"""Continuous session holder — keeps the ownerville login warm so SCHEDULED,
UNATTENDED report runs never hit Cloudflare's 'verify you're human'.

WHY (Megan 2026-06-17): Cloudflare globally tightened — the interactive Turnstile
now appears on a FRESH login even in a normal browser, on every machine. There is
no headless way past a forced interactive challenge, and the vendors won't expose
an API. The only thing that ALWAYS works unattended is to NEVER do a fresh login.

SUPERSEDED FOR OWNERVILLE (2026-09-02). The paragraph above is still true of
AppStream, but ownerville's Cloudflare now auto-passes automation — measured on
Lucy 1 2026-09-01: "ownerville form login reached a LIVE session UNATTENDED (rqst
present)". So NO HUMAN IS REQUIRED to bring this session back. Keeping the warm
session is still the fast path and still what this file is for; the difference is
that every recovery path now DRIVES THE LOGIN FORM (_unattended_ownerville_login)
before it will ever ask a person. It asks a human only after that fails.
A cold Lucy is a fault, not a constraint. [[feedback_lucys_always_warm]]

ownerville is the session this holds warm: with a fresh exported ownerville
storage_state, a HEADLESS run reaches Tableau via ownerville SSO. So the holder
keeps ownerville logged in — that one session covers every Tableau/ownerville
report.

AppStream: OPT-IN (restored 2026-08-05, was dropped 2026-06-30 when its Cloudflare
eased — it's back for office 11580). If this machine has been seeded once with
`--appstream-login` (APPSTREAM_STORAGE_STATE exists), the holder ALSO keeps the
applicantstream console warm so the batch/resume side rides a held session instead
of a flaky fresh login. Un-seeded machines (the mini) stay ownerville-only — no 3rd
tab, no per-cycle AppStream nav. All AppStream work is try/except-contained so it
can never crash the ownerville holder.

HOW: a human clears Cloudflare ONCE in the holder's window, then it keeps that
session alive 24/7 (never closes → never re-challenged) and every few minutes
EXPORTS the live cookies into the storage_state file the reports reuse
(tableau_patchright._reuse_ownerville_storage_state). Scheduled runs load that and
skip the login + Turnstile entirely.

SEED is non-disruptive: a SEPARATE validation page polls v2.ownerville for a live
rqst token while the human logs in on the login page — it never navigates the
human's page out from under them (the bug in the first cut).

DEGRADES SAFELY: if the session goes stale it logs back in UNATTENDED, keeps the
last good export until that succeeds, and only alerts for a human if the login
itself fails. (Before 2026-09-02 it refused to drive the form at all and just
alerted — which reads fine at 2pm and is an outage at midnight.)

Run on the always-on schedule machine (Mac mini; a laptop works while awake):

    python -m automations.shared.session_holder
    python -m automations.shared.session_holder --interval 6

Cross-platform (mac + windows). Ctrl-C to stop.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

# Which machine is this? Read the gitignored `.machine-profile` marker at the repo
# root directly (the SAME marker registry/mini_control use) — a lightweight read so
# `shared` doesn't import `day_orchestrator`. Absent → "Lucy 1".
_MACHINE_MARKER = Path(__file__).resolve().parents[2] / ".machine-profile"

# WHICH MACHINES KEEP THE APPSTREAM CONSOLE WARM.
#
# Was a single machine ("Lucy 2", office 11580). The gate existed so a machine
# carrying a STALE .appstream_storage_state.json from before the 2026-06-30
# removal couldn't silently re-activate warming — a good reason, and the reason
# this is a list rather than "any machine with a seed file".
#
# BACK TO ONE HOLDER, 2026-08-29 (Megan: "before we added Lucy 3, the other two
# Lucys were working great and no re-seeding was needed. We need to do whatever
# was being done then.") She is right, and the git history says so plainly.
#
# Until `a965a8a` (2026-08-24 19:08, "all three Lucys keep AppStream warm") this
# was `APPSTREAM_HOLD_MACHINE = "Lucy 2"` — a SINGLE machine held a live console
# and every other runner simply consumed the session it pushed. The re-seeding
# began after that commit, not before.
#
# WHY THREE HOLDERS ATE THEMSELVES — PAST TENSE SINCE 2026-09-02. It was true
# while all three ran the SAME shared rcaptain account; each now signs in as its
# own login, so the mutual invalidation below no longer applies. Kept because it
# explains why the fleet was ever built donor-and-consumer, and because the
# mechanism returns the moment two machines share an account again. Read the
# paragraph after it for what actually holds today. All three ran the same
# rcaptain account, and
# this module already records the mechanism a few lines down in
# _push_token_to_fleet: "Renewing appears to INVALIDATE the token the donor
# handed out last time — which every other machine is still holding. So an
# hour's delay is not an hour of slightly-stale tokens, it is an hour of DEAD
# ones that still read as valid." With one holder that is a clean handoff. With
# three, each machine re-hops its own console every ~6 min on the same account,
# so they invalidate each other's tokens continuously and the fleet converges on
# everyone holding something dead that still reads valid — which is exactly the
# 2026-08-29 shape: all three dark on one shared expiry.
#
# The 8/24 reasoning was sound about the SYMPTOM (Lucy 1 and Lucy 3 let their
# tokens age out) and wrong about the CURE: what those machines needed was the
# donor's session pushed to them, which they now get, not a competing console of
# their own.
#
# EVERY LUCY HOLDS ITS OWN AGAIN, 2026-09-02 (Megan: "All 3 lucy's should each
# hold their own and not rely on each other — we've proven the last 2 weeks that
# doesn't work"). The single-holder design above is REVERSED. Two weeks of it is
# the evidence: a machine whose only source of a session is somebody else's push
# is dark for as long as that push is late, and on 2026-09-02 Lucy 1 sat with an
# expired token through the whole 4am batch — daily_focus, applicant_sync_morning
# and recruiter_retention_daily all died — with no inbound push all morning while
# a human drove five manual logins.
#
# WHAT ABOUT THE MUTUAL-INVALIDATION MECHANISM the 8/29 note describes? It is
# real, and it is a same-ACCOUNT problem, not a same-design problem: three
# consoles re-hopping one rcaptain login invalidate each other's tokens. The fix
# is the per-person login migration (each Lucy signs in as its OWN account), not
# making two machines depend on a third. Until every Lucy has its own account,
# expect some token churn here — that is the known cost of this trade, and it is
# strictly better than a machine that cannot recover on its own.
APPSTREAM_HOLD_MACHINES = ("Lucy 1", "Lucy 2", "Lucy 3")
# Back-compat for anything importing the old singular name.
APPSTREAM_HOLD_MACHINE = APPSTREAM_HOLD_MACHINES[0]

# WHO RECEIVES the pushed session — every runner that RUNS AppStream reports,
# which is all three. Deliberately separate from who HOLDS one: consuming a
# donated session costs nothing and is what keeps Lucy 1 and Lucy 3 alive;
# holding a competing console is what broke them.
APPSTREAM_FLEET_MACHINES = ("Lucy 1", "Lucy 2", "Lucy 3")

# RE-MINT THE rqst TOKEN BEFORE IT DIES, not after (Megan 2026-08-27).
#
# The rqst SSO token lives ~2h. Until now the holder rode one until it expired
# and only THEN re-hopped the storage_state to get another — which is the one
# moment the hop cannot work, because the token it hands the server in
# `?rqst=<TOKEN>&p=701` is the dead one. What it gets back is a console that
# RENDERS (ColdFusion's CFID/CFTOKEN are still good, and the holder's own reload
# keeps those alive for 24h) but carries no token, so `_export_appstream` writes
# nothing and every AppStream report fails until a human re-seeds.
#
# That is exactly what happened today on Lucy 1: last good export 08:38:46, the
# token expired 08:41, and the holder printed "console warm but NO rqst token"
# every ~6 min for the next TEN HOURS without ever recovering. Twenty cycles
# inside the token's live window did nothing, because a healthy cycle returned
# early and never re-hopped.
#
# So: once the token is inside its last REMINT_MARGIN_MIN, act on every cycle
# while it is still live. If nothing is minted we keep the still-valid token and
# try again next cycle.
#
# CORRECTION (2026-08-29) — the margin was right, the ACTION was wrong. This
# originally re-hopped the storage_state, on the belief that a hop performed
# early enough could "mint its successor". It cannot, at any time: replaying
# `?rqst=<SAVED TOKEN>&p=701` restores a session but never issues a token
# (measured 8/27 — same id every cycle inside the margin, then expiry). So the
# holder counted its token down to zero while dutifully re-hopping, and only
# came back when a fleet push or a RESTART minted for it. Overnight neither
# happens: no console work is scheduled between midnight and 4am, which is why
# the session was dead at 3:00 AM with the batch an hour out.
# The margin now runs _mint_appstream_via_ownerville, which asks ownerville —
# the session this process holds warm 24/7 — for a genuinely new token.
REMINT_MARGIN_MIN = 30.0

# OWNERVILLE MINT — ON, and the reason it failed this morning is understood.
#
# Ownerville issues a fresh rqst on demand, unattended (measured 10:04 on
# 2026-08-29: it handed over 43A275AE while we held 083AE947). That was never
# the problem. The problem was HOW the token was applied:
#
#   • v1 called _sso_to_appstream(page), which navigates the CONSOLE tab to
#     v2.ownerville.com and back. Navigating that tab away tears down the live
#     AppStream session, so the hop back has to establish a NEW one — and a NEW
#     session is precisely what the 2026-08-20 Turnstile refuses. #searchMC
#     never rendered, at 10:04 and again at 10:50 with waits and a retry.
#   • The reuse path shows the shape that works: leave the session ALONE and
#     navigate the console tab to `?rqst=<TOKEN>&p=701`. That renders every
#     time, which is how every report and every fleet push lands.
#
# So the token is now read in its OWN tab (_fresh_rqst_from_ownerville) and the
# console tab is only ever RE-KEYED, never torn down. Same navigation the
# working path uses; the only difference is a new token instead of a saved one.
#
# Still throttled (MINT_MIN_INTERVAL_MIN): v1 ran every ~6 min for an hour
# against the SSO endpoint, and while a failing mint is cheap it is not free.
# On failure the caller falls back to the replay, so a bad attempt costs a
# navigation, not the session.
MINT_VIA_OWNERVILLE = True
# Never more than one attempt per this many minutes, even when enabled.
MINT_MIN_INTERVAL_MIN = 30.0
_LAST_MINT_ATTEMPT: dict = {"at": 0.0}

# THE THROTTLE HAS TO SURVIVE A RELAUNCH (2026-09-01, third lesson of the day).
#
# _LAST_MINT_ATTEMPT is module state, so it resets to 0.0 every time launchd
# relaunches the holder. Once the tokenless escalation below started asking for
# restarts, that produced a LOOP: fresh process -> throttle looks unset -> mint
# -> fail -> ask for restart -> exit(1) -> relaunch -> repeat, every ~45s.
# Measured on Lucy 2 while the session was dead:
#
#   07:59:55  exiting (rc=1) so launchd relaunches the holder
#   08:00:49  exiting (rc=1) ...
#   08:02:00  exiting (rc=1) ...
#   08:02:41  exiting (rc=1) ...
#
# Escalating once is the fix; escalating every 45 seconds is a hot loop against
# ownerville's SSO, which is exactly the kind of traffic that got the fleet
# flagged before [[project_tableau_access_budget]]. Persisting the timestamp
# makes MINT_MIN_INTERVAL_MIN mean what it says across process boundaries, so a
# tokenless night costs one restart per interval instead of eighty an hour.
_MINT_STAMP = Path(__file__).resolve().parent / ".appstream_last_mint_attempt"


def _last_mint_attempt() -> float:
    """Epoch of the last REAL mint attempt, surviving a holder relaunch.

    The on-disk stamp is consulted ONLY inside the holder's own loop (main()
    sets `holder_loop`). Library callers and tests set _LAST_MINT_ATTEMPT
    directly and mean it literally — reading a stamp left by some other process
    underneath them made five existing remint tests fail and, worse, would let a
    stale file suppress a mint that a caller had explicitly asked for."""
    if _LAST_MINT_ATTEMPT["at"]:
        return float(_LAST_MINT_ATTEMPT["at"])
    if not _MINT_FAILURES.get("holder_loop"):
        return 0.0
    try:
        return float(_MINT_STAMP.read_text().strip())
    except Exception:  # noqa: BLE001 — no stamp yet is simply "never attempted"
        return 0.0


def _record_mint_attempt(now: float) -> None:
    _LAST_MINT_ATTEMPT["at"] = now
    if not _MINT_FAILURES.get("holder_loop"):
        return                      # library/test use leaves no trace on disk
    try:
        _MINT_STAMP.write_text(str(now))
    except Exception:  # noqa: BLE001 — best effort; in-memory still throttles
        pass

# CONSECUTIVE FAILED MINTS BEFORE THE HOLDER RESTARTS ITSELF (Megan 2026-08-31).
#
# On 8/31 the mint failed from ~15:05 to 19:21 — every attempt re-keying the
# SAME token (66F074FE at 16:57 and again at 18:54), because ownerville's warm
# page keeps handing back the token it already issued. The holder logged "session
# stale — re-seed once" to itself for four hours and paged a human at 18:43.
#
# A RESTART mints. It is in this file's own record: on 8/29 a token reached
# `1m left` at 08:04, the holder restarted on a code change at 08:10, and by
# 08:11 it was handing a fresh one to the fleet — "the restart minted what four
# re-hop cycles could not". A restart builds a fresh context instead of re-reading
# a cached page, so ownerville issues rather than repeats.
#
# So a mint that keeps failing takes the restart path this file already uses for
# a code change, a dead browser and a stale export. Two failures, not one: mints
# are throttled to one per MINT_MIN_INTERVAL_MIN and a single miss can be
# ownerville mid-refresh, which the existing replay fallback rides out. Two in a
# row inside the re-mint margin means the token is going to die anyway — at that
# point a restart cannot be worse than doing nothing, which is what four hours of
# 8/31 actually were.
MINT_FAILURES_BEFORE_RESTART = 2
_MINT_FAILURES: dict = {"n": 0}


def _note_mint_result(ok: bool) -> int:
    """Record a mint outcome; returns the consecutive-failure count."""
    _MINT_FAILURES["n"] = 0 if ok else _MINT_FAILURES["n"] + 1
    return _MINT_FAILURES["n"]


def _mint_is_throttled() -> bool:
    """True when MINT_MIN_INTERVAL_MIN has not elapsed, so a False from
    _mint_appstream_via_ownerville means 'did not try', not 'tried and failed'.

    Callers that escalate on failure MUST check this first: the mint returns
    False for both, and treating the throttle as a failure turns the holder's
    restart ladder into a relaunch loop driven by nothing but the clock."""
    return (time.time() - _last_mint_attempt()) / 60.0 < MINT_MIN_INTERVAL_MIN


def _this_machine() -> str:
    try:
        v = _MACHINE_MARKER.read_text().strip()
        if v:
            return v
    except Exception:
        pass
    return "Lucy 1"

from patchright.sync_api import sync_playwright

from automations.shared.tableau_patchright import (
    PROFILE_DIR,
    _drive_login_form,
    _launch_persistent,
    _ownerville_session_valid,
    _reuse_appstream_storage_state,
    _sso_to_appstream,
    OWNERVILLE_STORAGE_STATE,
    APPSTREAM_STORAGE_STATE,
    LOGIN_URL,
    OWNERVILLE_V2_URL,
    APPSTREAM_BASE,
)

# The holder runs CONTINUOUSLY, so it must NOT use the reports' profile —
# a held-open persistent profile would lock out every report run. It keeps the
# session in its OWN profile and shares it via the exported storage_state.
HOLDER_PROFILE_DIR = PROFILE_DIR.parent / ".browser_profile_holder"


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_head() -> str:
    """This repo's HEAD, or '' if it can't be read.

    Best-effort by design: any failure answers '' and the caller treats that as
    "no change", so a git hiccup can never restart or stall the holder."""
    try:
        import subprocess
        r = subprocess.run(["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001 — bookkeeping must never break the holder
        return ""


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _browser_alive(ctx) -> bool:
    """Cheap liveness probe for the holder's Chrome. A persistent context's
    .browser is None, so is_connected() isn't available; instead confirm at
    least one page exists and isn't closed. A crashed browser reports its pages
    closed (or raises on access) -> False, which the loop turns into a clean
    exit so launchd relaunches the job (fixes the 2026-06-30 dead-Chrome /
    live-Python orphan where the session silently went cold)."""
    try:
        pages = ctx.pages
        return bool(pages) and any(not pg.is_closed() for pg in pages)
    except Exception:
        return False


def _export_ownerville(ctx) -> int:
    """Write the live ownerville (master SSO) cookies to OWNERVILLE_STORAGE_STATE.
    Only called when the session is confirmed live, so a good export is never
    clobbered with dead cookies."""
    cookies = ctx.storage_state().get("cookies", [])
    ov = [c for c in cookies if "ownerville" in (c.get("domain") or "")]
    OWNERVILLE_STORAGE_STATE.write_text(json.dumps({"cookies": ov, "origins": []}))
    return len(ov)


# NO HUMAN IS REQUIRED TO LOG THIS SESSION BACK IN (Megan 2026-09-02).
#
# This file was written in June on a premise that has since been MEASURED FALSE:
# "there is no headless way past a forced interactive challenge, so never do a
# fresh login." Ownerville's Cloudflare auto-passes automation — measured on
# Lucy 1 2026-09-01: "ownerville form login reached a LIVE session UNATTENDED
# (rqst present)", which is why appstream_autorenew.refresh_ownerville exists and
# works. The holder never picked that up, so both of its recovery paths still
# ended at a prompt in a window nobody is sitting in front of.
#
# That cost the night of 2026-09-01: the mint failed at 23:48, the holder exited
# for a relaunch at 23:54, printed "SEED: log into ownerville in the window" at
# 23:54:31, and waited. Nobody was there at midnight. Ownerville stayed dark
# through the 4am batch (applicant_sync_morning, recruiter_retention_daily and
# daily_focus all failed) until a human logged in at 08:26. The relaunch ladder
# above CANNOT fix this on its own: it re-seeds from the persistent profile's
# cookies, and last night those cookies were themselves dead.
#
# So: drive the form. A cold session is a fault, not a constraint.
# [[feedback_lucys_always_warm]]
LOGIN_MIN_INTERVAL_MIN = 15.0
_LAST_LOGIN_ATTEMPT: dict = {}


def _unattended_ownerville_login(ctx, page, verbose: bool = True) -> bool:
    """Log ownerville back in WITHOUT a human, in the holder's own profile.

    Returns True only when the session is genuinely live afterwards (a real rqst
    — `_ownerville_session_valid`, not merely a page that rendered).

    THROTTLED. A failing login retried every 6-minute cycle would hammer the
    form all night and is exactly the kind of loop that earns a challenge; one
    attempt per LOGIN_MIN_INTERVAL_MIN is plenty against a 25-minute
    no-export deadline, and the passive human check still runs every cycle.

    Runs in the CALLER's playwright loop by design — the holder is already
    inside sync_playwright(), so it cannot call refresh_ownerville (that starts
    its own and declines; see appstream_autorenew._inside_playwright_loop). This
    is the same login refresh_ownerville drives, minus the throwaway profile:
    we WANT the session to land in the holder's persistent profile."""
    last = _LAST_LOGIN_ATTEMPT.get("at", 0.0)
    if last and (time.time() - last) / 60 < LOGIN_MIN_INTERVAL_MIN:
        return False
    _LAST_LOGIN_ATTEMPT["at"] = time.time()
    print(f"[{_stamp()}] ownerville cold — driving the login form UNATTENDED "
          f"(no human needed; retry no sooner than {LOGIN_MIN_INTERVAL_MIN:g} min).",
          flush=True)
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3_000)
        # ALREADY SIGNED IN IS NOT A FAILURE — ownerville can redirect straight
        # past the form, and then filling the password times out on a session
        # that is perfectly live. Judge on the SESSION, not on whether we got to
        # type into it (the mistake refresh_ownerville had to correct 2026-09-01).
        try:
            _drive_login_form(page, verbose=verbose)
        except Exception as e:  # noqa: BLE001 — the validity check below judges
            print(f"[{_stamp()}] login form not driven ({type(e).__name__}) — "
                  f"checking whether we are already signed in", flush=True)
        if not _ownerville_session_valid(page, verbose=False):
            print(f"[{_stamp()}] unattended login did NOT reach a live session — "
                  f"a human login in the window would still fix it.", flush=True)
            return False
        ovn = _export_ownerville(ctx)
        print(f"[{_stamp()}] unattended login ✓ — session live again, exported "
              f"{ovn} ownerville cookies. No human was involved.", flush=True)
        return True
    except Exception as e:  # noqa: BLE001 — never take the holder down for this
        print(f"[{_stamp()}] unattended login error: {type(e).__name__}: "
              f"{str(e)[:160]}", flush=True)
        return False


# --------------------------------------------------------------------------- #
# AppStream warming — RESTORED 2026-08-05 (was dropped 2026-06-30 in 94f4f21 when
# AppStream's Cloudflare eased). It's back for office 11580, so the batch/resume
# side needs a continuously-warm applicantstream console again. This is OPT-IN and
# CONTAINED: it only runs when APPSTREAM_STORAGE_STATE exists (a machine seeded via
# `--appstream-login`, i.e. Lucy 2), so the mini stays byte-for-byte ownerville-only;
# and every call site wraps it in try/except so an AppStream hiccup can NEVER crash
# the ownerville holder or trip its watchdog (the instability that motivated the
# original removal). Restored from commit e7661e9.
# --------------------------------------------------------------------------- #
def _export_appstream(ctx) -> int:
    """Write the live applicantstream cookies (CFID/CFTOKEN + rqst SSO token) to
    APPSTREAM_STORAGE_STATE. GUARD: only export if the session carries an rqst SSO
    token — a degraded/SSO-only console can have applicantstream cookies but ZERO
    rqst tokens, and writing that clobbers a good rcaptain login and kills the
    direct-session reports. No token → keep the last good export untouched."""
    cookies = ctx.storage_state().get("cookies", [])
    ap = [c for c in cookies if "applicantstream" in (c.get("domain") or "")]
    n_rqst = sum(1 for c in ap if (c.get("name") or "").lower().startswith("rqst"))
    if not (ap and n_rqst):
        return 0
    # NEVER OVERWRITE A FRESHER SESSION THAN OUR OWN (2026-09-01).
    #
    # The holder re-exports its context every cycle. Its context can be holding
    # an OLD token — one pushed to it hours ago — while something else has just
    # put a genuinely newer one on disk. Then this line clobbers the new session
    # with the stale one, every six minutes, and the renewal silently evaporates.
    #
    # Watched live: Lucy 1 self-renewed to a full 120 minutes at 15:17, and
    # seconds later the file was back to AE4BC60A with 10 minutes on it — the
    # token the holder had been carrying since a 13:28 push. That is why
    # renewals "worked" and then were gone, and why a person kept being asked to
    # log in again.
    #
    # The rule is simply: an export must move the session FORWARD.
    try:
        mine = _best_rqst_minutes(ap)
        theirs = _best_rqst_minutes(
            json.loads(APPSTREAM_STORAGE_STATE.read_text()).get("cookies", []))
    except Exception:  # noqa: BLE001 — unreadable/missing disk state: ours wins
        mine, theirs = 1.0, 0.0
    if theirs > mine + 1.0:
        print(f"[{_stamp()}] not exporting — the saved session has "
              f"{theirs:.0f}m left and ours only {mine:.0f}m; keeping the "
              f"fresher one", flush=True)
        return 0
    APPSTREAM_STORAGE_STATE.write_text(json.dumps({"cookies": ap, "origins": []}))
    return len(ap)


def _best_rqst_minutes(cookies) -> float:
    """Minutes on the longest-lived rqst cookie in `cookies` (0.0 = none)."""
    now = time.time()
    best = 0.0
    for c in cookies or ():
        if not str(c.get("name") or "").lower().startswith("rqst"):
            continue
        e = c.get("expires")
        if isinstance(e, (int, float)) and e > 0:
            best = max(best, (e - now) / 60.0)
    return best


def _ctx_rqst_count(ctx) -> int:
    """How many applicantstream rqst_ SSO tokens the LIVE context is carrying.

    This is the thing reports actually need. A console can render without one:
    ColdFusion keeps #searchMC alive off CFID/CFTOKEN, which the holder's own
    reload refreshes forever."""
    try:
        return sum(1 for c in ctx.storage_state().get("cookies", [])
                   if "applicantstream" in (c.get("domain") or "")
                   and (c.get("name") or "").lower().startswith("rqst"))
    except Exception:  # noqa: BLE001 — a probe must never break the holder
        return 0


# WHOSE ✓ IS IT? (Megan 2026-08-27: "we've built the fix like 10 times").
# The holder printed `AppStream ✓ — 9 cookies` every six minutes whether it had
# just obtained a NEW login or was riding the same one down to its expiry. Both
# look identical, so ten rounds of fixes were each judged against a signal that
# cannot tell "renewed" from "still alive" — including the note in Megan's memory
# claiming the token renews itself overnight, which was inferred from an expiry
# timestamp, never observed. Until the log can say which happened, the next fix
# is another guess. So: name the token and say when it changes.
_LAST_RQST: dict = {"id": None}


def _rqst_id(ctx) -> str | None:
    """A short, stable name for the rqst token the LIVE context is carrying, so
    consecutive cycles can be compared. The token IS the cookie name
    (`rqst_<TOKEN>`); we print a prefix, never the whole credential."""
    try:
        names = sorted(c.get("name") or "" for c in ctx.storage_state().get("cookies", [])
                       if "applicantstream" in (c.get("domain") or "")
                       and (c.get("name") or "").lower().startswith("rqst_"))
        return names[-1][len("rqst_"):][:8] if names else None
    except Exception:  # noqa: BLE001 — a probe must never break the holder
        return None


def _donated_token_ids() -> set:
    """Token ids a fleet handoff installed on THIS machine (set_appstream_state
    writes the marker). Used only to keep the log honest — see _rqst_note."""
    try:
        return {ln.strip() for ln in APPSTREAM_STORAGE_STATE.with_name(
            ".appstream_donated_token").read_text().splitlines() if ln.strip()}
    except Exception:  # noqa: BLE001
        return set()


def _rqst_note(ctx) -> str:
    """The half of the ✓ line that actually carries information: which token,
    how long it has left, and whether it just CHANGED (the only proof that
    anything renewed). Never raises — worst case it adds nothing."""
    try:
        tok = _rqst_id(ctx)
        if not tok:
            return ""
        left = _ctx_rqst_minutes_left(ctx)
        life = f", {left:.0f}m left" if left is not None else ""
        prev = _LAST_RQST.get("id")
        _LAST_RQST["id"] = tok
        if prev and prev != tok:
            # A DONATION IS NOT A RENEWAL. Both change the token id, so a
            # machine that cannot renew at all would print RENEWED minutes after
            # a handoff landed — and we would read the self-heal as working.
            # That is the `AppStream ✓ — 9 cookies` mistake one level up, and
            # this log line is now what the AppStream work is being steered by.
            if tok in _donated_token_ids():
                return f" · token {tok}{life} · RECEIVED from the fleet"
            _push_token_to_fleet(urgent=True)
            return f" · token {tok}{life} · RENEWED (was {prev})"
        return f" · token {tok}{life}"
    except Exception:  # noqa: BLE001
        return ""


# NOBODY SHOULD EVER HAVE TO RE-SEED (Megan 2026-08-27).
#
# Today Lucy 1 and Lucy 3 sat tokenless for ten hours while Lucy 2's holder was
# exporting a LIVE session the entire time, never more than six minutes stale.
# All three ran the same rcaptain account, and one machine's session worked on
# any of them — the fix was already on the fleet, and the only way to move it
# was to ask a person to clear a Turnstile that did not need clearing.
#
# BOTH HALVES OF THAT ARE NOW FALSE (2026-09-02), which is why the handoff below
# never fires between Lucys any more. Each machine signs in as its OWN account,
# so one machine's session does NOT work on another — installing it makes that
# machine the wrong person. And nobody has to clear a Turnstile: the check
# clears itself given ~30s before submit, so a tokenless machine logs ITSELF
# back in. The answer to "Lucy 1 has no token" is a login on Lucy 1, not a
# donation from Lucy 2.
#
# So a holder that RENEWS its token hands the new one to the other hold
# machines. A machine whose own renewal fails is then carried by whichever one
# succeeded, and it takes all three failing at once — not any one of them — to
# need a human. There are two triggers, and only one of them may be throttled.
#
# A RENEWAL MUST GO OUT AT ONCE. Renewing appears to INVALIDATE the token the
# donor handed out last time — which every other machine is still holding. So an
# hour's delay is not an hour of slightly-stale tokens, it is an hour of DEAD
# ones that still read as valid, because a cookie's expiry is a clock and not a
# statement about the server. That is exactly where the fleet was caught at
# 2026-08-28 19:47: Lucy 1 and Lucy 3 both sat on EA30849A showing "18m left"
# while Lucy 2 had already moved to EC854530; their holders printed ✓ off
# consoles opened before the switch, and the watch was right that no report
# could open one. Throttling this push was the defect.
#
# The other trigger — "I am alive, here is my session", on any live export — is
# what carries a machine that cannot renew at all. That one keeps the hourly
# floor: it has nothing new to say, so its only cost is queue rows.
#
# Fully contained: any failure here is logged and dropped. Handing off a session
# must never be able to take down the thing holding it.
FLEET_PUSH_MIN_INTERVAL_MIN = 60.0
_LAST_FLEET_PUSH: dict = {"at": 0.0}


def _push_token_to_fleet(verbose: bool = True, urgent: bool = False) -> None:
    """Give the just-renewed session to the other AppStream hold machines.

    urgent=True bypasses the hourly floor. A RENEWAL is always urgent, and the
    floor was actively harmful there — see FLEET_PUSH_MIN_INTERVAL_MIN.

    Sends the SAME payload the human re-seed's second half sends
    (`--appstream-push-fleet` → each machine's `set_appstream_state`), so the
    landing side is unchanged and still installs + verifies its own copy and
    refuses a state carrying no rqst_ token."""
    now = time.time()
    if not urgent and (now - _LAST_FLEET_PUSH["at"]) / 60.0 < FLEET_PUSH_MIN_INTERVAL_MIN:
        return
    try:
        blob = APPSTREAM_STORAGE_STATE.read_text()
        if not sum(1 for c in json.loads(blob).get("cookies", [])
                   if str(c.get("name", "")).startswith("rqst_")):
            return          # never distribute a session that can't open a console
        from automations.day_orchestrator import mini_control as mc
        me = _this_machine()
        # NEVER TO A MACHINE THAT HOLDS ITS OWN. Once each Lucy signs in as its
        # OWN account, a push is not a favour — it is an identity swap. Lucy 1
        # authenticates as 'Lucy Reports' (account 23981, 8 offices); Lucy 2 is
        # Carlos. Handing one machine's storage_state to the other replaces WHO
        # that machine is, and every office lookup behind it silently becomes the
        # wrong account's — the same class of failure as Lucy 2's "rcaptain"
        # verify actually running as Carlos Hidalgo (2026-08-20).
        #
        # That is the real content of "each hold their own and not rely on each
        # other" (Megan 2026-09-02), and it is why the filter is here at the
        # SENDER rather than a freshness check at the receiver: the objection is
        # not that the pushed session is stale, it is that it belongs to somebody
        # else.
        #
        # With all three holding, this list is normally empty and no automatic
        # push happens at all. It stays for a machine added to the fleet before
        # it has its own login, and `--appstream-push-fleet` remains the
        # deliberate operator hand-off.
        sent = [m for m in APPSTREAM_FLEET_MACHINES
                if m != me and m not in APPSTREAM_HOLD_MACHINES]
        for m in sent:
            mc.enqueue("set_appstream_state", blob, by="holder-renewal", machine=m)
        _LAST_FLEET_PUSH["at"] = now
        if verbose and sent:
            print(f"[{_stamp()}] AppStream → handed the fresh token to "
                  f"{', '.join(sent)}", flush=True)
    except Exception as e:  # noqa: BLE001 — a handoff must never break the holder
        print(f"[{_stamp()}] AppStream fleet handoff skipped: "
              f"{type(e).__name__}: {str(e)[:110]}", flush=True)


def _ctx_rqst_minutes_left(ctx) -> float | None:
    """Minutes until the LIVE context's rqst token expires (the latest one, the
    same one `appstream_watch.session_status` reads). None when the context
    carries no dated token — treat that as "don't know", not as "expiring"."""
    try:
        exps = [c.get("expires") for c in ctx.storage_state().get("cookies", [])
                if "applicantstream" in (c.get("domain") or "")
                and (c.get("name") or "").lower().startswith("rqst")
                and isinstance(c.get("expires"), (int, float)) and c["expires"] > 0]
        if not exps:
            return None
        return (max(exps) - time.time()) / 60.0
    except Exception:  # noqa: BLE001 — a probe must never break the holder
        return None


_RQST_RE = re.compile(r"rqst=([A-Za-z0-9_-]+)")

# TOKENS THIS PROCESS HAS ALREADY PROVED DEAD (Megan 2026-09-01).
#
# Ownerville's warm page re-serves the SAME token id for hours — 66F074FE was
# handed back at 8/31 16:57, 8/31 18:54, 9/1 04:33 and 9/1 05:36, i.e. the same
# id across two days and every mint attempt in between. Each of those attempts
# navigated the console tab to `?rqst=66F074FE&p=701`, got no #searchMC, and
# logged "ownerville hop landed without a console" — which reads like an
# AppStream/Turnstile fault when it is really a stale READ on our side.
#
# Remembering the ids we have already burned turns that into an honest, instant
# "ownerville re-served a dead token" instead of a wasted console navigation and
# a misleading log line. Process-local on purpose: a RESTART is what mints (see
# MINT_FAILURES_BEFORE_RESTART), so a fresh process must start with a clean
# slate and be free to accept whatever ownerville issues it.
_DEAD_TOKENS: set = set()

# DOES THIS MACHINE'S OWNERVILLE IDENTITY EVEN HAVE APPSTREAM? (2026-09-02)
#
# The ownerville hop can only mint where the signed-in ownerville identity is
# offered program 701. On Lucy 1 it is NOT: that login is Rafael Hidalgo (ICD,
# office 11280), and a read of the dashboard lists ~90 program codes — p=81
# (Tableau) among them, p=701 absent. So every mint attempt there hops, gets no
# console, and logs "AppStream mint FAILED — ownerville hop landed without a
# console" — once per cycle, forever, for a condition no retry can change.
#
# That line is indistinguishable from the real failure it was written for, and
# today proved what a misleading log line costs: this one sat next to genuine
# alerts all morning while the actual fault (a mistyped username) went unlooked
# at. So decide the question ONCE from the dashboard itself, say so once in
# plain terms, and stop attempting.
#
# Process-local, like _DEAD_TOKENS: a restart re-checks, so granting the account
# p=701 takes effect on the next holder start with no code change.
_OV_APPSTREAM: dict = {"offered": None, "announced": False}


def _tok8(tok) -> str:
    """The 8-char upper-case id form `_rqst_id` uses, so a freshly scraped token
    (full length) and a context token (already truncated) can be compared at
    all. Without this the "did ownerville hand back the same one?" check silently
    never matches, which is how the repeat went unnoticed for two days."""
    return (tok or "")[:8].upper()


def _fresh_rqst_from_ownerville(ctx) -> str | None:
    """A NEW rqst token, read from the warm ownerville session in its OWN tab.

    Deliberately does NOT touch the AppStream console tab. Ownerville is the
    issuer — it hands out a fresh token on request, unattended, and this process
    already holds a valid ownerville login 24/7 (measured 8/29: it issued
    43A275AE on demand at 10:04). Everything here is read-only navigation of
    ownerville's own page; the token is then applied to the console tab by the
    caller, the same way the reuse path applies a saved one.

    CACHE-BUSTED (2026-09-01). This used to `goto(OWNERVILLE_V2_URL)` on a
    context that has been alive for days, so the SSO link could be read straight
    out of the browser's cached copy of the dashboard — the same href, carrying
    the same long-dead token, every time. That is the difference between this
    path and a RESTART, which mints reliably precisely because a fresh context
    has nothing cached and must fetch the page for real. A unique query param
    plus a cache-ignoring reload makes the warm process fetch it for real too.

    None on any failure — a mint we cannot do is a missed cycle, never a raise."""
    page = None
    try:
        page = ctx.new_page()
        _bust = f"{OWNERVILLE_V2_URL}?_cb={int(time.time())}"
        page.goto(_bust, wait_until="domcontentloaded")
        # Belt and braces: even with a unique URL, ask for a hard reload so any
        # intermediate/disk cache is bypassed rather than revalidated.
        try:
            page.reload(wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001 — the goto above is the load that matters
            pass
        page.wait_for_timeout(5_000)
        # Answer "is p=701 offered to this identity?" HERE, off the page we are
        # already loading, so the check costs no extra navigation. A dashboard
        # that lists other programs but no 701 is the structural case; a page
        # with no program links at all is inconclusive (still loading, or a
        # redirect), so leave the verdict unset rather than latch a false
        # negative that would disable minting until the next restart.
        try:
            _n701, _nprog = page.evaluate(
                "() => { const a=[...document.querySelectorAll('a')]"
                ".map(x=>x.getAttribute('href')||'');"
                " return [a.filter(h=>/p=701/.test(h)).length,"
                "         a.filter(h=>/[?&#]p=\\d+/.test(h)).length]; }")
            if _n701:
                _OV_APPSTREAM["offered"] = True
            elif _nprog:
                _OV_APPSTREAM["offered"] = False
        except Exception:  # noqa: BLE001 — a diagnosis must never break the mint
            pass
        m = _RQST_RE.search(page.url or "")
        if not m:
            href = page.evaluate(
                "() => { const a=[...document.querySelectorAll('a')]"
                ".find(x=>/p=701/.test(x.getAttribute('href')||'')); "
                "return a?a.getAttribute('href'):''; }")
            m = _RQST_RE.search(href or "")
        if not m:
            m = _RQST_RE.search(
                page.evaluate("() => document.documentElement.innerHTML") or "")
        return m.group(1) if m else None
    except Exception as e:  # noqa: BLE001 — never raise into the holder
        print(f"[{_stamp()}] AppStream mint — ownerville token read failed: "
              f"{type(e).__name__}: {str(e)[:110]}", flush=True)
        return None
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass


def _mint_appstream_via_ownerville(ctx, page, verbose: bool = False) -> bool:
    """Mint a genuinely NEW rqst token by re-running ownerville's SSO hop.

    THE THING THE HOLDER WAS MISSING (2026-08-29). There are two hops and only
    one of them mints:

      • `_reuse_appstream_storage_state` replays a token we already have
        (`?rqst=<SAVED TOKEN>&p=701`). It RESTORES a session; it never ISSUES
        one. Measured 2026-08-27 with token-identity logging: the id was
        unchanged across every cycle inside the re-mint margin, then expired.
      • `_sso_to_appstream` goes to v2.ownerville.com and asks OWNERVILLE for a
        fresh token, then hops with that. This is where an rqst comes from —
        it is how the very first seed gets one, and how a holder RESTART gets
        one.

    The 8/27 re-mint fix wired the margin to the FIRST of those, so the holder
    faithfully re-hopped a dying token every cycle and minted nothing. It only
    ever came back with a fresh token when something else happened to mint: a
    fleet push, or a restart. Observed on Lucy 1 on 8/29: token 03F0A612 counted
    down to `1m left` at 08:04, the holder restarted on a code change at 08:10,
    and at 08:11 it was handing a fresh token to the fleet — the restart minted
    what four re-hop cycles could not. Overnight nothing restarts it and no
    console work is scheduled between midnight and 4am, so the token simply
    died: hence the 3:00 AM "session re-seed needed" with the batch an hour out.

    Ownerville is exactly what this process holds warm 24/7, so this path is
    available at 3am with no human. Read-only navigation (ownerville → p=701
    console); it never touches p=604 or any applicant action.

    True only when the context comes back holding a DIFFERENT token — "the hop
    ran" is not the claim, "we have a new token" is. [[reference_appstream_turnstile]]

    EVERY OUTCOME IS LOGGED UNCONDITIONALLY, not behind `verbose`. The holder's
    loop calls _warm_appstream(verbose=False), so a verbose-gated message here
    means a failed mint says NOTHING and the token just counts down — which is
    the exact shape of the bug this function exists to fix, and it cost a first
    attempt on 2026-08-29 (token 083AE947 sat at 21m left inside the margin with
    no line explaining why). If it can fail, it has to say so."""
    if not MINT_VIA_OWNERVILLE:
        return False
    now = time.time()
    if (now - _last_mint_attempt()) / 60.0 < MINT_MIN_INTERVAL_MIN:
        return False
    _record_mint_attempt(now)
    before = _rqst_id(ctx)
    # FETCH THE TOKEN IN A SEPARATE TAB. This is the whole fix. The first
    # version called _sso_to_appstream(page), which navigates THIS tab to
    # v2.ownerville.com and then back — and navigating the console tab away
    # tears down the live AppStream session, so the hop back has to establish a
    # NEW one, which is exactly what the 2026-08-20 Turnstile refuses
    # (#searchMC never rendered, 10:04 and 10:50 on 8/29).
    #
    # The reuse path proves the shape that DOES work: with the session left
    # intact, navigating the console tab to `?rqst=<TOKEN>&p=701` renders every
    # time. So do that — just with a token that is NEW instead of saved. The
    # console session is never torn down; it is only re-keyed.
    tok = _fresh_rqst_from_ownerville(ctx)
    if not tok:
        print(f"[{_stamp()}] AppStream mint FAILED — no rqst token on the warm "
              f"ownerville session (is ownerville logged in?)", flush=True)
        return False
    # CHECK FOR A REPEAT *BEFORE* SPENDING THE CONSOLE NAVIGATION (2026-09-01).
    #
    # There is already an `after == before` check below, but it fires only after
    # the hop has run — so a token we have provably burned still costs a full
    # re-key of the live console tab, and when it fails the log blames
    # AppStream ("hop landed without a console") rather than the stale read that
    # actually happened. On 8/31->9/1 that misattribution repeated for hours on
    # one id, 66F074FE.
    #
    # Re-keying the console to a DEAD token is not free either: it drops a
    # session that still had minutes on it. Refusing here keeps the token we
    # hold, names the real cause, and returns False so the caller's restart
    # ladder — the path this file documents as the one that actually mints —
    # gets its failure honestly.
    # STRUCTURAL, NOT A FAILURE. Ownerville handed us a token, but this identity
    # is not offered program 701, so the hop below cannot land a console no
    # matter how fresh the token is. Say it once, in terms that name the fix
    # (grant the ownerville login AppStream, or let this machine's own
    # applicantstream login carry it), then stay quiet — the alternative is one
    # false alarm every cycle for a condition retrying cannot change.
    if _OV_APPSTREAM.get("offered") is False:
        if not _OV_APPSTREAM["announced"]:
            _OV_APPSTREAM["announced"] = True
            print(f"[{_stamp()}] AppStream mint via ownerville is NOT AVAILABLE "
                  f"on this machine — its ownerville identity is not offered "
                  f"program 701, so the SSO hop can never reach the console. "
                  f"This is not a fault and will not be retried; AppStream here "
                  f"comes from this machine's own applicantstream login "
                  f"(appstream_autorenew). Grant that ownerville login p=701 to "
                  f"re-enable minting, then restart the holder.", flush=True)
        return False
    _t8 = _tok8(tok)
    if _t8 == _tok8(before) or _t8 in _DEAD_TOKENS:
        print(f"[{_stamp()}] AppStream mint FAILED — ownerville re-served the "
              f"same token {_t8} we already hold/burned (its warm page is "
              f"repeating, not issuing) — not re-keying the console with it.",
              flush=True)
        _DEAD_TOKENS.add(_t8)
        return False
    try:
        page.goto(f"{APPSTREAM_BASE}?rqst={tok}&p=701",
                  wait_until="domcontentloaded")
    except Exception as e:  # noqa: BLE001 — a mint attempt must never break the holder
        print(f"[{_stamp()}] AppStream mint FAILED (re-key nav): "
              f"{type(e).__name__}: {str(e)[:140]}", flush=True)
        return False
    # WAIT for the console the way the REPORTS' path waits for it.
    # _sso_to_appstream returns after a FIXED sleep and never confirms #searchMC,
    # so asking count() the instant it returns fails a console that simply had
    # not painted yet — which is precisely what happened on the first live
    # attempt (2026-08-29 10:04): ownerville handed over a genuinely NEW token
    # (43A275AE…, not the 083AE947 we held), the hop navigated to it, and the
    # check called it a failure with no wait at all. _reuse_appstream_storage_state
    # has always used wait_for_selector here; the mint path must match it.
    # One re-navigation of the same ?rqst=<TOKEN>&p=701 URL before giving up,
    # for the same reason the reuse path tries each saved token.
    for attempt in (1, 2):
        try:
            page.wait_for_selector("#searchMC", timeout=15_000)
            break
        except Exception:  # noqa: BLE001 — timeout or a dead frame
            url = page.url or ""
            if attempt == 1 and "rqst=" in url:
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    continue
                except Exception:  # noqa: BLE001
                    pass
            # Remember it: this token has now demonstrably failed to open a
            # console, so a later cycle that scrapes the same id off ownerville's
            # cached page can refuse it up front instead of repeating this.
            _DEAD_TOKENS.add(_tok8(tok))
            print(f"[{_stamp()}] AppStream mint FAILED — ownerville hop landed "
                  f"without a console (#searchMC absent after {attempt} "
                  f"attempt(s), at {url[:100]})", flush=True)
            return False
    after = _rqst_id(ctx)
    if not after:
        print(f"[{_stamp()}] AppStream mint FAILED — console rendered but the "
              f"context carries NO rqst token", flush=True)
        return False
    if after == before:
        _DEAD_TOKENS.add(_tok8(after))
        print(f"[{_stamp()}] AppStream mint FAILED — ownerville handed back the "
              f"SAME token {after} (it re-used our session instead of issuing "
              f"a new one)", flush=True)
        return False
    left = _ctx_rqst_minutes_left(ctx)
    print(f"[{_stamp()}] AppStream MINTED a fresh rqst via ownerville: "
          f"{before} -> {after}"
          + (f", {left:.0f}m left" if left is not None else ""), flush=True)
    return True


def _appstream_form_login(ctx, page, verbose: bool = False) -> bool:
    """Sign in to AppStream by TYPING THE CREDENTIALS, in the holder's own
    context. Returns True only when the office console actually renders.

    This is what makes a re-seed unnecessary. It is the same form
    appstream_direct_session drives (tableau_patchright, the
    _APPSTREAM_USERNAME_SELECTOR branch), run on the page the holder already
    has open rather than in a second browser — the holder is inside
    sync_playwright(), so it cannot call appstream_autorenew._form_login (that
    opens its own and a nested sync_playwright cannot start).

    THROTTLED with the mint, deliberately: this runs only on the tokenless path,
    after the hop has already failed, so it inherits that path's pacing instead
    of adding a second login loop of its own."""
    from automations.shared import creds
    from automations.shared.tableau_patchright import (
        _APPSTREAM_USERNAME_SELECTOR, _PASSWORD_SELECTOR)
    print(f"[{_stamp()}] AppStream — typing the login (no re-seed, no human).",
          flush=True)
    try:
        page.goto("https://applicantstream.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(3_000)
        # ALREADY SIGNED IN IS NOT A FAILURE — same judgment the ownerville side
        # had to learn: decide on the CONSOLE, not on whether a form appeared.
        if (page.locator(_PASSWORD_SELECTOR).count() > 0
                or page.locator(_APPSTREAM_USERNAME_SELECTOR).count() > 0):
            _drive_login_form(page, verbose,
                              username=creds.appstream_username(),
                              password=creds.appstream_password())
        page.wait_for_selector("#searchMC", timeout=20_000)
    except Exception as e:  # noqa: BLE001 — never break the holder over a login
        print(f"[{_stamp()}] AppStream typed login did NOT reach the console: "
              f"{type(e).__name__}: {str(e)[:140]}", flush=True)
        return False
    tok = _rqst_id(ctx)
    if not tok:
        # Never clobber a good export with a console that carries no token.
        print(f"[{_stamp()}] AppStream typed login rendered the console but the "
              f"context carries NO rqst token — keeping the existing export.",
              flush=True)
        return False
    left = _ctx_rqst_minutes_left(ctx)
    print(f"[{_stamp()}] AppStream ✓ TYPED LOGIN minted {tok}"
          + (f", {left:.0f}m left" if left is not None else "")
          + " — no human, no re-seed.", flush=True)
    return True


def _warm_appstream(ctx, page, verbose: bool = False) -> bool:
    """Keep the AppStream (applicantstream) console session alive in the holder's
    context so unattended reports reuse it. Reload the open console to refresh the
    ColdFusion session; if it dropped — or if it renders but carries NO rqst token
    — restore from the saved storage_state, which is also where a fleet push
    delivers a freshly minted session. True once the context holds a token.

    A RENDERING CONSOLE IS NOT A LIVE SESSION (Megan 2026-08-25). This used to
    return True the moment #searchMC was present after a reload, and never reach
    the storage_state branch. But #searchMC renders off CFID/CFTOKEN alone, and
    the holder's own 6-minute reload keeps those alive indefinitely — so once the
    rqst token aged out, the holder sat warming a console with no token, exported
    0 cookies, and printed ✓ every cycle. Worse, it could not be rescued: a
    `--appstream-push-fleet` writes a fresh token to APPSTREAM_STORAGE_STATE, and
    _reuse_appstream_storage_state re-reads that file on every call — but the
    early return meant it was never called, so the one process whose whole job is
    to hold that session was the one process a successful re-seed could not
    reach. Lucy 1 was in that state all morning on 8/25, after an 08:42 push that
    verified clean on all three machines.

    So the bar is now the TOKEN, not the render.

    AND THE RE-HOP HAPPENS BEFORE THE TOKEN DIES (2026-08-27). Raising the bar to
    the token fixed the "✓ every 6 min while exporting nothing" lie, but the
    holder still only re-hopped AFTER the token had expired — the one moment the
    hop has nothing live to trade in. See REMINT_MARGIN_MIN for the ten-hour
    outage that came of it."""
    try:
        if "applicantstream" in (page.url or ""):
            page.reload(wait_until="domcontentloaded")
            if page.locator("#searchMC").count() > 0 and _ctx_rqst_count(ctx):
                left = _ctx_rqst_minutes_left(ctx)
                if left is None or left > REMINT_MARGIN_MIN:
                    return True
                # Inside the token's last REMINT_MARGIN_MIN — MINT a successor
                # through ownerville. This used to call
                # _reuse_appstream_storage_state, which replays the token we
                # already hold and cannot issue a new one, so the holder
                # re-hopped a dying token every cycle and minted nothing. See
                # _mint_appstream_via_ownerville for the measurements.
                if verbose:
                    print(f"-> rqst token has {left:.0f}m left — minting a fresh "
                          f"one through ownerville", flush=True)
                # A THROTTLED CALL IS NOT A FAILURE — check before counting.
                #
                # This is the rule _mint_is_throttled's own docstring states
                # ("callers that escalate on failure MUST check this first"),
                # and the recovery path below obeys it. This branch did not, and
                # the arithmetic made that fire every single token cycle:
                # the holder wakes every 6 min, REMINT_MARGIN_MIN is 30, so a
                # draining token gets ~5 in-margin cycles — while
                # MINT_MIN_INTERVAL_MIN is also 30, so only the FIRST of those
                # genuinely tries. Cycles 2-5 return False because they were
                # throttled, got counted as failures, hit
                # MINT_FAILURES_BEFORE_RESTART, and asked for a restart the
                # session did not need. Measured on Lucy 2 and Lucy 3.
                _throttled = _mint_is_throttled()
                _minted = _mint_appstream_via_ownerville(ctx, page,
                                                          verbose=verbose)
                if _minted:
                    _note_mint_result(True)
                    return True
                _fails = _MINT_FAILURES["n"] if _throttled else _note_mint_result(False)
                if not _throttled and _fails >= MINT_FAILURES_BEFORE_RESTART:
                    # NAME WHAT ACTUALLY MINTS. This line used to say the restart
                    # "is the path that actually mints", and that is measurably
                    # untrue: the ownerville hop has never minted a token once
                    # (0 successes against 23k log lines on Lucy 2), and what
                    # produces every token this fleet carries is the TYPED login
                    # on the tokenless path below — "TYPED LOGIN minted …, 120m
                    # left", like clockwork every ~2h. A restart only helps
                    # because a fresh process reaches that same typed login.
                    print(f"[{_stamp()}] AppStream: the ownerville hop failed "
                          f"{_fails}x in a row. Not fatal — the typed login on "
                          f"the tokenless path is what mints, and it runs next. "
                          f"Asking for a restart as the backstop.", flush=True)
                    _MINT_FAILURES["restart_wanted"] = True
                # Ownerville couldn't mint this cycle (its own session may be
                # mid-refresh). Fall back to the old replay: it cannot produce a
                # new token, but it does re-assert the session we still hold.
                try:
                    if (_reuse_appstream_storage_state(ctx, page, verbose=verbose)
                            and _ctx_rqst_count(ctx)):
                        return True
                except Exception:
                    pass
                # Nothing minted this cycle. The old token is still valid for a
                # few more minutes, so stay warm on it and retry next cycle
                # rather than reporting a stale session.
                return True
            if verbose and page.locator("#searchMC").count() > 0:
                print("-> console renders but carries no rqst token — "
                      "re-reading storage_state", flush=True)
    except Exception:
        pass
    # THE RECOVERY PATH — we are here because the token is gone (expired, or the
    # console renders off CFID/CFTOKEN alone). Two steps, in this order:
    #
    #  1. Replay the storage_state. It is re-read from disk every call, so this
    #     is how a FLEET PUSH reaches this process: a donor machine's fresh
    #     token lands in the file and we pick it up for free. Cheap, and it is
    #     the whole reason a machine that cannot mint is still carried.
    #  2. If that leaves us with no live token, MINT one through ownerville.
    #     This step is new (2026-08-29). Without it, a holder that missed its
    #     re-mint margin could only sit and replay dead tokens — which is
    #     exactly the ten-hour outage of 2026-08-27, where twenty cycles printed
    #     "console warm but NO rqst token" and never recovered without a human.
    try:
        if (_reuse_appstream_storage_state(ctx, page, verbose=verbose)
                and _ctx_rqst_count(ctx)):
            return True
    except Exception:
        pass
    # COUNT THE OUTCOME HERE TOO (2026-09-01) — this was the hole.
    #
    # Until now this path minted and threw the result away. Only the in-margin
    # branch called _note_mint_result, so `restart_wanted` could be set ONLY
    # while a token was still alive. The moment the token actually died — the
    # emergency the restart ladder exists for — the holder minted, failed, and
    # asked for nothing, cycle after cycle.
    #
    # That is the 2026-09-01 overnight shape exactly: the rqst expired at 22:15
    # and session_holder.out.log printed "warm ✓ — 6 ownerville cookies" every
    # six minutes until 05:49, when a human logged in. Seven hours in which the
    # one recovery this file documents as working ("the restart minted what four
    # re-hop cycles could not") was never requested. Same shape as the ten-hour
    # 2026-08-27 outage named above; that fix added the mint here but not the
    # bookkeeping that turns a failing mint into a restart.
    #
    # ONE failure is enough here, not MINT_FAILURES_BEFORE_RESTART. That
    # threshold exists to keep a needless restart from disturbing a LIVE token;
    # with no live token there is nothing to protect, and this file's own
    # argument applies at full strength: "a restart cannot be worse than doing
    # nothing, which is what four hours of 8/31 actually were."
    #
    # A THROTTLED call is not a failure. _mint_appstream_via_ownerville returns
    # False both when it genuinely fails and when MINT_MIN_INTERVAL_MIN has not
    # elapsed; counting the latter would restart the holder every loop cycle on
    # nothing but the throttle, which is a relaunch loop, not a recovery.
    throttled = _mint_is_throttled()
    try:
        minted = _mint_appstream_via_ownerville(ctx, page, verbose=verbose)
    except Exception:
        minted = False
    if minted:
        _note_mint_result(True)
        return True
    # THE HOP IS NOT THE ONLY WAY IN — TYPE THE LOGIN (Megan 2026-09-02: "I
    # SHOULD NOT HAVE TO RESEED - YOU CAN TYPE IN THE LOGINS").
    #
    # The ownerville hop has never once worked. Measured on Lucy 1: 15
    # "mint FAILED" lines and ZERO "MINTED a fresh rqst" since the two messages
    # were added together on 2026-08-29 (be91e7f), every failure the same
    # "#searchMC absent". Lucy 2 is the same. So every token this fleet has ever
    # carried came from a person typing the login — and the code could have
    # typed it the whole time: creds.appstream_username()/appstream_password()
    # are right there, and appstream_autorenew._form_login records it working
    # "on Lucy 1 from a cold profile (no saved session): the form completed and
    # the office console rendered."
    #
    # Asking for a restart instead was the mistake: a restart re-runs the same
    # hop that has failed 15/15, then tells a human to --appstream-login. This
    # tries the login FIRST and keeps the restart as the last resort.
    if not throttled:
        if _appstream_form_login(ctx, page, verbose=verbose):
            _note_mint_result(True)
            return True
        _note_mint_result(False)
        print(f"[{_stamp()}] no live rqst token, the ownerville hop failed AND "
              f"the typed login failed — asking for a restart.", flush=True)
        _MINT_FAILURES["restart_wanted"] = True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Keep the ownerville session warm for unattended report runs.")
    ap.add_argument("--interval", type=float, default=8.0,
                    help="Minutes between keep-alive refreshes + exports (default 8; "
                         "keep it well under Cloudflare's clearance lifetime).")
    ap.add_argument("--seed-timeout", type=float, default=15.0,
                    help="Minutes to wait for the human to log in on first start.")
    args = ap.parse_args()

    # From here on we ARE the holder loop, so the mint throttle may persist to
    # disk and survive a launchd relaunch (see _last_mint_attempt). Nothing
    # outside this entry point reads or writes that stamp.
    _MINT_FAILURES["holder_loop"] = True
    HOLDER_PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    # A crashed Chrome leaves a stale Singleton* lock in the profile that makes
    # the next launch fail with "profile already in use" — which would defeat the
    # whole point of a launchd restart. Clear them so a watchdog/launchd relaunch
    # actually relaunches instead of dying at startup.
    for _lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (HOLDER_PROFILE_DIR / _lock).unlink()
        except OSError:
            pass
    with sync_playwright() as p:
        ctx = _launch_persistent(p, HOLDER_PROFILE_DIR, headless=False,
                                 label="session_holder", verbose=False)
        login_page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # --- Seed. THE HOLDER SEEDS ITSELF (2026-09-02). Order matters:
        #       1. the persistent profile usually auto-resumes — free, no login;
        #       2. if it doesn't, DRIVE THE FORM unattended;
        #       3. only if that fails do we fall back to asking a human.
        #     Step 2 is the one that was missing. Without it a relaunch onto a
        #     profile whose cookies are dead — the exact 2026-09-01 midnight case
        #     — lands on the prompt below and stays there until morning. ---
        try:
            login_page.goto(OWNERVILLE_V2_URL, wait_until="domcontentloaded")
        except Exception:
            pass
        seeded = "rqst=" in (login_page.url or "")
        if seeded:
            print(f"[{_stamp()}] profile resumed a live ownerville session — "
                  f"no login needed.", flush=True)
        else:
            seeded = _unattended_ownerville_login(ctx, login_page, verbose=False)
        if not seeded:
            print(f"[{_stamp()}] unattended seed failed — falling back to a human. "
                  f"SEED: log into ownerville in the window and clear any "
                  f"'verify you're human' box. (This one session covers every "
                  f"Tableau/ownerville report.) Waiting up to {args.seed_timeout:g} min…",
                  flush=True)
            waited, deadline = 0, args.seed_timeout * 60
            while waited < deadline:
                # PASSIVE detection — read the login page's URL (a property read,
                # NO navigation) so we never re-trigger Cloudflare while the human
                # is mid-login. The old cut polled by NAVIGATING a check page every
                # 15s, which kept the Turnstile alive and fought the login (Megan
                # 2026-06-18). The post-login redirect lands on v2 with an rqst.
                if "rqst=" in (login_page.url or ""):
                    seeded = True
                    break
                time.sleep(5)
                waited += 5
        if seeded:
            ovn = _export_ownerville(ctx)
            print(f"[{_stamp()}] seeded ✓ — exported {ovn} ownerville cookies. "
                  f"Keep-alive every {args.interval:g} min. Leave running. Ctrl-C to stop.",
                  flush=True)
        else:
            print(f"[{_stamp()}] not seeded within {args.seed_timeout:g} min — the "
                  f"keep-alive loop will retry the unattended login on its own "
                  f"cadence; a human login in the window also works.", flush=True)

        # --- AppStream warming (OPT-IN, RESTORED 2026-08-05): only if this machine
        #     has been seeded (`--appstream-login` wrote APPSTREAM_STORAGE_STATE).
        #     Un-seeded machines (the mini) skip this entirely — no 3rd tab, no
        #     per-cycle AppStream nav — so they stay ownerville-only as before.
        #     Seeded machines (Lucy 2, office 11580) get a warm applicantstream
        #     console so the batch/resume side rides a held session instead of a
        #     flaky fresh login. All AppStream work is try/except-contained so it
        #     can never crash the ownerville holder. ---
        # Gate on BOTH a seed file AND this being an AppStream-hold machine (see
        # APPSTREAM_HOLD_MACHINES — every Lucy holds its own again since
        # 2026-09-02, so on the fleet this is normally True everywhere). The
        # machine check still earns its place: it stops a box carrying a stale
        # .appstream_storage_state.json from before the 2026-06-30 removal from
        # silently re-activating warming.
        as_enabled = (APPSTREAM_STORAGE_STATE.exists()
                      and _this_machine() in APPSTREAM_HOLD_MACHINES)
        appstream_page = None
        if as_enabled:
            try:
                appstream_page = ctx.new_page()
                if _warm_appstream(ctx, appstream_page, verbose=False):
                    apn = _export_appstream(ctx)
                    if apn:
                        print(f"[{_stamp()}] AppStream ✓ — console restored "
                              f"({apn} cookies){_rqst_note(ctx)}.", flush=True)
                    else:
                        print(f"[{_stamp()}]  ⚠️ AppStream console warm but NO rqst "
                              f"token — nothing exported", flush=True)
                else:
                    print(f"[{_stamp()}]  ⚠️ AppStream session stale — re-seed once:  "
                          f"PYTHONPATH=. .venv/bin/python -m "
                          f"automations.shared.tableau_patchright --appstream-login",
                          flush=True)
            except Exception as e:  # noqa: BLE001 — AppStream must never crash the holder
                as_enabled = False
                print(f"[{_stamp()}] AppStream warm init skipped: "
                      f"{type(e).__name__}: {str(e)[:120]}", flush=True)
        else:
            # SAY WHICH of the two reasons it is. A non-holder runner is the
            # NORMAL, correct state since 2026-08-29 — it consumes the donor's
            # pushed session and must not keep a console of its own. Printing
            # "not seeded … seed once: --appstream-login" at it sends whoever
            # reads the log off to do a re-seed that is neither needed nor
            # harmless (a fresh login invalidates the token the whole fleet is
            # holding). Misleading log lines are most of why this took a week.
            if not APPSTREAM_STORAGE_STATE.exists():
                print(f"[{_stamp()}] AppStream not seeded on this machine — "
                      f"ownerville-only. (Seed once with --appstream-login, then "
                      f"--appstream-push-fleet.)", flush=True)
            else:
                # Seeded, but this machine is not in APPSTREAM_HOLD_MACHINES —
                # i.e. we could not place it. This used to print "this machine
                # is a CONSUMER … do NOT --appstream-login here", which since
                # every Lucy holds its own is both wrong AND the most expensive
                # kind of wrong: it talks whoever reads the log out of the one
                # command that fixes the box. Name the real condition instead.
                print(f"[{_stamp()}] AppStream: this machine "
                      f"({_this_machine()!r}) is not in APPSTREAM_HOLD_MACHINES "
                      f"{APPSTREAM_HOLD_MACHINES} — warming is OFF here. If it "
                      f"IS a runner, its .machine-profile marker is wrong; fix "
                      f"that, then --appstream-login on THIS machine. Nothing "
                      f"donates a session to it.", flush=True)

        # --- Continuous keep-alive + export loop, ONE ownerville tab. When the
        #     session is healthy we navigate that tab to keep it warm; when it
        #     goes stale we STOP navigating and passively watch the SAME tab for
        #     the human's re-login (navigating mid-login fights Cloudflare —
        #     Megan 2026-06-18). No separate poller tab. ---
        # WATCHDOG: launchd's KeepAlive only watches THIS python, not the Chrome
        # child. When Chrome died, the old loop logged "refresh error" forever
        # while the session went cold (the 2026-06-30 failure). Instead: detect a
        # dead/unrecoverable browser and EXIT non-zero so launchd relaunches the
        # whole job — a fresh Chrome on the SAME persistent profile re-warms from
        # the still-valid cookies, no human needed.
        def _passive_rqst() -> bool:
            """Read the CURRENT tab for a live rqst — URL or in-page SSO link. No
            navigation, so it never disturbs a human mid-login."""
            try:
                if re.search(r"rqst=([A-Za-z0-9_]+)", login_page.url or ""):
                    return True
                href = login_page.evaluate(
                    "() => { const a=[...document.querySelectorAll('a')]"
                    ".find(x=>/rqst=/.test(x.getAttribute('href')||'')); "
                    "return a?a.getAttribute('href'):''; }")
                return bool(re.search(r"rqst=([A-Za-z0-9_]+)", href or ""))
            except Exception:
                return False

        awaiting_login = not seeded
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 3
        # Self-heal the LOGIN-lapsed-but-browser-alive gap (2026-07-09): the old
        # watchdog only exits on a DEAD browser, so when the ownerville login went
        # stale while Chrome stayed up, the loop sat in awaiting_login logging
        # "waiting for ownerville login…" for HOURS until a human / the re-seed email
        # — even though a plain relaunch re-seeds UNATTENDED from the persistent
        # profile's still-valid cookies (proven: `lucy restart_holder` recovered the
        # session in seconds today). So if we haven't managed a good export in this
        # long, EXIT(1) → launchd relaunches → the fresh-start goto re-navigates and
        # re-seeds with no human. 25 min >> the 6–8 min export cadence (so it only
        # fires when genuinely stuck) and >> any real human login (which _passive_rqst
        # detects instantly anyway), so it won't interrupt someone mid-login.
        NO_EXPORT_MAX_MIN = 25
        last_export_ok = time.time()   # the seed export above counts as the first
        # SELF-RELOAD (Megan 2026-08-25). The holder runs for days, so it keeps
        # whatever code it started with — a `git pull` changes the files on disk
        # and nothing else. That is how BOTH of this week's holder fixes came to
        # sit inert: a965a8a widened AppStream warming to all three Lucys on 8/24
        # and 6665dff taught the holder to pick up a pushed token on 8/25, and
        # neither did anything until someone remembered `lucy restart_holder`.
        # A fix nobody notices is off is worse than no fix — it reads as "we tried
        # that and it didn't help". mini_control's poller has re-execed on a HEAD
        # change since 2026-07-05 for exactly this reason.
        #
        # It EXITS instead of os.execv-ing, which is where it differs from the
        # poller: the poller owns no browser, while this process owns a live
        # Chrome. Replacing the image out from under it would orphan or kill that
        # Chrome mid-session. Exiting is the restart path this file already uses
        # twice (dead browser, stale export) and launchd's KeepAlive relaunches
        # in ~30s onto the persistent profile, re-seeding without a human.
        head_at_start = _git_head()
        while True:
            try:
                head_now = _git_head()
                if head_at_start and head_now and head_now != head_at_start:
                    print(f"[{_stamp()}] code changed ({head_at_start[:7]} → "
                          f"{head_now[:7]}) — exiting (rc=1) so launchd relaunches "
                          f"the holder on it.", flush=True)
                    return 1
                if _MINT_FAILURES.get("restart_wanted"):
                    print(f"[{_stamp()}] exiting (rc=1) so launchd relaunches the "
                          f"holder — a fresh context is what mints a new rqst.",
                          flush=True)
                    return 1
                if not _browser_alive(ctx):
                    print(f"[{_stamp()}] browser is gone — exiting (rc=1) so launchd "
                          f"restarts the holder fresh on the persistent profile.",
                          flush=True)
                    return 1
                stale_min = (time.time() - last_export_ok) / 60
                if stale_min >= NO_EXPORT_MAX_MIN:
                    print(f"[{_stamp()}] no good ownerville export in {stale_min:.0f} min "
                          f"(login lapsed, browser still alive) — exiting (rc=1) so "
                          f"launchd relaunches + re-seeds from the persistent profile.",
                          flush=True)
                    return 1
                if awaiting_login:
                    # PASSIVE CHECK FIRST, ALWAYS. If a human IS mid-login on this
                    # tab, driving the form would navigate out from under them
                    # (the 2026-06-18 bug). A property read never does that.
                    if _passive_rqst():
                        awaiting_login = False
                        ovn = _export_ownerville(ctx)
                        last_export_ok = time.time()
                        print(f"[{_stamp()}] re-seeded ✓ — exported {ovn} ownerville "
                              f"cookies.", flush=True)
                    # NO HUMAN NEEDED (2026-09-02). This branch used to do nothing
                    # but print "waiting…" every cycle — for HOURS overnight, which
                    # is how the 4am batch found a dead session. Retry the
                    # unattended login instead; it is throttled to one attempt per
                    # LOGIN_MIN_INTERVAL_MIN, so between attempts we still just
                    # watch the tab for a human who may be logging in anyway.
                    elif _unattended_ownerville_login(ctx, login_page, verbose=False):
                        awaiting_login = False
                        last_export_ok = time.time()
                    else:
                        print(f"[{_stamp()}]  ⏳ ownerville still cold — unattended "
                              f"login will retry; a human login in the window also "
                              f"works.", flush=True)
                else:
                    # Healthy → navigate the one tab to keep the session warm.
                    if _ownerville_session_valid(login_page, verbose=False):
                        ovn = _export_ownerville(ctx)
                        last_export_ok = time.time()
                        print(f"[{_stamp()}] warm ✓ — {ovn} ownerville cookies "
                              f"(stale = kept last good export)", flush=True)
                    # STALE → LOG BACK IN, don't announce it and wait. Recovering
                    # on the FIRST stale cycle is the whole point: the fallback
                    # ladder below (25-min no-export exit → relaunch) only re-seeds
                    # from the profile's cookies, which in this state are dead.
                    elif _unattended_ownerville_login(ctx, login_page, verbose=False):
                        last_export_ok = time.time()
                    else:
                        awaiting_login = True
                        print(f"[{_stamp()}]  ⚠️ ownerville STALE and the unattended "
                              f"login did not take — will retry (kept last good "
                              f"export). A human login in the window also works.",
                              flush=True)
                    # AppStream keep-alive (seeded machines only). FULLY CONTAINED:
                    # its own try/except means a stale/challenged applicantstream
                    # console only logs a nudge — it never raises into the holder's
                    # main loop, so it can't trip the watchdog or drop ownerville.
                    if as_enabled and appstream_page is not None:
                        try:
                            if _warm_appstream(ctx, appstream_page, verbose=False):
                                apn = _export_appstream(ctx)
                                # A 0-cookie export is NOT a success. _export_appstream
                                # returns 0 only when the context carries no rqst token,
                                # and that is precisely the state reports die on — so
                                # printing ✓ here is the line that hid this for days
                                # (Lucy 1, every 6 min, all of 8/25).
                                if apn:
                                    print(f"[{_stamp()}] AppStream ✓ — {apn} cookies "
                                          f"(office-11580 console warm)"
                                          f"{_rqst_note(ctx)}", flush=True)
                                    # Donate on ANY live export, not only on a
                                    # renewal. Measured 2026-08-27 20:13: Lucy 2
                                    # renews, Lucy 1 and Lucy 3 do not (their
                                    # token id sat unchanged through the
                                    # re-hop, at 20m and 14m left). So a machine
                                    # that can never renew must be topped up by
                                    # one that can, and waiting for the donor's
                                    # own renewal event is a trigger we can't
                                    # count on. The hourly floor bounds it; a
                                    # dead machine has nothing to export and so
                                    # never donates.
                                    # TIGHTEN THIS once renewal is understood —
                                    # three healthy machines cost 6 queue rows
                                    # an hour, which is worth it only while the
                                    # holder cannot renew on its own.
                                    _push_token_to_fleet()
                                else:
                                    print(f"[{_stamp()}]  ⚠️ AppStream console warm but "
                                          f"NO rqst token — nothing exported; reports "
                                          f"will fail until a re-seed lands", flush=True)
                            else:
                                print(f"[{_stamp()}]  ⚠️ AppStream stale — re-seed:  "
                                      f"--appstream-login", flush=True)
                        except Exception as _ae:  # noqa: BLE001
                            print(f"[{_stamp()}] AppStream warm skipped: "
                                  f"{type(_ae).__name__}", flush=True)
                consecutive_errors = 0   # a clean pass clears the strike count
            except KeyboardInterrupt:
                print(f"[{_stamp()}] holder stopped.", flush=True)
                return 0
            except Exception as e:
                consecutive_errors += 1
                emsg = f"{type(e).__name__}: {str(e)[:140]}"
                dead = any(s in emsg.lower() for s in
                           ("closed", "crash", "disconnect", "target page",
                            "browser has been"))
                print(f"[{_stamp()}] refresh error #{consecutive_errors}: {emsg}",
                      flush=True)
                if dead or consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"[{_stamp()}] browser unrecoverable — exiting (rc=1) so "
                          f"launchd restarts the holder fresh.", flush=True)
                    return 1
            try:
                time.sleep(args.interval * 60)
            except KeyboardInterrupt:
                print(f"[{_stamp()}] holder stopped.", flush=True)
                return 0


if __name__ == "__main__":
    sys.exit(main())

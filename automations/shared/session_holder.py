"""Continuous session holder — keeps the ownerville login warm so SCHEDULED,
UNATTENDED report runs never hit Cloudflare's 'verify you're human'.

WHY (Megan 2026-06-17): Cloudflare globally tightened — the interactive Turnstile
now appears on a FRESH login even in a normal browser, on every machine. There is
no headless way past a forced interactive challenge, and the vendors won't expose
an API. The only thing that ALWAYS works unattended is to NEVER do a fresh login.

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

DEGRADES SAFELY: if the session goes stale it does NOT drive the form (that hits
the Turnstile). It alerts loudly, keeps the last good export, and the human logs
back in RIGHT THERE — same warm window, no new escalation.

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
# LUCY 1 + LUCY 3 ADDED 2026-08-24 (Megan). Both run AppStream reports and
# NEITHER was holding its session warm, so the token simply aged out: seeded
# ~06:00, expired 14:05 — about eight hours — and the 4am flow the next morning
# would have found it dead. Today that cost five reports on Lucy 1 (daily_focus,
# applicant_sync_morning, both recruiter_retention) plus alphalete_org_focus's
# Recruiting pull on Lucy 3, and the fix was a human clearing a Turnstile twice
# in one day. Holding it warm is what makes the seed last: the holder never
# closes the session, so it is never re-challenged.
#
# Safe to extend now because all three were freshly seeded + verified tonight
# (Lucy 1 reported reachable=8/8), so none of them is the stale-file case the
# gate was written for. A machine still needs its OWN seed file — the
# APPSTREAM_STORAGE_STATE.exists() half of the check is unchanged.
APPSTREAM_HOLD_MACHINES = ("Lucy 1", "Lucy 2", "Lucy 3")
# Back-compat for anything importing the old singular name.
APPSTREAM_HOLD_MACHINE = APPSTREAM_HOLD_MACHINES[1]

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
    _launch_persistent,
    _ownerville_session_valid,
    _reuse_appstream_storage_state,
    _sso_to_appstream,
    OWNERVILLE_STORAGE_STATE,
    APPSTREAM_STORAGE_STATE,
    OWNERVILLE_V2_URL,
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
    if ap and n_rqst:
        APPSTREAM_STORAGE_STATE.write_text(json.dumps({"cookies": ap, "origins": []}))
        return len(ap)
    return 0


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
# All three run the same rcaptain account, and one machine's session works on
# any of them — the fix was already on the fleet, and the only way to move it
# was to ask a person to clear a Turnstile that did not need clearing.
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
        sent = [m for m in APPSTREAM_HOLD_MACHINES if m != me]
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
    before = _rqst_id(ctx)
    try:
        _sso_to_appstream(page, verbose=verbose)
    except Exception as e:  # noqa: BLE001 — a mint attempt must never break the holder
        print(f"[{_stamp()}] AppStream mint FAILED (ownerville hop): "
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
        print(f"[{_stamp()}] AppStream mint FAILED — ownerville handed back the "
              f"SAME token {after} (it re-used our session instead of issuing "
              f"a new one)", flush=True)
        return False
    left = _ctx_rqst_minutes_left(ctx)
    print(f"[{_stamp()}] AppStream MINTED a fresh rqst via ownerville: "
          f"{before} -> {after}"
          + (f", {left:.0f}m left" if left is not None else ""), flush=True)
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
                if _mint_appstream_via_ownerville(ctx, page, verbose=verbose):
                    return True
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
    try:
        return _mint_appstream_via_ownerville(ctx, page, verbose=verbose)
    except Exception:
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

        # --- Seed: open ownerville for the human; poll a separate page for a
        #     live session. The holder never drives the form or navigates the
        #     human's page — a pure human login is what keeps Cloudflare quiet. ---
        try:
            login_page.goto(OWNERVILLE_V2_URL, wait_until="domcontentloaded")
        except Exception:
            pass
        print(f"[{_stamp()}] SEED: log into ownerville in the window and clear any "
              f"'verify you're human' box. (This one session covers every "
              f"Tableau/ownerville report.) Waiting up to {args.seed_timeout:g} min…",
              flush=True)
        waited, deadline = 0, args.seed_timeout * 60
        seeded = False
        while waited < deadline:
            # PASSIVE detection — read the login page's URL (a property read, NO
            # navigation) so we never re-trigger Cloudflare while the human is
            # mid-login. The old cut polled by NAVIGATING a check page every 15s,
            # which kept the Turnstile alive and fought the login (Megan
            # 2026-06-18). The post-login redirect lands on v2 with an rqst token.
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
            print(f"[{_stamp()}] not seeded within {args.seed_timeout:g} min — will keep "
                  f"checking; finish logging in in the window.", flush=True)

        # --- AppStream warming (OPT-IN, RESTORED 2026-08-05): only if this machine
        #     has been seeded (`--appstream-login` wrote APPSTREAM_STORAGE_STATE).
        #     Un-seeded machines (the mini) skip this entirely — no 3rd tab, no
        #     per-cycle AppStream nav — so they stay ownerville-only as before.
        #     Seeded machines (Lucy 2, office 11580) get a warm applicantstream
        #     console so the batch/resume side rides a held session instead of a
        #     flaky fresh login. All AppStream work is try/except-contained so it
        #     can never crash the ownerville holder. ---
        # Gate on BOTH a seed file AND this being an AppStream-hold machine
        # (see APPSTREAM_HOLD_MACHINES — all three Lucys since 2026-08-24). The
        # machine check stops a box carrying a stale .appstream_storage_state.json
        # from before the 2026-06-30 removal silently re-activating warming.
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
            print(f"[{_stamp()}] AppStream not seeded on this machine — ownerville-only. "
                  f"(To hold office-11580 AppStream warm here, seed once:  "
                  f"--appstream-login)", flush=True)

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
                    # Human is (re)logging in on the tab — DON'T navigate it.
                    if _passive_rqst():
                        awaiting_login = False
                        ovn = _export_ownerville(ctx)
                        last_export_ok = time.time()
                        print(f"[{_stamp()}] re-seeded ✓ — exported {ovn} ownerville "
                              f"cookies.", flush=True)
                    else:
                        print(f"[{_stamp()}]  ⏳ waiting for ownerville login in the "
                              f"window…", flush=True)
                else:
                    # Healthy → navigate the one tab to keep the session warm.
                    if _ownerville_session_valid(login_page, verbose=False):
                        ovn = _export_ownerville(ctx)
                        last_export_ok = time.time()
                        print(f"[{_stamp()}] warm ✓ — {ovn} ownerville cookies "
                              f"(stale = kept last good export)", flush=True)
                    else:
                        awaiting_login = True
                        print(f"[{_stamp()}]  ⚠️ ownerville STALE — log back in in the "
                              f"window (kept last good export).", flush=True)
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

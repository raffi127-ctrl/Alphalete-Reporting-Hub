"""AppStream session watch — predict the recruiting-console session dying and
recover from it, so the 4am unattended reports (daily_focus, recruiter_retention)
never surprise-fail at 4am.

WHY THIS EXISTS
The recruiting console is authenticated by an `rqst` SSO token (+ ColdFusion
CFID/CFTOKEN). A freshly-minted rqst lives ~2 HOURS — measured three times now
(2026-08-24: login 20:54 → expiry 22:54, and 21:09 → 23:09; plus a captured
session on 8/24 18:53 → 20:53). The 24h figure belongs to CFID/CFTOKEN riding
alongside it. So an EXPIRED stored token is the normal state between runs and is
NOT by itself a verdict on health.

HOW THE BATCH ACTUALLY SURVIVES THE NIGHT — the fleet renews it, unattended,
with no human login. Get the MECHANISM right, because an earlier version of this
comment had it wrong and the wrong version is very persuasive:

  • the holder's 6-minute reload keeps the ColdFusion session (CFID/CFTOKEN,
    24h) from idle-timing-out, indefinitely;
  • the storage_state re-hop (`?rqst=<TOKEN>&p=701`) RESTORES a session but does
    NOT issue a new token. Measured with token-identity logging on 2026-08-27:
    Lucy 1 and Lucy 3 held the same token id across every cycle inside the
    re-mint margin and then expired anyway. Do not build on the re-hop;
  • what actually mints is a machine that USES the console (Lucy 2 —
    applicant_push / resume_pushing). When its token renews it pushes the new
    one to every hold machine (`_push_token_to_fleet` →
    `set_appstream_state`, by=holder-renewal). That is what the other runners
    are living on.

Observed on the control queue overnight into 2026-08-29: a `set_appstream_state
… session VERIFIED here — the AppStream reports can run` landing every ~6 min
without a break, straight through the 4am batch (04:08, 04:10, 05:07, 05:13).
Yesterday's batch finished 45/47; the two failures (mobrium_list, sci_campaigns)
are not AppStream reports.

THE ONE CASE THAT STILL NEEDS A HUMAN: only the console-using machine renews, so
if it stops, every machine goes dark together on a shared expiry. That is a real
outage, it is what the alerting below must stay loud for, and it is why the
quieting in this module is scoped to forecasts rather than to failures.
[[reference_appstream_turnstile]]

WHAT THIS WATCH MUST NOT DO — two false alarms, both now fixed.

1. THE DEAD LOGIN ROUTE (fixed 2026-08-27, `e6bba32`). The probe drove the
   rcaptain FORM login (force_form_login=True) and cried "the self-heal is
   BROKEN" when it failed. But `d793ea3` had disabled that form for scheduled
   runs hours before, so no report had taken it since — the watch was failing a
   route nothing uses. `selfheal_ok()` now drives the REUSE path the reports
   drive.

2. THE IMPOSSIBLE PREDICTION (fixed 2026-08-29, this change). Health was
   "does the stored rqst outlast the next 4am batch + 90 min?". The rqst TTL is
   a fixed ~2 HOURS. No token can ever satisfy that test — a freshly minted,
   perfectly healthy one least of all. Measured on Lucy 1 at 05:17 on 8/29,
   mid-batch, with the holder re-exporting a VERIFIED session every six
   minutes: "AppStream rqst token valid 0.7h more (until Aug 29 6:01AM)" —
   against a required Aug 30 05:30. So `healthy` was structurally False every
   hour of every day, every ping window escalated to the live probe, and any
   single flake in that probe (stray Chrome, a busy profile, a slow console)
   became a page for a session that was fine. That is the wolf Megan kept
   hearing, and it could not stop on its own.

   Health is now judged in the PRESENT TENSE — is the token valid *right now*,
   and is the holder still exporting it? — because the holder re-mints on its
   own and a lapsed stored token between runs is the normal, healthy state, not
   a forecast of failure. Prediction is what cried wolf; it is gone from the
   paging path.

THE BAR FOR WAKING SOMEONE. A page now requires evidence that a report cannot
get a session — never a forecast that it might not:
  • an AppStream-backed report ACTUALLY failed today with a session/auth
    reason (read from the orchestrator's own day_state), or
  • the live probe failed on the reports' own path, twice, minutes apart.

WHAT EVE DOES (everything but the click):
  • OBSERVE  — read the rqst expiry from the stored session + how recently the
               holder re-exported it (cheap, no network, no Cloudflare risk).
  • PING     — only on the evidence above, ONCE per window per day, with the
               exact re-seed command.
  • RECOVER  — the moment the session is healthy again AND it's the morning
               window (a 4am failure), auto-rerun the AppStream reports via
               mini_control so they fill with no further human step.

Run on the mini (where the live session + storage_state live). Called every few
minutes from the session-holder loop; also runnable standalone:
    python -m automations.shared.appstream_watch --once
    python -m automations.shared.appstream_watch --once --dry-run   # no Slack / no enqueue
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path

from automations.shared.tableau_patchright import (
    APPSTREAM_STORAGE_STATE, OWNERVILLE_STORAGE_STATE,
)

WATCH_STATE = Path(__file__).resolve().parents[2] / "output" / "appstream_watch_state.json"

# Slack DM recipients for the re-seed ping — BOTH get it so whoever's free does
# the 30-sec re-seed if the other can't (Megan 2026-06-26). Megan Hidalgo +
# Evelyn ("Eve") Sobrino. Tunable: add/remove user ids (or a channel id).
# Plus #claudecorrections-and-requests (Eve 2026-08-24): a DM is easy to miss
# and only reaches two people. The re-seed needs SOMEONE at the mini, not a
# specific someone, so the ping belongs where the rest of the day's failures
# already land. chat_postMessage takes a channel id in the same slot as a
# user id, so this needs no other change.
# CHANNEL ONLY (Megan 2026-08-28: "it also shouldn't be DMing Eve and I").
# This used to DM Megan + Eve as well, on the 2026-06-26 reasoning that a
# re-seed needs SOMEBODY and two people beats one. That reasoning stopped
# holding the moment #claudecorrections-and-requests became where the day's
# failures land: the DM adds no reader, it just puts the same alert in three
# places, and this particular alert has fired repeatedly while the batch was
# being carried — so the cost of a false one is paid three times over, by name,
# out of hours. The channel is the standing home for this
# ([[project_corrections_slack_channel]]); a re-seed needs someone at a
# keyboard, not a specific someone.
ALERT_SLACK_TARGETS = ["C0BK5PRG259"]

# (There used to be an APPSTREAM_REPORTS_FALLBACK = ["daily_focus"] here, used
# when the day-state or registry couldn't be read. Removed 2026-08-29: guessing
# a report to re-run is the one thing this path must not do — daily_focus posts,
# and a blind rerun off an unreadable state is how you double-post. The recovery
# list now falls back to nothing and lets the alert carry the news.)

# NOT a health test any more — see false alarm #2 in the module docstring. The
# rqst TTL is ~2h, so "outlasts the next 4am batch by 90 min" is unsatisfiable by
# construction and marked every healthy session stale. Kept only so the status
# line can SAY what the stored token would and wouldn't cover; nothing pages on
# it. session_check.py reads it for the same display-only purpose.
SURVIVAL_BUFFER_MIN = 90

# The live probe opens a real Chrome, so it inherits every transient this repo
# already knows about: a stray human Chrome, a profile another report is holding,
# a console that renders slowly. One flake used to equal one page. Ask twice,
# minutes apart, and only believe a failure both times agree on — the holder
# re-exports every ~6 min, so a genuine outage is still caught on the next pass
# while a hiccup costs nobody their evening.
PROBE_ATTEMPTS = 2
PROBE_RETRY_SLEEP_S = 45
# A recovery during this window means a 4am failure we should re-run; a recovery
# outside it (e.g. an evening proactive re-seed) needs no rerun.
# Ran to noon until 2026-08-25. Since the login form went human-gated the re-seed
# happens whenever a person gets to it, from wherever they are — Eve re-seeds from
# Argentina, and a 10am start there is already 7am CT with no margin left. A
# re-seed at 10am CT used to recover nothing and say nothing. Widened to 3pm: an
# evening proactive re-seed is still outside it, the day-state filter keeps a
# finished report from re-running, and the once-a-day guard still holds.
MORNING_WINDOW = (4, 15)   # [4am, 3pm)

# Send the proactive "re-seed tonight" ping in the EVENING only — a predictable
# 6pm heads-up you can act on before bed beats a random-time one (Megan
# 2026-06-26: "slack Eve at 6pm if she needs the reseed to happen"). The watch
# still runs every 6 min, but it HOLDS the ping until this hour.
PING_HOUR = 18   # 6pm (mini local time)
# A DAYTIME window, so a session that dies during business hours is not sat on
# until 6pm (Megan 2026-08-27). Lucy 1's holder lost its token at 08:41 and
# printed "console warm but NO rqst token" to a log nobody reads for TEN HOURS;
# the first thing anyone saw was the 6:41pm ping — after the working day, from
# people whose whole job this ping is asking them to do. The probe still gates
# it, so this only fires when a report genuinely could not open the console
# right now; on a normal day the stored token is expired at 8am too and the
# probe passes, exactly as it does at 6pm.
DAY_PING_HOUR = 8    # 8am (mini local time) — after the 4am batch, in work hours
# A SECOND, last-chance window ~1h before the 4am batch: catches a session that
# went stale AFTER the 6pm ping (or was never re-seeded), so it surfaces as an
# early-morning heads-up instead of a 7am surprise-failure.
PRE_BATCH_PING_HOUR = 3   # 3am (mini local time)
# The holder re-exports a live session every ~6 min and ONLY when it validates.
# So a stale export FILE means the holder is down OR the session no longer
# validates — a real-health signal the rqst-expiry timestamp alone can miss
# (a future-dated token whose holder died still reads "valid").
STALE_EXPORT_MIN = 25


def _now() -> dt.datetime:
    return dt.datetime.now()


def _export_age_min(state_path) -> float | None:
    """Minutes since the holder last re-exported this session file. The holder
    writes it only when the session validates live, so a stale file means the
    holder is down or the session is dead — caught even when the stored rqst
    timestamp still reads 'valid'. None if the file is absent."""
    try:
        return (_now().timestamp() - Path(state_path).stat().st_mtime) / 60.0
    except OSError:
        return None


# How long the fleet handoff may go quiet before a consumer is on its own.
# Lucy 2 mints a fresh AppStream rqst and hands it to every consumer roughly
# HOURLY (2026-08-31: 01:11, 02:12, 03:09, 04:11, 05:07, 06:08), while the token
# itself only lives ~2h. A consumer's copy is therefore a few minutes from
# expiry somewhere in every trough — that is the designed rhythm, not a fault.
# 2026-08-31 03:01 paged Megan about a token that died at 03:05 and was replaced
# at 03:09, eight minutes later, with the holder never having missed a beat.
# 100m is one handoff interval plus room for a slow one.
FLEET_HANDOFF_GRACE_MIN = 100.0


def _donated_token_marker():
    return APPSTREAM_STORAGE_STATE.with_name(".appstream_donated_token")


def _donation_age_min() -> float | None:
    """Minutes since a fleet handoff last installed a session on this machine.

    mini_control writes '.appstream_donated_token' beside the state file every
    time the holder's push lands, so its mtime is this machine's OWN record of
    when the fleet last fed it — no cross-machine read, nothing to go stale."""
    return _export_age_min(_donated_token_marker())


def fleet_is_feeding_us() -> tuple[bool, str]:
    """Always (False, why). NOTHING FEEDS THIS MACHINE — it mints its own.

    This was a page-SUPPRESSION rule, and it earned its place: on 2026-08-31 the
    watch woke Megan at 03:01 over a token with 0.1h left on a machine that was
    being handed a fresh one hourly, and the re-seed it asked for would have
    invalidated the token the whole fleet was holding. While one machine minted
    and the rest consumed, "my copy is nearly expired" genuinely was not an
    outage — it was a copy that is old on purpose.

    THE ARRANGEMENT IT SUPPRESSED FOR IS GONE (Megan 2026-09-02: "one machine
    CANNOT depend on another, we don't want 1 taking them all down"). Every Lucy
    signs in as its own account and mints its own token. There is no donor, no
    trough, and nothing that is old on purpose.

    So the suppression has to go with it — and this is the direction that
    matters. A suppression whose premise has quietly expired does not fail
    loudly; it swallows the page on the morning the session is genuinely dead,
    which is the same shape as the 4am batch dying on a token that had just been
    "renewed". A dead session now always pages, on the machine it is dead on,
    because that is the only machine that can fix it.

    Kept as a stub rather than deleted so the caller keeps its explanatory
    string — the log line says WHY it is not suppressing."""
    return False, ("this machine mints its own AppStream session — nothing "
                   "donates one to it, so a dead session here is real and "
                   "actionable HERE")


def _this_machine() -> str:
    """This runner's name, the same way mini_control resolves it."""
    try:
        from automations.shared import hub_identity
        return hub_identity.machine_name()
    except Exception:                       # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Probe — read when the session dies. Cheap, no network.
# ---------------------------------------------------------------------------

def session_status(state_path=None, what: str = "AppStream") -> dict:
    """Report when a stored session dies. The rqst SSO token's `expires` is the
    binding constraint for whether the console will still authenticate;
    CFID/CFTOKEN ride alongside it. Works for BOTH the AppStream recruiting
    session and the ownerville/Tableau session (same cookie shape) — pass the
    state_path + a label.

    Returns {ok, rqst_expiry: datetime|None, hours_left: float|None, what, reason}."""
    state_path = state_path or APPSTREAM_STORAGE_STATE
    if not state_path.exists():
        return {"ok": False, "rqst_expiry": None, "hours_left": None, "what": what,
                "reason": f"no stored {what} session — never seeded"}
    try:
        cookies = json.loads(state_path.read_text()).get("cookies", [])
    except Exception as e:
        return {"ok": False, "rqst_expiry": None, "hours_left": None, "what": what,
                "reason": f"{what} session file unreadable: {str(e)[:80]}"}
    now = _now().timestamp()
    rqst_exps = [c.get("expires") for c in cookies
                 if (c.get("name") or "").lower().startswith("rqst")
                 and isinstance(c.get("expires"), (int, float)) and c["expires"] > 0]
    if not rqst_exps:
        return {"ok": False, "rqst_expiry": None, "hours_left": None, "what": what,
                "reason": f"{what}: no rqst SSO token in the session (degraded / SSO-only)"}
    latest = max(rqst_exps)
    hours = (latest - now) / 3600
    exp = dt.datetime.fromtimestamp(latest)
    # Built by hand: %-d / %-I are glibc/BSD-only and raise ValueError on
    # Windows, so EVERY session_status() call from a Windows box crashed instead
    # of answering — including the ones you make while diagnosing a dead source
    # (Eve 2026-08-17). Cross-platform rule, same as opt_frontier._week_label.
    when = "{} {} {}:{:02d}{}".format(
        exp.strftime("%b"), exp.day, (exp.hour % 12) or 12, exp.minute,
        "AM" if exp.hour < 12 else "PM")
    if latest <= now:
        return {"ok": False, "rqst_expiry": exp, "hours_left": hours, "what": what,
                "reason": f"{what} rqst token EXPIRED {-hours:.1f}h ago (at {when})"}
    return {"ok": True, "rqst_expiry": exp, "hours_left": hours, "what": what,
            "reason": f"{what} rqst token valid {hours:.1f}h more (until {when})"}


def _next_4am(now: dt.datetime | None = None) -> dt.datetime:
    now = now or _now()
    four = now.replace(hour=4, minute=0, second=0, microsecond=0)
    return four if now < four else four + dt.timedelta(days=1)


def _reseed_cmd() -> str:
    # Since AppStream's 2026-08-20 release the login form has an interactive
    # human-check, so the re-seed happens on WHATEVER machine a human is at
    # (laptop is fine) — the second command then pushes the fresh session to
    # every runner (Lucy 1 primary + Lucy 2 alternate) via the control queue.
    #
    # Written for the machine the watch is running on: '.venv/bin/python' is not
    # a path on Windows, and "on any machine you're at" only holds if the lines
    # can be pasted where the reader actually is (Eve 2026-08-24). Same
    # cross-platform rule as the hand-built `when` string in session_status().
    mod = "automations.shared.tableau_patchright"
    if os.name == "nt":
        py = r".\.venv\Scripts\python.exe"
        pre = "$env:PYTHONPATH='.'; $env:PYTHONUTF8='1'; "
    else:
        py, pre = ".venv/bin/python", "PYTHONPATH=. "
    return ("# run from your repo folder, on any machine you're at:\n"
            f"{pre}{py} -m {mod} --appstream-login\n"
            f"{pre}{py} -m {mod} --appstream-push-fleet")


def selfheal_ok(verbose: bool = False) -> tuple[bool, str]:
    """Can a scheduled report open the AppStream console RIGHT NOW? Drives the
    exact path the 4am reports drive — reuse the stored session, no login form.

    WHY REUSE-ONLY (Megan 2026-08-27: "this is already corrected — I haven't
    touched it all day"). This used to drive the rcaptain FORM login with
    force_form_login=True, and reported "the self-heal is BROKEN" when that
    failed. But `d793ea3` had disabled the form for scheduled runs hours
    earlier (allow_form_login defaults False), so no report has taken that path
    since — the probe was failing a route nothing uses and waking people for it,
    every night, while the 4am batch ran clean.

    What actually carries the batch is the fleet: the console-using machine
    renews the ~2h rqst and pushes it to every hold machine every few minutes
    (see the module docstring — NOT the storage_state re-hop, which restores a
    session without issuing a token). So the honest question is not "can we log
    in" — it is "does the session the reports will use authenticate", which is
    what this now asks.

    'profile busy' counts as healthy — another AppStream report is holding a
    live session right now, which is proof the path works."""
    from automations.shared.tableau_patchright import (
        AppStreamBusy, appstream_direct_session)
    try:
        # allow_form_login/force_form_login left at their defaults (False) ON
        # PURPOSE: this must fail exactly where a scheduled report would fail.
        with appstream_direct_session(headless=False, verbose=verbose,
                                      yield_if_busy=True) as page:
            if page.locator("#searchMC").count() > 0:
                return True, "stored session opened the console (same path as the reports)"
            return False, "stored session did not render #searchMC"
    except AppStreamBusy:
        return True, "profile busy — another AppStream report holds a live session"
    except Exception as e:                                      # noqa: BLE001
        return False, "stored session is dead: {}: {}".format(
            type(e).__name__, str(e)[:110])


def probe_appstream_healthy(attempts: int = PROBE_ATTEMPTS,
                            sleep_s: float = PROBE_RETRY_SLEEP_S) -> tuple[bool, str]:
    """selfheal_ok() with a retry, so one flaky Chrome launch is not a page.

    A single probe failure is not evidence of an outage: the probe drives a real
    browser against a profile the 4am batch also uses, and 'profile in use',
    a stray human Chrome and a slow-rendering console all surface here as an
    exception. A genuinely dead session fails every time, so a second ask costs
    nothing and removes the biggest remaining source of false pages."""
    why = "probe never ran"
    for i in range(max(1, attempts)):
        ok, why = selfheal_ok()
        if ok:
            return True, (why if i == 0 else f"{why} (recovered on attempt {i + 1})")
        if i < attempts - 1:
            print(f"[appstream_watch] probe attempt {i + 1}/{attempts} failed "
                  f"({why}) — retrying in {sleep_s:.0f}s")
            time.sleep(sleep_s)
    return False, f"{why} (failed {attempts}x)"


# A report's own failure reason, when what failed was GETTING A SESSION rather
# than anything about the report. These are the phrases the AppStream path
# actually emits (tableau_patchright's re-seed message, the direct-session
# guard, the console check) — kept narrow on purpose: a broad match here would
# turn an ordinary report bug into a re-seed page, which is the same cry-wolf
# in a new costume.
_SESSION_FAIL_MARKERS = (
    "re-seed", "reseed", "no rqst", "rqst token", "no stored", "storage_state",
    "session is dead", "session is stale", "session stale", "not authenticated",
    "appstream session", "#searchmc", "sign in", "signed out", "login page",
)


def appstream_session_failures(now: dt.datetime | None = None) -> list[tuple[str, str]]:
    """(report_id, reason) for AppStream-backed reports that ACTUALLY failed
    today because they could not get a session. The ground truth this watch was
    missing: it used to page on a forecast while never once reading whether a
    report had in fact failed.

    BLOCKED_SESSION counts on its own — the status means exactly this. FAILED
    counts only when its reason reads like an auth/session failure, so a report
    that died of its own bug does not ask anyone for a re-seed.

    Returns [] on any error: this is an ADDITIONAL alarm, and a broken read of
    it must never be the thing that wakes someone."""
    try:
        from automations.day_orchestrator import registry
        from automations.day_orchestrator import state as day_state
        day = (now or _now()).date()
        cfg = registry.load_config()
        appstream_ids = {r.report_id for r in registry.scheduled_today(cfg, day)
                         if r.source_type == "appstream"}
        if not appstream_ids:
            return []
        state_file = day_state.STATE_DIR / f"{day.isoformat()}.json"
        if not state_file.exists():
            return []
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        out = []
        for rid, rs in (raw.get("reports") or {}).items():
            if rid not in appstream_ids:
                continue
            status = rs.get("status")
            reason = (rs.get("last_reason") or "").strip()
            if status == day_state.BLOCKED_SESSION:
                out.append((rid, reason or "BLOCKED_SESSION"))
            elif status == day_state.FAILED and any(
                    m in reason.lower() for m in _SESSION_FAIL_MARKERS):
                out.append((rid, reason))
        return sorted(out)
    except Exception as e:                                      # noqa: BLE001
        print(f"[appstream_watch] (couldn't read today's report failures: "
              f"{type(e).__name__}: {str(e)[:100]})")
        return []


def _ov_reseed_cmd() -> str:
    # Restarting the session-holder re-seeds ownerville: it opens the login and
    # waits for a human to clear the 'verify you're human' box (one session
    # covers Tableau + AppStream-via-SSO).
    return "launchctl kickstart -k gui/$(id -u)/com.alphalete.session-holder"


# ---------------------------------------------------------------------------
# State (throttle + recovery detection) + side effects
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    try:
        return json.loads(WATCH_STATE.read_text())
    except Exception:
        return {}


def _save_state(s: dict) -> None:
    try:
        WATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
        WATCH_STATE.write_text(json.dumps(s, indent=2))
    except Exception:
        pass


def _alert(text: str, dry_run: bool) -> None:
    print(f"[appstream_watch] ALERT → {', '.join(ALERT_SLACK_TARGETS)}\n{text}")
    if dry_run:
        return
    try:
        from automations.shared.slack_metrics_post import _client
        client = _client()
    except Exception as e:
        print(f"[appstream_watch] (Slack client init failed: {type(e).__name__}: {str(e)[:100]})")
        return
    for target in ALERT_SLACK_TARGETS:   # one failure mustn't block the other recipient
        try:
            client.chat_postMessage(channel=target, text=text)
        except Exception as e:
            print(f"[appstream_watch] (Slack alert to {target} failed: "
                  f"{type(e).__name__}: {str(e)[:100]})")


def _appstream_reports_to_rerun(now: dt.datetime | None = None) -> list[tuple[str, str]]:
    """(report_id, machine) for the AppStream-backed reports a session failure
    actually COST us today — what a re-seed should pick up — in run order.

    This was a hardcoded ["daily_focus"], so a re-seed landing after 4am
    recovered exactly one of the AppStream reports and left the rest to be
    re-queued by hand, every morning, since the 2026-08-20 release human-gated
    the login form (Eve 2026-08-25: applicant_sync_morning +
    recruiter_retention_daily, every day). Derived now from the same two files
    the batch itself uses, which also settles the ways a list like this goes
    wrong:

      • ONLY reports that reached a FAILED / BLOCKED_SESSION end-state. It used
        to be "everything that isn't DONE", which quietly includes PENDING —
        reports the orchestrator has not reached yet and still owns. On
        2026-08-29 a recovery fired mid-batch at 05:29 and re-queued
        other_office_knocks, which the day-state listed as `pending -
        daily_metrics`: waiting on a dependency. The rerun path runs a report
        DIRECTLY and does not check deps (mini_control._action_rerun), so that
        is a dependency-violating early run of a report that posts to Slack —
        and [[feedback_never_post_blank]] is exactly the cost. A report the
        batch has not attempted is not something a re-seed needs to recover.
      • It must not re-run a report that already reached DONE. Several of these
        post to Slack, and the rqst token only lives ~2h — a wasted run can cost
        a real one.
      • It must not go stale the way the push-fleet machine list did, which
        quietly covered two of three runners for three days (see
        tableau_patchright --appstream-push-fleet). A new AppStream report is
        covered here the day it lands on the scheduler.
    """
    try:
        from automations.day_orchestrator import registry
        from automations.day_orchestrator import state as day_state
        day = (now or _now()).date()
        cfg = registry.load_config()
        scheduled = {r.report_id: r for r in registry.scheduled_today(cfg, day)
                     if r.source_type == "appstream"}
        if not scheduled:
            return []
        state_file = day_state.STATE_DIR / f"{day.isoformat()}.json"
        if not state_file.exists():
            # No day-state means the batch has not recorded anything, so nothing
            # has failed yet — there is nothing for a re-seed to recover.
            return []
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        failed_states = {day_state.FAILED, day_state.BLOCKED_SESSION}
        hit = [scheduled[rid] for rid, rs in (raw.get("reports") or {}).items()
               if rid in scheduled and rs.get("status") in failed_states]
        hit.sort(key=lambda r: (r.order if r.order is not None else 10_000,
                                r.report_id))
        return [(r.report_id, r.machine) for r in hit]
    except Exception as e:
        # Fall back to NOTHING, not to a report. A recovery rerun is a
        # convenience; firing one on a guess can double-post. The alert still
        # goes out either way, so a human still learns about it.
        print(f"[appstream_watch] (couldn't derive the rerun list, "
              f"recovering nothing automatically: "
              f"{type(e).__name__}: {str(e)[:100]})")
        return []


def _registry_default_machine() -> str:
    """'Lucy 1' unless the registry says otherwise — kept out of the import path
    above so a broken registry import can still name a machine."""
    try:
        from automations.day_orchestrator.registry import DEFAULT_MACHINE
        return DEFAULT_MACHINE
    except Exception:
        return "Lucy 1"


def _enqueue_rerun(report_id: str, dry_run: bool,
                   machine: str | None = None) -> None:
    print(f"[appstream_watch] enqueue rerun {report_id}"
          + (f" -> {machine}" if machine else ""))
    if dry_run:
        return
    try:
        from automations.day_orchestrator import mini_control
        # auto=True: a watchdog re-running a report is not a person working its
        # alert thread, so this rerun must not leave a :pending: on it.
        # machine: these reports are spread across the runners (alphalete_org_focus
        # is Lucy 3), and the re-seed pushes the session to all of them — so each
        # rerun has to land on the tab whose poller actually owns the report.
        kw = {"by": "appstream_watch", "auto": True}
        if machine and machine != _registry_default_machine():
            kw["machine"] = machine
        mini_control.enqueue("rerun", report_id, **kw)
    except Exception as e:
        print(f"[appstream_watch] (enqueue failed: {type(e).__name__}: {str(e)[:100]})")


def _reseed_alert_text(stale, when: str) -> str:
    """Build the re-seed DM. `stale` is [(status, reseed_cmd), ...]; `when` frames
    the urgency (evening 'tonight' vs the 3am '~1h before the batch')."""
    # DO NOT CLAIM AN AUTOMATED RECOVERY THAT NEVER HAPPENED, and do not send
    # anyone to clear a Cloudflare check (2026-09-02).
    #
    # This used to say "The automated login already tried and could NOT recover
    # this one" for BOTH sessions. For ownerville that was simply false: it
    # reaches this list on the stored file's timestamp alone — no probe, no
    # login attempt — so the sentence invented a failed recovery. And "clear the
    # check once" is left over from the twelve days we believed the Cloudflare
    # box needed a person; it clears itself given ~30s before submit.
    #
    # Both halves point away from the real cause. On 2026-09-02 the actual fault
    # was a DISABLED session-holder LaunchAgent on Lucy 1 — the ownerville token
    # had 48h left and nothing needed re-seeding at all. An alert that names a
    # remedy it has not tried is worse than one that says less.
    lines = [f"⚠️ *Session holder needs attention* {when}."]
    for stt, reseed in stale:
        lines.append(f"\n• *{stt['what']}*: {stt['reason']}\n"
                     f"  Nobody needs to clear a Cloudflare check — both logins "
                     f"sign themselves in. Check the holder is actually RUNNING "
                     f"first (a disabled LaunchAgent looks exactly like this, "
                     f"and `kickstart` will say \"could not find service\"):\n"
                     f"```launchctl print-disabled gui/$(id -u) | grep alphalete\n"
                     f"launchctl enable gui/$(id -u)/com.alphalete.session-holder\n"
                     f"launchctl kickstart -k gui/$(id -u)/com.alphalete.session-holder```\n"
                     f"  Then confirm BOTH logins on that machine:\n"
                     f"```{reseed}```")
    lines.append("\nThe moment it's healthy I'll auto-run what I can — "
                 "you don't have to touch anything else.")
    return "\n".join(lines)


def _real_failure_text(failures, reseed: str) -> str:
    """The page for a session failure that has ALREADY cost a report. Says which
    reports, and what they said — so the reader can tell in one line that this
    is the real thing and not the nightly countdown this alert used to send."""
    n = len(failures)
    lines = [f"⚠️ *AppStream session failure* — {n} report"
             f"{'' if n == 1 else 's'} could not open the recruiting console "
             f"today and did NOT fill:"]
    for rid, reason in failures:
        lines.append(f"\n• *{rid}* — {reason[:200]}")
    # Same correction as _reseed_alert_text: no "clear the check once". The
    # login is unattended; if it failed, the cause is the credential, the
    # profile, or a holder that is not running — not a missing human.
    lines.append(f"\nFix on THAT machine (no check to clear — the login is "
                 f"unattended):\n```{reseed}```")
    lines.append("The moment it's healthy I'll auto-re-run these — "
                 "you don't have to touch anything else.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The watch — one evaluation
# ---------------------------------------------------------------------------

def watch(dry_run: bool = False, probe: bool = True) -> dict:
    """One evaluation across BOTH sessions (AppStream recruiting console +
    ownerville/Tableau). Observe / ping / recover. Safe to call every few minutes
    (throttled to one ping per window + one rerun-batch per day). Never raises.

    AppStream can only page on EVIDENCE: a report that actually failed on a
    session today, or a live probe that failed twice on the reports' own path.
    The stored token's timestamp alone never pages it — that was the cry-wolf.

    probe=False drops both evidence sources, leaving only the stored timestamp,
    which by the rule above means AppStream cannot page at all. Debugging only."""
    state = _load_state()
    now = _now()
    today = now.date().isoformat()
    threshold = _next_4am(now) + dt.timedelta(minutes=SURVIVAL_BUFFER_MIN)

    # (key, status, re-seed cmd, reports to auto-rerun on morning recovery).
    # Ownerville recovery has no auto-rerun list — the 4am failure email already
    # lists those reports with their `lucy rerun` lines, so we don't double-fire.
    sessions = [
        ("appstream",  session_status(APPSTREAM_STORAGE_STATE, "AppStream"),
         _reseed_cmd(),    _appstream_reports_to_rerun(now)),
        ("ownerville", session_status(OWNERVILLE_STORAGE_STATE, "Ownerville"),
         _ov_reseed_cmd(), []),
    ]

    # Which ping window (if any) is open right now — computed BEFORE the loop
    # because the AppStream self-heal probe is expensive and only worth running
    # when we are actually about to wake someone.
    evening_due = (now.hour >= PING_HOUR
                   and state.get("alerted_evening_for") != today)
    prebatch_due = (PRE_BATCH_PING_HOUR <= now.hour < MORNING_WINDOW[0]
                    and state.get("alerted_prebatch_for") != today)
    daytime_due = (DAY_PING_HOUR <= now.hour < PING_HOUR
                   and state.get("alerted_daytime_for") != today)
    ping_due = evening_due or prebatch_due or daytime_due

    # [(status, reseed_cmd), ...] for sessions that are UNHEALTHY RIGHT NOW —
    # not "won't survive the batch", which is what this used to mean and what
    # made it fire on healthy sessions. Ownerville was quietly caught by the same
    # forecast: its 24h token is refreshed around 05:11 each morning, i.e.
    # perpetually just under a 4am+90min threshold of 05:30, so it too was stale
    # every single evening. Both are judged in the present tense now.
    stale = []
    # The subset of `stale` a LIVE probe just failed. Only these earn the daytime
    # ping: ownerville is judged by its stored expiry (no probe), and an unprobed
    # 8am ping about it every morning would be a brand-new false alarm.
    probed_stale = []
    healthy_all = True
    state_paths = {"appstream": APPSTREAM_STORAGE_STATE, "ownerville": OWNERVILLE_STORAGE_STATE}
    for key, stt, reseed, reports in sessions:
        # PRESENT TENSE, not a forecast. `stt["ok"]` is "the stored token is
        # valid right now". It used to be "…and still valid after tomorrow's
        # 4am batch", which the ~2h rqst TTL makes impossible — see false alarm
        # #2 in the module docstring. The holder re-mints long before 4am, so a
        # token that cannot reach it is the normal state, not a fault.
        token_ok = bool(stt["ok"])
        age = _export_age_min(state_paths[key])
        export_fresh = age is not None and age <= STALE_EXPORT_MIN
        # A future-dated token whose file has gone stale means the holder stopped
        # validating/exporting it — effectively dead even though the timestamp
        # still reads "valid". Surface it; the expiry check alone would miss it.
        if token_ok and not export_fresh:
            note = (f" — but the holder hasn't re-exported in {age:.0f}m "
                    f"(holder down or session no longer validating)") if age is not None \
                   else " — but there is no export file (holder never ran)"
            stt = {**stt, "reason": stt["reason"] + note}
        healthy = token_ok and export_fresh
        # AppStream only: the expiry check alone cries wolf every night (see the
        # module docstring — a fresh token can't reach 4am, so "stale at 6pm" is
        # the normal, healthy state, and the holder re-mints one long before the
        # batch). Before pinging, ask the only question that matters: can a
        # report open the console RIGHT NOW, on the path a report actually uses?
        probe_failed = False
        # THE MINTER, NOT THE COPY (2026-08-31) — a suppression that NO LONGER
        # FIRES (2026-09-02). It existed because this machine consumed a token
        # Lucy 2 minted and pushed hourly, so between pushes its copy was short
        # or expired BY DESIGN and no login here could shorten the wait. Every
        # Lucy now mints its own, so there is no trough and nothing is old on
        # purpose: fleet_is_feeding_us() is hard-False and a dead session pages,
        # on the machine that can actually fix it. The call stays because its
        # reason string is what the log shows for why nothing was suppressed —
        # and because a silently-deleted suppression is harder to notice than a
        # stubbed one if this ever needs revisiting.
        fleet_fed = False
        if key == "appstream" and not healthy:
            fleet_fed, why_fed = fleet_is_feeding_us()
            if fleet_fed:
                healthy = True
                stt = {**stt, "reason": "{} (stored token: {})".format(
                    why_fed, stt["reason"])}
        if key == "appstream" and not healthy and ping_due and probe:
            probe_ok, why = probe_appstream_healthy()
            if probe_ok:
                healthy = True
                stt = {**stt, "reason": "{} reachable — {} (stored token: {})"
                                        .format(stt["what"], why, stt["reason"])}
            else:
                stt = {**stt, "reason": "{} — and a report cannot open the "
                                        "console: {}".format(stt["reason"], why)}
                probe_failed = True
        healthy_all = healthy_all and healthy
        was_ok = state.get(f"last_ok_{key}")
        if healthy:
            # Recovered in the morning window after being stale → a re-seed just
            # happened; auto-rerun this session's reports so nothing's missing.
            # NOT on the fleet-fed path: "healthy because the holder is still
            # feeding us" means nothing ever broke, so there is nothing to
            # re-run — and re-running the AppStream reports off a trough would
            # be exactly the blanket re-run this repo has been bitten by.
            if (was_ok is False and reports and not fleet_fed
                    and MORNING_WINDOW[0] <= now.hour < MORNING_WINDOW[1]
                    and state.get(f"reran_{key}") != today):
                for rid, rmachine in reports:
                    _enqueue_rerun(rid, dry_run, machine=rmachine)
                _alert(f"✅ {stt['what']} session is healthy again — auto-re-running "
                       f"{', '.join(rid for rid, _ in reports)} so nothing's "
                       f"missing. ({stt['reason']})",
                       dry_run)
                state[f"reran_{key}"] = today
            state[f"last_ok_{key}"] = True
        else:
            # THE INVARIANT: AppStream reaches the paging list ONLY on a failed
            # LIVE probe — never on the stored token alone. Its token is expired
            # or short more often than not (2h TTL, holder re-mints), so letting
            # the file's timestamp put it here is precisely the wolf. Ownerville
            # keeps its file-based verdict: its token is 24h, so "expired right
            # now with no fresh export" already means the holder is down.
            if key != "appstream" or probe_failed:
                stale.append((stt, reseed))
            if probe_failed:
                probed_stale.append((stt, reseed))
            state[f"last_ok_{key}"] = False

    # Heads-up pings, each held to an act-able window + once/day:
    #   • 6pm — the predictable "re-seed tonight" nudge.
    #   • 3am — a last-chance check ~1h before the 4am batch, catching a session
    #           that went stale AFTER the evening ping (which used to surface only
    #           as a 7am surprise). Both re-seeds need a human at the mini.
    # AppStream can only reach here after FAILING the live probe twice, so a ping
    # about it is a real "the automation cannot open the console", not a countdown.
    #
    # THE REAL-OUTAGE PATH, and the only one that is not window-gated. A report
    # that already failed for want of a session is not a forecast to sit on
    # until 6pm — it is today's data missing, now. Once per day so a re-detected
    # failure (or a resume) doesn't re-post.
    real_failures = appstream_session_failures(now) if probe else []
    if real_failures and state.get("alerted_realfail_for") != today:
        _alert(_real_failure_text(real_failures, _reseed_cmd()), dry_run)
        state["alerted_realfail_for"] = today
    elif stale:
        if daytime_due and probed_stale:
            _alert(_reseed_alert_text(
                probed_stale,
                "NOW — AppStream reports cannot run until it lands"), dry_run)
            state["alerted_daytime_for"] = today
        elif evening_due:
            _alert(_reseed_alert_text(stale, "before tomorrow's 4am reports"), dry_run)
            state["alerted_evening_for"] = today
        elif prebatch_due:
            _alert(_reseed_alert_text(stale, "before the 4am batch (~1h out)"), dry_run)
            state["alerted_prebatch_for"] = today

    state["last_checked"] = now.isoformat(timespec="seconds")
    state["last_reason"] = "; ".join(stt["reason"] for _, stt, _, _ in sessions)
    _save_state(state)
    return {"sessions": {stt["what"]: stt["reason"] for _, stt, _, _ in sessions},
            "stale": [stt["what"] for stt, _ in stale],
            # Renamed from "survives_next_4am_batch": nothing is forecast any
            # more, and the old name is what made an impossible prediction read
            # like a health verdict for as long as it did.
            "healthy_now": healthy_all,
            "failed_reports": [rid for rid, _ in real_failures],
            # Display only — what the stored token would have to reach to cover
            # the whole next batch on its own. It never can (2h TTL); the holder
            # is what covers it. Nothing pages on this.
            "would_need_token_until": threshold.isoformat(timespec="minutes")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Watch + recover the AppStream + ownerville sessions")
    ap.add_argument("--once", action="store_true", help="one evaluation (default)")
    ap.add_argument("--status", action="store_true",
                    help="print BOTH session statuses (AppStream + ownerville) + exit")
    ap.add_argument("--test-ping", action="store_true",
                    help="send a test Slack DM to the alert recipients to prove the path")
    ap.add_argument("--dry-run", action="store_true", help="no Slack / no enqueue")
    ap.add_argument("--probe", action="store_true",
                    help="run the AppStream probe now and exit — opens the "
                         "console on the SAME reuse path the 4am reports use "
                         "(no login form); exit 0 = a report could run now")
    ap.add_argument("--no-probe", action="store_true",
                    help="skip the live probe AND the day_state failure read, "
                         "leaving only the stored token's timestamp - debugging "
                         "only; AppStream can never page in this mode")
    a = ap.parse_args(argv)
    if a.status:
        for path, what in ((APPSTREAM_STORAGE_STATE, "AppStream"),
                           (OWNERVILLE_STORAGE_STATE, "Ownerville")):
            s = session_status(path, what)
            print(json.dumps({**s, "rqst_expiry": s["rqst_expiry"].isoformat()
                              if s["rqst_expiry"] else None}, indent=2))
        return 0
    if a.test_ping:
        _alert("✅ Test ping from appstream_watch — if you (Megan + Eve) both see "
               "this, the 6pm re-seed alerts will reach you. No action needed.",
               dry_run=False)
        return 0
    if a.probe:
        ok, why = selfheal_ok(verbose=True)
        # "OK / CANNOT OPEN" — never "BROKEN". The old word named a self-heal
        # that had been switched off on purpose, and that wording is half of why
        # a passing batch read as an outage for days.
        print("[appstream_watch] console probe: {} — {}".format(
            "OK" if ok else "CANNOT OPEN", why))
        return 0 if ok else 1
    res = watch(dry_run=a.dry_run, probe=not a.no_probe)
    print(f"[appstream_watch] healthy now: {res['healthy_now']} "
          f"(stale: {res['stale'] or 'none'}; "
          f"reports that failed on a session today: "
          f"{', '.join(res['failed_reports']) or 'none'})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

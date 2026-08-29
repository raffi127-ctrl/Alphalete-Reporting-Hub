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

HOW THE BATCH ACTUALLY SURVIVES THE NIGHT (Megan 2026-08-27). The session-holder
carries it, unattended, with no human login:

  • its 6-minute reload keeps the ColdFusion session (CFID/CFTOKEN) from
    idle-timing-out, indefinitely;
  • when the ~2h rqst lapses, `_warm_appstream` no longer short-circuits on a
    rendering console (`6665dff`, 8/25) — it falls through to the storage_state
    re-hop (`?rqst=<TOKEN>&p=701`) off that still-live ColdFusion session and
    comes back with a FRESH token, which it exports for the reports to reuse.

Measured on Lucy 1: token minted ~22:03 (expiry 12:03AM), re-minted by ~06:41
the next morning with nobody touching it; no "NO rqst" lapse in the 31h since
the 8/25 fix; and the 4am batch ran 47/50 clean (the 3 not-done were clock-gated,
none AppStream). Ownerville's holder self-heals the same way.

WHAT THIS WATCH MUST NOT DO. Until 2026-08-27 the probe drove the rcaptain FORM
login (force_form_login=True) and cried "the self-heal is BROKEN" when it
failed. But `d793ea3` had disabled that form for scheduled runs hours before, so
no report had taken it since — the watch was failing a route nothing uses and
waking people nightly while the batch ran fine. `selfheal_ok()` now drives the
REUSE path the reports drive. A ping means a real report would fail right now.

WHAT EVE DOES (everything but the click):
  • PREDICT  — read the rqst expiry from the stored session (cheap, no network,
               no Cloudflare risk).
  • PING     — if the session won't survive to the next 4am run, ping Megan ONCE
               with the exact re-seed command (a daily reminder until re-seeded).
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

# Reports that depend on the AppStream recruiting console — auto-rerun on recovery.
# FALLBACK ONLY. The live list is derived per-day by _appstream_reports_to_rerun()
# from schedule_config + today's day-state; this is what we use when either of
# those can't be read.
APPSTREAM_REPORTS_FALLBACK = ["daily_focus"]

# The session must stay valid through the 4am batch — require it to outlast 4am
# by this margin so the token covers the whole daily_focus run, not just its start.
SURVIVAL_BUFFER_MIN = 90
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

    What actually carries the batch is the session-holder: its 6-minute reload
    keeps the ColdFusion session (CFID/CFTOKEN, 24h) alive, and when the ~2h
    rqst lapses `_warm_appstream` falls through to the storage_state re-hop
    (`?rqst=<TOKEN>&p=701`) and comes back with a fresh token — the behaviour
    `6665dff` restored on 8/25. Measured on Lucy 1: token minted 22:03 → 12:03AM,
    then re-minted by 06:41 with nobody touching it, and no lapse warning since
    8/25 17:34. So the honest question is not "can we log in" — it is "does the
    session the reports will use authenticate", which is what this now asks.

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
    """(report_id, machine) for every AppStream-backed report today's batch did
    NOT finish — what a morning re-seed should pick up — in run order.

    This was a hardcoded ["daily_focus"], so a re-seed landing after 4am
    recovered exactly one of the AppStream reports and left the rest to be
    re-queued by hand, every morning, since the 2026-08-20 release human-gated
    the login form (Eve 2026-08-25: applicant_sync_morning +
    recruiter_retention_daily, every day). Derived now from the same two files
    the batch itself uses, which also settles the two ways a list like this goes
    wrong:

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
        pending = [r for r in registry.scheduled_today(cfg, day)
                   if r.source_type == "appstream"]
        if not pending:
            return []
        state_file = day_state.STATE_DIR / f"{day.isoformat()}.json"
        if state_file.exists():
            raw = json.loads(state_file.read_text(encoding="utf-8"))
            done = {rid for rid, rs in raw.get("reports", {}).items()
                    if rs.get("status") == day_state.DONE}
            pending = [r for r in pending if r.report_id not in done]
        pending.sort(key=lambda r: (r.order if r.order is not None else 10_000,
                                    r.report_id))
        return [(r.report_id, r.machine) for r in pending]
    except Exception as e:
        print(f"[appstream_watch] (couldn't derive the rerun list, falling back "
              f"to {APPSTREAM_REPORTS_FALLBACK}: {type(e).__name__}: {str(e)[:100]})")
        return [(rid, _registry_default_machine()) for rid in APPSTREAM_REPORTS_FALLBACK]


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
    lines = [f"⚠️ *Session re-seed needed* {when}."]
    for stt, reseed in stale:
        lines.append(f"\n• *{stt['what']}*: {stt['reason']}\n"
                     f"  The automated login already tried and could NOT recover "
                     f"this one. Fix from any machine you're at (clear the check "
                     f"once):\n```{reseed}```")
    lines.append("\nThe moment it's healthy I'll auto-run what I can — "
                 "you don't have to touch anything else.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The watch — one evaluation
# ---------------------------------------------------------------------------

def watch(dry_run: bool = False, probe: bool = True) -> dict:
    """One evaluation across BOTH sessions (AppStream recruiting console +
    ownerville/Tableau). Predict / ping / recover. Safe to call every few minutes
    (throttled to one ping + one rerun-batch per day). Never raises.

    probe=False skips the live AppStream self-heal check and judges by the stored
    token's expiry alone — the old, cry-wolf behaviour. Debugging only."""
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

    stale = []   # [(status, reseed_cmd), ...] for sessions that won't survive the batch
    # The subset of `stale` a LIVE probe just failed, i.e. "a report would fail
    # right now" rather than "the stored token is past its date". Only these earn
    # the daytime ping: ownerville is judged by expiry alone, and an unprobed
    # 8am ping about it every morning is the cry-wolf this window exists to avoid.
    probed_stale = []
    healthy_all = True
    state_paths = {"appstream": APPSTREAM_STORAGE_STATE, "ownerville": OWNERVILLE_STORAGE_STATE}
    for key, stt, reseed, reports in sessions:
        token_ok = bool(stt["ok"] and stt["rqst_expiry"] and stt["rqst_expiry"] >= threshold)
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
        if key == "appstream" and not healthy and ping_due and probe:
            probe_ok, why = selfheal_ok()
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
            if (was_ok is False and reports
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
            stale.append((stt, reseed))
            if probe_failed:
                probed_stale.append((stt, reseed))
            state[f"last_ok_{key}"] = False

    # Heads-up pings, each held to an act-able window + once/day:
    #   • 6pm — the predictable "re-seed tonight" nudge.
    #   • 3am — a last-chance check ~1h before the 4am batch, catching a session
    #           that went stale AFTER the evening ping (which used to surface only
    #           as a 7am surprise). Both re-seeds need a human at the mini.
    # AppStream can only reach here after FAILING the live self-heal probe, so a
    # ping about it is a real "the automation cannot log in", not a countdown.
    if stale:
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
            "survives_next_4am_batch": healthy_all,
            "next_threshold": threshold.isoformat(timespec="minutes")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Predict + recover the AppStream + ownerville sessions")
    ap.add_argument("--once", action="store_true", help="one evaluation (default)")
    ap.add_argument("--status", action="store_true",
                    help="print BOTH session statuses (AppStream + ownerville) + exit")
    ap.add_argument("--test-ping", action="store_true",
                    help="send a test Slack DM to the alert recipients to prove the path")
    ap.add_argument("--dry-run", action="store_true", help="no Slack / no enqueue")
    ap.add_argument("--probe", action="store_true",
                    help="run the AppStream self-heal probe now and exit (drives "
                         "the unattended rcaptain login -> re-seeds this machine)")
    ap.add_argument("--no-probe", action="store_true",
                    help="judge AppStream by the stored token's expiry alone "
                         "(the old cry-wolf behaviour - debugging only)")
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
        print("[appstream_watch] self-heal probe: {} — {}".format(
            "OK" if ok else "BROKEN", why))
        return 0 if ok else 1
    res = watch(dry_run=a.dry_run, probe=not a.no_probe)
    print(f"[appstream_watch] survives next 4am batch: {res['survives_next_4am_batch']} "
          f"(stale: {res['stale'] or 'none'}; needs valid until {res['next_threshold']})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

"""AppStream session watch — predict the recruiting-console session dying and
recover from it, so the 4am unattended reports (daily_focus, recruiter_retention)
never surprise-fail at 4am.

WHY THIS EXISTS
The recruiting console is authenticated by an `rqst` SSO token (+ ColdFusion
CFID/CFTOKEN) that carries a FIXED, server-set expiry (~daily). The session-holder
reloads the console every few minutes, which keeps the ColdFusion session from
*idle*-timing-out — but it CANNOT refresh the rqst token or the Cloudflare
clearance. Only a fresh, human-cleared login mints a new rqst token, and clearing
the Cloudflare Turnstile is bot-detection (prohibited + actually blocked). So the
session dies on the server's schedule and a human MUST re-seed. We can't prevent
that — but the rqst expiry is a readable timestamp, so we can predict it and
shrink the human's job to a single 30-second click at a convenient time.

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
from pathlib import Path

from automations.shared.tableau_patchright import (
    APPSTREAM_STORAGE_STATE, OWNERVILLE_STORAGE_STATE,
)

WATCH_STATE = Path(__file__).resolve().parents[2] / "output" / "appstream_watch_state.json"

# Slack DM recipients for the re-seed ping — BOTH get it so whoever's free does
# the 30-sec re-seed if the other can't (Megan 2026-06-26). Megan Hidalgo +
# Evelyn ("Eve") Sobrino. Tunable: add/remove user ids (or a channel id).
ALERT_SLACK_TARGETS = ["U04G5HJBGFN", "U088E2KJEV8"]

# Reports that depend on the AppStream recruiting console — auto-rerun on recovery.
# One entry now: daily_focus runs every captainship in one pass (--captainship all).
APPSTREAM_REPORTS = ["daily_focus"]

# The session must stay valid through the 4am batch — require it to outlast 4am
# by this margin so the token covers the whole daily_focus run, not just its start.
SURVIVAL_BUFFER_MIN = 90
# A recovery during this window means a 4am failure we should re-run; a recovery
# outside it (e.g. an evening proactive re-seed) needs no rerun.
MORNING_WINDOW = (4, 12)   # [4am, noon)

# Send the proactive "re-seed tonight" ping in the EVENING only — a predictable
# 6pm heads-up you can act on before bed beats a random-time one (Megan
# 2026-06-26: "slack Eve at 6pm if she needs the reseed to happen"). The watch
# still runs every 6 min, but it HOLDS the ping until this hour.
PING_HOUR = 18   # 6pm (mini local time)
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
    if latest <= now:
        return {"ok": False, "rqst_expiry": exp, "hours_left": hours, "what": what,
                "reason": f"{what} rqst token EXPIRED {-hours:.1f}h ago (at {exp:%b %-d %-I:%M%p})"}
    return {"ok": True, "rqst_expiry": exp, "hours_left": hours, "what": what,
            "reason": f"{what} rqst token valid {hours:.1f}h more (until {exp:%b %-d %-I:%M%p})"}


def _next_4am(now: dt.datetime | None = None) -> dt.datetime:
    now = now or _now()
    four = now.replace(hour=4, minute=0, second=0, microsecond=0)
    return four if now < four else four + dt.timedelta(days=1)


def _reseed_cmd() -> str:
    return ("cd /Users/alphalete/recruiting-report && PYTHONPATH=. .venv/bin/python "
            "-m automations.shared.tableau_patchright --appstream-login")


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


def _enqueue_rerun(report_id: str, dry_run: bool) -> None:
    print(f"[appstream_watch] enqueue rerun {report_id}")
    if dry_run:
        return
    try:
        from automations.day_orchestrator import mini_control
        mini_control.enqueue("rerun", report_id, by="appstream_watch")
    except Exception as e:
        print(f"[appstream_watch] (enqueue failed: {type(e).__name__}: {str(e)[:100]})")


def _reseed_alert_text(stale, when: str) -> str:
    """Build the re-seed DM. `stale` is [(status, reseed_cmd), ...]; `when` frames
    the urgency (evening 'tonight' vs the 3am '~1h before the batch')."""
    lines = [f"⚠️ *Session re-seed needed* {when}."]
    for stt, reseed in stale:
        lines.append(f"\n• *{stt['what']}*: {stt['reason']}\n"
                     f"  Fix on the mini (clear the check once):\n```{reseed}```")
    lines.append("\nThe moment it's healthy I'll auto-run what I can — "
                 "you don't have to touch anything else.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The watch — one evaluation
# ---------------------------------------------------------------------------

def watch(dry_run: bool = False) -> dict:
    """One evaluation across BOTH sessions (AppStream recruiting console +
    ownerville/Tableau). Predict / ping / recover. Safe to call every few minutes
    (throttled to one ping + one rerun-batch per day). Never raises."""
    state = _load_state()
    now = _now()
    today = now.date().isoformat()
    threshold = _next_4am(now) + dt.timedelta(minutes=SURVIVAL_BUFFER_MIN)

    # (key, status, re-seed cmd, reports to auto-rerun on morning recovery).
    # Ownerville recovery has no auto-rerun list — the 4am failure email already
    # lists those reports with their `lucy rerun` lines, so we don't double-fire.
    sessions = [
        ("appstream",  session_status(APPSTREAM_STORAGE_STATE, "AppStream"),
         _reseed_cmd(),    APPSTREAM_REPORTS),
        ("ownerville", session_status(OWNERVILLE_STORAGE_STATE, "Ownerville"),
         _ov_reseed_cmd(), []),
    ]

    stale = []   # [(status, reseed_cmd), ...] for sessions that won't survive the batch
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
        healthy_all = healthy_all and healthy
        was_ok = state.get(f"last_ok_{key}")
        if healthy:
            # Recovered in the morning window after being stale → a re-seed just
            # happened; auto-rerun this session's reports so nothing's missing.
            if (was_ok is False and reports
                    and MORNING_WINDOW[0] <= now.hour < MORNING_WINDOW[1]
                    and state.get(f"reran_{key}") != today):
                for rid in reports:
                    _enqueue_rerun(rid, dry_run)
                _alert(f"✅ {stt['what']} session is healthy again — auto-re-running "
                       f"{', '.join(reports)} so nothing's missing. ({stt['reason']})",
                       dry_run)
                state[f"reran_{key}"] = today
            state[f"last_ok_{key}"] = True
        else:
            stale.append((stt, reseed))
            state[f"last_ok_{key}"] = False

    # Heads-up pings, each held to an act-able window + once/day:
    #   • 6pm — the predictable "re-seed tonight" nudge.
    #   • 3am — a last-chance check ~1h before the 4am batch, catching a session
    #           that went stale AFTER the evening ping (which used to surface only
    #           as a 7am surprise). Both re-seeds need a human at the mini.
    if stale:
        if now.hour >= PING_HOUR and state.get("alerted_evening_for") != today:
            _alert(_reseed_alert_text(stale, "before tomorrow's 4am reports"), dry_run)
            state["alerted_evening_for"] = today
        elif (PRE_BATCH_PING_HOUR <= now.hour < MORNING_WINDOW[0]
              and state.get("alerted_prebatch_for") != today):
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
    res = watch(dry_run=a.dry_run)
    print(f"[appstream_watch] survives next 4am batch: {res['survives_next_4am_batch']} "
          f"(stale: {res['stale'] or 'none'}; needs valid until {res['next_threshold']})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

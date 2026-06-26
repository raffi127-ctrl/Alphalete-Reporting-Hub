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

from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE

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


def _now() -> dt.datetime:
    return dt.datetime.now()


# ---------------------------------------------------------------------------
# Probe — read when the session dies. Cheap, no network.
# ---------------------------------------------------------------------------

def session_status() -> dict:
    """Report when the stored AppStream session dies. The rqst SSO token's
    `expires` is the binding constraint for whether the recruiting console will
    still authenticate; CFID/CFTOKEN ride alongside it.

    Returns {ok, rqst_expiry: datetime|None, hours_left: float|None, reason}."""
    if not APPSTREAM_STORAGE_STATE.exists():
        return {"ok": False, "rqst_expiry": None, "hours_left": None,
                "reason": "no stored AppStream session — never seeded"}
    try:
        cookies = json.loads(APPSTREAM_STORAGE_STATE.read_text()).get("cookies", [])
    except Exception as e:
        return {"ok": False, "rqst_expiry": None, "hours_left": None,
                "reason": f"session file unreadable: {str(e)[:80]}"}
    now = _now().timestamp()
    rqst_exps = [c.get("expires") for c in cookies
                 if (c.get("name") or "").lower().startswith("rqst")
                 and isinstance(c.get("expires"), (int, float)) and c["expires"] > 0]
    if not rqst_exps:
        return {"ok": False, "rqst_expiry": None, "hours_left": None,
                "reason": "no rqst SSO token in the session (degraded / SSO-only)"}
    latest = max(rqst_exps)
    hours = (latest - now) / 3600
    exp = dt.datetime.fromtimestamp(latest)
    if latest <= now:
        return {"ok": False, "rqst_expiry": exp, "hours_left": hours,
                "reason": f"rqst token EXPIRED {-hours:.1f}h ago (at {exp:%b %-d %-I:%M%p})"}
    return {"ok": True, "rqst_expiry": exp, "hours_left": hours,
            "reason": f"rqst token valid {hours:.1f}h more (until {exp:%b %-d %-I:%M%p})"}


def _next_4am(now: dt.datetime | None = None) -> dt.datetime:
    now = now or _now()
    four = now.replace(hour=4, minute=0, second=0, microsecond=0)
    return four if now < four else four + dt.timedelta(days=1)


def _reseed_cmd() -> str:
    return ("cd /Users/alphalete/recruiting-report && PYTHONPATH=. .venv/bin/python "
            "-m automations.shared.tableau_patchright --appstream-login")


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


# ---------------------------------------------------------------------------
# The watch — one evaluation
# ---------------------------------------------------------------------------

def watch(dry_run: bool = False) -> dict:
    """One evaluation: predict / ping / recover. Safe to call every few minutes
    (throttled to one ping + one rerun-batch per day). Never raises."""
    st = session_status()
    state = _load_state()
    now = _now()
    today = now.date().isoformat()
    threshold = _next_4am(now) + dt.timedelta(minutes=SURVIVAL_BUFFER_MIN)
    survives = bool(st["ok"] and st["rqst_expiry"] and st["rqst_expiry"] >= threshold)
    was_ok = state.get("last_ok")

    if survives:
        # Healthy through the next 4am batch. If we were stale before, a re-seed
        # just happened — auto-rerun the AppStream reports IF this is the morning
        # window (i.e. they likely failed at 4am). An evening proactive re-seed
        # recovers without needing a rerun.
        if (was_ok is False
                and MORNING_WINDOW[0] <= now.hour < MORNING_WINDOW[1]
                and state.get("reran_for") != today):
            for rid in APPSTREAM_REPORTS:
                _enqueue_rerun(rid, dry_run)
            _alert(f"✅ AppStream session is healthy again — auto-re-running "
                   f"{', '.join(APPSTREAM_REPORTS)} so nothing's missing. "
                   f"({st['reason']})", dry_run)
            state["reran_for"] = today
        state["last_ok"] = True
    else:
        # Won't survive to the next 4am batch — needs a human re-seed. HOLD the
        # ping until the evening (PING_HOUR) so it lands when Megan can act on it,
        # then send it once/day. (last_ok is still tracked now, regardless of the
        # ping time, so morning auto-recovery works whenever the re-seed happens.)
        if now.hour >= PING_HOUR and state.get("alerted_for") != today:
            _alert(
                "⚠️ *AppStream re-seed needed* before tomorrow's 4am reports "
                "(daily_focus + recruiter retention).\n"
                f"• {st['reason']}\n"
                "• It's a 30-sec job: on the mini, run the re-seed and clear the "
                "Cloudflare check once:\n"
                f"```{_reseed_cmd()}```\n"
                "The moment it's healthy I'll auto-run the reports — you don't "
                "have to touch anything else.",
                dry_run)
            state["alerted_for"] = today
        state["last_ok"] = False

    state["last_checked"] = now.isoformat(timespec="seconds")
    state["last_reason"] = st["reason"]
    _save_state(state)
    return {"status": st, "survives_next_4am_batch": survives,
            "next_threshold": threshold.isoformat(timespec="minutes")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Predict + recover the AppStream session")
    ap.add_argument("--once", action="store_true", help="one evaluation (default)")
    ap.add_argument("--status", action="store_true", help="just print session_status + exit")
    ap.add_argument("--dry-run", action="store_true", help="no Slack / no enqueue")
    a = ap.parse_args(argv)
    if a.status:
        s = session_status()
        print(json.dumps({**s, "rqst_expiry": s["rqst_expiry"].isoformat() if s["rqst_expiry"] else None}, indent=2))
        return 0
    res = watch(dry_run=a.dry_run)
    print(f"[appstream_watch] survives next 4am batch: {res['survives_next_4am_batch']} "
          f"(needs valid until {res['next_threshold']})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

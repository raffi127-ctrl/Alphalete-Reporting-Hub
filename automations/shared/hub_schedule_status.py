"""Resolve a Hub card's REAL auto-run status for the change-notification email.

"Assigned to Lucy 2" (card display) and "actually auto-runs on Lucy 2"
(execution) are two separate settings today. This reads the execution truth —
day_orchestrator/schedule_config.json — and combines it with Megan's rule
(assignee = the machine; 4–8 AM → that machine's morning batch, otherwise a
standalone timer at its time) to answer, for a card assigned to a Lucy machine:

  • which machine it should run on,
  • its schedule in plain English,
  • whether it's ACTUALLY wired to auto-run (or just assigned, not scheduled),
  • and — when it isn't — what the rule says it SHOULD be wired as.

Best-effort and read-only: never raises to the caller (returns None on any
trouble), so a notification never fails over scheduling introspection.
"""
from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _REPO_ROOT / "automations" / "day_orchestrator" / "schedule_config.json"

_LUCY = {"Lucy 1", "Lucy 2"}
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
         "Saturday", "Sunday"]

# Megan's rule: a scheduled time inside [MORNING_START, MORNING_END) joins the
# machine's 4am morning batch; anything else gets its own standalone timer.
MORNING_START = 4
MORNING_END = 8


def _machine_of(assignees) -> str | None:
    for a in assignees or []:
        if a in _LUCY:
            return a
    return None


def _parse_hour(time_str: str) -> int | None:
    """Hour-of-day (0–23) from a '11:00 AM' / '8:30 AM' style string."""
    s = (time_str or "").strip().upper()
    if not s:
        return None
    ampm = None
    if s.endswith("AM") or s.endswith("PM"):
        ampm = s[-2:]
        s = s[:-2].strip()
    try:
        hh = int(s.split(":")[0])
    except (ValueError, IndexError):
        return None
    if ampm == "PM" and hh != 12:
        hh += 12
    elif ampm == "AM" and hh == 12:
        hh = 0
    return hh if 0 <= hh <= 23 else None


def _days_phrase(weekdays) -> str:
    if not weekdays:
        return ""
    wd = sorted(int(d) for d in weekdays if 0 <= int(d) <= 6)
    if wd == [0, 1, 2, 3, 4]:
        return "weekdays (Mon–Fri)"
    if wd == list(range(7)):
        return "every day"
    return ", ".join(_DAYS[d] + "s" for d in wd)


def _human_schedule(schedule: dict) -> str:
    """'Weekly · Wednesdays · 11:00 AM' from the card's schedule dict."""
    if not isinstance(schedule, dict):
        return "—"
    freq = str(schedule.get("frequency") or "").strip().title()
    days = _days_phrase(schedule.get("weekdays"))
    time_ = str(schedule.get("time") or "").strip()
    parts = [p for p in (freq or None, days or None, time_ or None) if p]
    return " · ".join(parts) if parts else "—"


def _config_entry(card_id: str):
    """The schedule_config.json entry for this card id (hyphen/underscore
    tolerant), or None. Returns (report_id, entry)."""
    try:
        reports = json.loads(_CONFIG.read_text()).get("reports", {})
    except Exception:
        return None
    if not card_id:
        return None
    want = {card_id, card_id.replace("-", "_"), card_id.replace("_", "-")}
    for rid, entry in reports.items():
        if rid in want:
            return rid, entry
    return None


def resolve(card_id: str, assignees, schedule) -> dict | None:
    """Return the auto-run status for a card assigned to a Lucy machine, or None
    if it isn't assigned to one (then there's no machine-scheduling to report)."""
    try:
        machine = _machine_of(assignees)
        if not machine:
            return None

        human = _human_schedule(schedule)
        hour = _parse_hour((schedule or {}).get("time")) if isinstance(schedule, dict) else None
        # Per the rule: which mechanism SHOULD carry this time?
        if hour is None:
            intended = "morning batch or a standalone timer (no time set)"
        elif MORNING_START <= hour < MORNING_END:
            intended = f"{machine}'s morning batch"
        else:
            t = (schedule or {}).get("time") or "its scheduled time"
            intended = f"a standalone timer on {machine} at {t}"

        found = _config_entry(card_id)
        if found:
            _, entry = found
            on = bool(entry.get("on_scheduler"))
            weekdays = (entry.get("cadence") or {}).get("weekdays") or []
            cfg_machine = entry.get("machine") or "Lucy 1"
            if on and weekdays:
                wired = True
                kind = "morning batch"
                status = f"✅ Auto-runs in {cfg_machine}'s morning batch ({_days_phrase(weekdays)})."
            elif on and not weekdays:
                wired = True
                kind = "standalone timer"
                status = (f"✅ Runs on {cfg_machine} as a standalone scheduled task "
                          "(its own launchd timer, not the morning batch).")
            else:
                wired = False
                kind = None
                status = (f"⚠️ Not auto-running — it's in the scheduler config but "
                          "turned off (on_scheduler: false).")
        else:
            wired = False
            kind = None
            status = (f"⚠️ Not auto-running yet — assigned to {machine} but no "
                      "active schedule is wired.")

        return {
            "machine": machine,
            "human_schedule": human,
            "wired": wired,
            "kind": kind,
            "status": status,
            "intended": intended,   # what the rule says it should be
        }
    except Exception:
        return None

"""The words. Short; the picture carries the detail."""
from __future__ import annotations

from typing import Optional

from automations.recruiting_day_texts import config as C


def pct(showed: int, scheduled: int) -> int:
    return int(round(100.0 * showed / scheduled)) if scheduled else 0


def has_anything(day) -> bool:
    return bool(day.first or day.second or day.ns_scheduled)


def morning(office: C.Office, day) -> Optional[str]:
    """None = nothing on the calendar today -> send nothing (never a blank).
    The picture carries the schedule; the text is just the greeting (Megan
    2026-11-13)."""
    if not has_anything(day):
        return None
    return "Good Morning %s Team \u2600\ufe0f Here\u2019s today's Schedule:" % office.team


def showed(office: C.Office, day) -> Optional[str]:
    """None = no new starts were scheduled today -> no 4pm text. The names
    (showed / no show) are in the picture."""
    sched, came = len(day.ns_scheduled), len(day.ns_showed)
    if not sched:
        return None
    return ("New Starts Update: %d/%d showed \u2014 %d%% retention"
            % (came, sched, pct(came, sched)))

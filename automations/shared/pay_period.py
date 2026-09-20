"""Pay weeks: Sunday-Saturday activation week, paid the Friday after.

One place for the calendar the Order Log tab and the Office Info image both
draw (Raf 2026-09-16)."""
from __future__ import annotations

from datetime import date, timedelta


def week_bounds(d: date) -> tuple:
    """Sun-Sat week containing d -> (sunday, saturday, paid_friday)."""
    start = d - timedelta(days=(d.weekday() + 1) % 7)
    end = start + timedelta(days=6)
    return start, end, end + timedelta(days=6)


def pay_weeks(today: date, back: int, total: int) -> list:
    """`total` weeks of (sunday, saturday, paid_friday), starting `back` weeks
    before the week containing today."""
    this_sun = week_bounds(today)[0]
    return [week_bounds(this_sun + timedelta(weeks=i))
            for i in range(-back, total - back)]

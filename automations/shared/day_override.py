"""One-off calendar overrides: a date that should run on another day's rules.

Carlos 2026-10-04: "just for this sunday lets treat it as saturday" -- his
reports (Box and Fiber) keep Saturday hours on that date. Raf's own rooms are
NOT on this list's path: every caller here is a Carlos-only report or the
guest half of a shared one. Remove the date once it has passed; nothing else
needs reverting.
"""
from __future__ import annotations

import datetime as dt

TREAT_AS_SATURDAY = {"2026-10-04"}


def weekday(d: "dt.date | dt.datetime") -> int:
    """Python weekday() (Mon=0 .. Sun=6), with the overrides applied."""
    day = d.date() if isinstance(d, dt.datetime) else d
    return 5 if day.isoformat() in TREAT_AS_SATURDAY else day.weekday()

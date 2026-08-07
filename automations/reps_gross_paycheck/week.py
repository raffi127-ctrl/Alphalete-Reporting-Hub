"""Week maths — the one-week lag that is the whole point of this report.

Every rep tab, the sales board and the PNL all key off the WEEK-ENDING SUNDAY.
The lag: what a rep is paid on Thursday is what the PNL settled the week
BEFORE, so the column headed with the COMING Sunday gets the PNL's PREVIOUS
Sunday.

  filled on Thu 2026-08-06
    -> target column  WE 8/9   (the Sunday that closes this week)
    -> PNL 'Got Paid' WE 8/2   (the Sunday before it)

Verified against the history Eve had already typed in by hand: of the 245 cells
where both sides carry a 2026 number, 241 match the ONE-WEEK-LAGGED PNL value
and 4 don't (probe 2026-08-06, output/reps_gross_paycheck/offset_check.txt).
The same-week reading matches almost nothing, so the lag is not a coin flip.

`target_sunday` deliberately does NOT depend on the run happening on a
Thursday: it's the Sunday that closes whatever week you run it in. A Thursday
run that slips to Friday still fills the same column, and a re-run is a no-op.
"""
from __future__ import annotations

import datetime as dt
from typing import List

LAG = dt.timedelta(days=7)

# Eve stopped filling these tabs after the WE 6/21 column, so 6/28 is the first
# gap. Used as the default floor for --backfill.
BACKFILL_FROM = dt.date(2026, 6, 28)


def week_sunday(d: dt.date) -> dt.date:
    """The Sunday that ends `d`'s Monday-first week (Sunday maps to itself)."""
    return d + dt.timedelta(days=6 - d.weekday())


def target_sunday(today: dt.date) -> dt.date:
    """The rep-tab column this run fills."""
    return week_sunday(today)


def source_sunday(target: dt.date) -> dt.date:
    """The PNL 'Got Paid' week that feeds `target`."""
    return target - LAG


def sundays_between(first: dt.date, last: dt.date) -> List[dt.date]:
    """Every week-ending Sunday from `first` through `last`, inclusive."""
    first, last = week_sunday(first), week_sunday(last)
    out, d = [], first
    while d <= last:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def md(d: dt.date) -> str:
    """'8/9' — how both the PNL headers and the tab headers read a week."""
    return f"{d.month}/{d.day}"

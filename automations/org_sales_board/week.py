"""The ORG Sales Board's reporting-week model — ONE source of truth.

The board's week rolls on TUESDAY (see rollover.py), one day AFTER the
calendar week boundary. So on MONDAY the board is still reporting the
JUST-FINISHED week: on Mon 6/8 the active week is 6/1–6/7 (Mon–Sun), all 7
days complete; the rollover (freeze + advance the columns) runs Tuesday.
(Megan 2026-06-08: "Monday fills last week entirely; rollover is Tuesday.")

This must be applied in TWO coordinated places, or data gets mislabeled
(verified 2026-06-08):
  1. PIN — the Tableau views are pinned to a week-ending via the
     'Sale Date Week Ending (mon-sun)' filter. Pin to reporting_sunday() so
     on Monday the views RETURN last week's complete data (confirmed: pinning
     WE 6/7 on Monday returned all 54 owners; the default/this-week pin
     returned only Monday's 2). Without the pin the views give this week's
     partial data.
  2. LABEL — weekday-named columns ("Monday"…) are mapped to dates via
     reporting_monday(); the fill + compare use reporting_week(). So last
     week's data lands in last week's 6/1–6/7 columns.

Keep the two concepts separate:
  • reporting_monday / reporting_week / reporting_sunday — WHICH week (lagged
    on Monday). Use wherever code computed `today - today.weekday()` or pinned
    `today + (6 - today.weekday())`.
  • completed_days — which days are DONE, vs the REAL today (so on Monday all
    7 of last week count as complete).
Only MONDAY behavior changes; Tue–Sun are identical to before.
"""
from __future__ import annotations

import datetime as dt
from typing import List


def _ref(today: dt.date) -> dt.date:
    """The date whose calendar week is the board's active reporting week.
    Lags one day on Monday so the week rolls Tuesday, not Monday."""
    return today - dt.timedelta(days=1) if today.weekday() == 0 else today


def reporting_monday(today: dt.date) -> dt.date:
    """Monday of the board's active reporting week (last week's Monday on a
    Monday; this week's Monday Tue–Sun)."""
    ref = _ref(today)
    return ref - dt.timedelta(days=ref.weekday())


def reporting_week(today: dt.date) -> List[dt.date]:
    """The 7 dates (Mon–Sun) of the active reporting week."""
    m = reporting_monday(today)
    return [m + dt.timedelta(days=i) for i in range(7)]


def reporting_sunday(today: dt.date) -> dt.date:
    """Sunday (week-ending) of the active reporting week — what the Tableau
    views must be pinned to."""
    return reporting_monday(today) + dt.timedelta(days=6)


def completed_days(today: dt.date) -> List[dt.date]:
    """Days of the active reporting week that are fully complete — strictly
    before the REAL today. Monday = all 7 of last week; Tue 1; … Sun 6."""
    return [d for d in reporting_week(today) if d < today]

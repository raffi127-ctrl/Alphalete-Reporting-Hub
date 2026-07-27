"""Week maths for the Country Sales Board.

The board's week is MONDAY-first, Sunday-ending — the day header row reads
Monday..Sunday and the leaderboard columns are labelled by the ending Sunday
("WE 07.26").

IT ROLLS TUESDAY, like the ORG board (Eve 2026-07-27). On MONDAY the board is
still reporting the week that just ended, because Monday's fill exists to write
SUNDAY's production into it; the columns advance Tuesday. `reporting_sunday`
below is that model — the same one org_sales_board.week implements — and it is
what `rollover.needs_rollover` keys off.

The SOURCE agrees. Tableau's 'D2D Page 1 - This Week' tracker (the
'Sales By ICD (ATT) (V2)' worksheet, whose header row literally reads
'This Week') is on the same Tuesday-rolling week: the 2026-07-20 probe — taken
on a MONDAY — returned Mon (07-13)..Sun (07-19), i.e. the closing week, not the
calendar one (output/probe_d2d_Sales_By_ICD_ATT_V2_.csv). So board week and
source week advance together and Monday fills Sunday into the week it belongs
to. `pull.pull_icd_days_aligned` does not TRUST that alignment, it verifies it
and falls back to the (LW2) worksheet if the source ever rolls a day early.

The authority on which week the board is CURRENTLY showing is still the sheet
itself — the day-number row under the day headers — not the calendar. See
`sheet_week`: it reads those numbers back into real dates. That way a board
that hasn't rolled yet (or was rolled early) is filled for the week it is
actually displaying, and the fill can never write Tuesday's numbers into a
column headed with a different date. [[feedback_no_hardcoded_columns]]
"""
from __future__ import annotations

import datetime as dt
from typing import List


def week_monday(d: dt.date) -> dt.date:
    """The Monday that starts `d`'s week."""
    return d - dt.timedelta(days=d.weekday())


def week_sunday(d: dt.date) -> dt.date:
    """The Sunday that ends `d`'s week (Mon-Sun)."""
    return week_monday(d) + dt.timedelta(days=6)


def reporting_sunday(d: dt.date) -> dt.date:
    """Week-ending Sunday of the board's ACTIVE reporting week — the week the
    daily fill is about to write into, and therefore the week the board should
    be displaying.

    Lags one day on Monday so the board rolls TUESDAY, not Monday: on Mon 7/27
    this is still 7/26, because Monday's run exists to write Sunday 7/26 into
    the week that just closed. Rolling Monday would advance the columns out from
    under that fill and lose every Sunday. Identical to
    org_sales_board.week.reporting_sunday — kept here so this module stays the
    one place the Country board's week is defined."""
    ref = d - dt.timedelta(days=1) if d.weekday() == 0 else d
    return week_sunday(ref)


def week_dates(sunday: dt.date) -> List[dt.date]:
    """The 7 dates Mon..Sun of the week ending on `sunday`, in board order."""
    monday = sunday - dt.timedelta(days=6)
    return [monday + dt.timedelta(days=i) for i in range(7)]


def we_label(sunday: dt.date, pad: bool = True) -> str:
    """The board's week label for a week-ending Sunday.

    The tab uses BOTH conventions: the leaderboard header row is zero-padded
    ("WE 07.26") while the WE history stack in col A is not ("WE 7.19"). Callers
    that WRITE a label must pass the convention of the block they're writing;
    callers that MATCH one should compare against both (see `label_matches`)."""
    if pad:
        return f"WE {sunday.month:02d}.{sunday.day:02d}"
    return f"WE {sunday.month}.{sunday.day}"


def label_matches(text: str, sunday: dt.date) -> bool:
    """True if `text` is this Sunday's WE label in EITHER padding convention."""
    t = (text or "").strip().upper().replace(" ", "")
    return t in {we_label(sunday, True).upper().replace(" ", ""),
                 we_label(sunday, False).upper().replace(" ", "")}


def sheet_week(day_col_by_daynum: dict, today: dt.date,
               search_weeks: int = 6) -> List[dt.date]:
    """Resolve the day-of-month numbers the board is showing into real dates.

    `day_col_by_daynum` is {day_of_month: column} from
    fill_section.find_daily_section. Its numbers alone are ambiguous (a "3"
    could be this month or next), and they WRAP across a month boundary
    (29,30,31,1,2,3,4) so they can't just be sorted. So we walk candidate
    Mon-Sun weeks either side of `today` and return the one whose day numbers,
    read in COLUMN order, match the sheet exactly.

    Raises ValueError when no nearby week matches — that means the day-number
    row is malformed (or the board is rolled far out of range), which is worth
    failing loudly on rather than guessing a week and filling the wrong column.
    """
    daynums = [d for d, _c in sorted(day_col_by_daynum.items(),
                                     key=lambda kv: kv[1])]
    base = week_sunday(today)
    for offset in range(-search_weeks, search_weeks + 1):
        sunday = base + dt.timedelta(weeks=offset)
        dates = week_dates(sunday)
        if [d.day for d in dates] == daynums:
            return dates
    raise ValueError(
        f"the board's day numbers {daynums} don't match any Mon-Sun week "
        f"within {search_weeks} weeks of {today.isoformat()} — check the "
        f"day-number row under the day headers")

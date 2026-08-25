"""Fold SEVERAL days of knock rows into ONE board's worth of rows.

WHY THIS EXISTS RATHER THAN AN OWNERVILLE DATE RANGE. The Disposition page
(p=89) really is server-side range-filtered — `?startDate=&endDate=` — so one
navigation could return a whole week. Two things make that the wrong tool:

  1. The Time Tracker endpoint (p=510) takes `dateToSearch=<one day>`. It has
     no range at all, and it is where Gaps / Total Gaps come from — and for a
     gaps-only (NDS) office it IS the entire board. So a range pull would still
     have to walk the days for half its data.
  2. 'Avg. Hrs Knocking' is DERIVED as (Last Knock − First Knock) − Total Gaps.
     That is clock arithmetic for ONE day. Handed a week's aggregate row it
     computes one day's span minus seven days of gaps — a wrong number on
     Raf's board, silently, with no exception to notice.

Pulling day by day and folding here fixes both, and buys the thing that
actually makes on-demand ranges fast: every day is INDIVIDUALLY cacheable, so
a week that overlaps mornings we already pulled is answered from disk without
opening ownerville at all. A server-side range could never hit that cache.

WHAT THE AGGREGATE MEANS (say it out loud, because a screenshot of the board
outlives the message that explained it):
  · counts, Gaps, Total Gaps  — summed across the days
  · First Knock / Last Knock  — the EARLIEST and LATEST in the window, not an
    average: a literal aggregate nobody can mistake for a statistic
  · Avg. Hrs Knocking         — per-day hours, averaged over the days that rep
    ACTUALLY knocked. Raf's column is "AVG Hrs knocking per day", so a 7-day
    board must not show 7× a day's hours under it.

ONE DAY IS NOT AGGREGATED. `aggregate_days` with a single day returns those
rows unchanged — same objects, no added keys — so a one-day range renders
byte-identically to what `/knocks` has always sent.

No PIL and no browser in this module on purpose: the fold is pure, so it is
tested offline (`test_aggregate_days`).
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable, List, Optional

from automations.total_knocks.pull import (
    COL_FIRST_KNOCK,
    COL_GAPS,
    COL_ID,
    COL_LAST_KNOCK,
    COL_REP,
    COL_TOTAL_GAPS,
    COL_TT_BREAKS,
    COL_TT_SALES,
    COL_TT_SALES_TIME,
)

# Derived at render time (Raf 2026-08-23: "AVG Hrs knocking per day"):
# (last knock − first knock) − total gaps. Lives here rather than in `render`
# so the multi-day fold and the board share ONE definition of the column.
COL_HRS_KNOCKING = "Avg. Hrs Knocking"

# A time that didn't parse sorts after every real one (render relies on this).
NO_TIME = 24 * 60 + 1

# Merged by hand, not by summing: the two knock times fold to earliest/latest,
# and identity is carried through rather than added up.
_TIME_COLS = frozenset({COL_FIRST_KNOCK, COL_LAST_KNOCK})
_IDENTITY_COLS = frozenset({COL_ID, COL_REP})
# Time Tracker columns the live page leaves EMPTY when they're zero. They sum
# like any other number; they just render blank at zero (`pull._blank_zero`).
_BLANK_ZERO_COLS = frozenset({COL_TT_BREAKS, COL_TT_SALES_TIME, COL_TT_SALES})

# A request is capped so nobody waits on a quarter of scraping by typing two
# far-apart dates into a picker. 31 days covers "last month" whole.
MAX_RANGE_DAYS = 31


def knock_time_key(v) -> int:
    """'2:31 PM' -> minutes since midnight; blank/unparsable sorts last.

    strptime %I (not %-I) so it runs on Windows too."""
    s = str(v or "").strip()
    try:
        t = dt.datetime.strptime(s, "%I:%M %p")
        return t.hour * 60 + t.minute
    except ValueError:
        return NO_TIME


def fmt_time(minutes: int) -> str:
    """Minutes since midnight -> '2:31 PM' — the inverse of `knock_time_key`,
    so a folded time re-parses to exactly what went in."""
    if minutes is None or minutes >= 24 * 60:
        return ""
    h, m = divmod(int(minutes), 60)
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def hours_between(first, last, total_gaps) -> Optional[int]:
    """One day's knocking minutes: (last − first) − gaps, or None when the day
    has no usable span (a missing/unparsable time, or a last knock at or
    before the first). None means "leave the cell blank", which is what the
    board has always shown for those reps."""
    f, l = knock_time_key(first), knock_time_key(last)
    if f >= 24 * 60 or l >= 24 * 60 or l <= f:
        return None
    gaps = str(total_gaps or "").strip()
    return max(l - f - (int(gaps) if gaps.isdigit() else 0), 0)


def day_hours(rec: dict) -> Optional[int]:
    """`hours_between` for one scraped record."""
    return hours_between(rec.get(COL_FIRST_KNOCK), rec.get(COL_LAST_KNOCK),
                         rec.get(COL_TOTAL_GAPS))


def daterange(start: dt.date, end: dt.date) -> List[dt.date]:
    """Every day from `start` to `end` inclusive. Empty when end < start —
    callers refuse that in words rather than silently swapping the two."""
    if end < start:
        return []
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _rep_key(rec: dict) -> str:
    """What makes two rows the same rep across days: the badge ID, falling
    back to the name for a source that didn't carry one."""
    rid = str(rec.get(COL_ID, "") or "").strip()
    if rid and rid != "0":
        return f"id:{rid}"
    return "name:" + " ".join(str(rec.get(COL_REP, "") or "").lower().split())


def _as_number(v) -> Optional[float]:
    """The value as a number, or None if it isn't one. Blank is NOT zero here
    — a blank contributes nothing and can't make a text column look numeric."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v if v is not None else "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def aggregate_days(days: Iterable[List[dict]]) -> List[dict]:
    """Fold one list of rows per day into one list of per-rep rows.

    A rep who knocked on 3 of 7 days appears once, with 3 days' counts and an
    Avg. Hrs Knocking averaged over those 3 — not over 7. Rows keep the KEY
    SET they came with (union across the days), so `render.knocks_shape` still
    reads the right board shape off the result.

    Single day in, same rows out — see the module docstring.
    """
    per_day = [rows for rows in days if rows]
    if not per_day:
        return []
    if len(per_day) == 1:
        return list(per_day[0])

    order: List[str] = []
    acc: dict = {}
    for rows in per_day:
        for rec in rows:
            key = _rep_key(rec)
            slot = acc.get(key)
            if slot is None:
                slot = acc[key] = {"ident": {}, "nums": {}, "text": {},
                                   "first": NO_TIME, "last": NO_TIME,
                                   "hours": [], "cols": []}
                order.append(key)
            for col, val in rec.items():
                if col not in slot["cols"]:
                    slot["cols"].append(col)
                if col in _IDENTITY_COLS:
                    if not str(slot["ident"].get(col, "")).strip():
                        slot["ident"][col] = val
                    continue
                if col in _TIME_COLS:
                    t = knock_time_key(val)
                    if t < 24 * 60:
                        if col == COL_FIRST_KNOCK:
                            slot["first"] = min(slot["first"], t)
                        else:
                            slot["last"] = (t if slot["last"] >= 24 * 60
                                            else max(slot["last"], t))
                    continue
                n = _as_number(val)
                if n is None:
                    if not str(slot["text"].get(col, "")).strip():
                        slot["text"][col] = val
                else:
                    slot["nums"][col] = slot["nums"].get(col, 0.0) + n
            h = day_hours(rec)
            if h is not None:
                slot["hours"].append(h)

    # Every rep carries every column any rep had, so shape detection and the
    # renderers see a uniform table even when one day's scrape was narrower.
    all_cols: List[str] = []
    for key in order:
        for col in acc[key]["cols"]:
            if col not in all_cols:
                all_cols.append(col)

    out: List[dict] = []
    for key in order:
        slot = acc[key]
        rec: dict = {}
        for col in all_cols:
            if col in _IDENTITY_COLS:
                rec[col] = slot["ident"].get(col, "")
            elif col == COL_FIRST_KNOCK:
                rec[col] = fmt_time(slot["first"])
            elif col == COL_LAST_KNOCK:
                rec[col] = fmt_time(slot["last"])
            elif col in slot["nums"]:
                total = slot["nums"][col]
                n = int(total) if float(total).is_integer() else total
                rec[col] = "" if (col in _BLANK_ZERO_COLS and not n) else n
            else:
                rec[col] = slot["text"].get(col, "")
        # Precomputed so the board does NOT re-derive it from the folded
        # first/last/gaps — that would be one day's span minus a week's gaps.
        hrs = slot["hours"]
        rec[COL_HRS_KNOCKING] = (str(round(sum(hrs) / len(hrs))) if hrs else "")
        out.append(rec)

    out.sort(key=lambda r: str(r.get(COL_REP, "")).strip().lower())
    return out

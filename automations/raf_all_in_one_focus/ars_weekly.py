"""Weekly office totals out of one owner tab of an ARS REPORT workbook.

Each week in the tab is a box. Its header row has the week label ('11/15', the
Sunday that ENDS the week) in the QUALIFIED RETENTION block's first column, the
row under it has the sub-headers, and one row per interviewer follows until the
next box. Every block ends in a 'TOTAL for the WEEK' group:

    QUALIFIED RETENTION  -> Qualified | Disqualified | Declined | ...Retention
    ANSWERED / BOOKED    -> Qualified | Answered | Booked | Not Contacted | ...

The office total for a week is the sum of those per-interviewer weekly totals
(Owner and ADMIN ROLE rows included: they are interviews the office ran).
Retentions are NOT summed here -- the Focus Report recomputes them with
formulas from the counts.

Everything is found by label: the two blocks by their row-1 banner, the total
group by the 'TOTAL for the WEEK' text, the columns by their sub-header.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

QUALIFIED_BANNER = "qualified retention"
ANSWERED_BANNER = "answered / booked retention"
TOTAL_TEXT = "total for the week"

# sub-header (normalised) -> key in the result
Q_FIELDS = {"qualified": "qualified", "disqualified": "disqualified",
            "declined": "declined"}
A_FIELDS = {"qualified": "ab_qualified", "answered": "answered",
            "booked": "booked", "not contacted": "not_contacted"}

_WEEK = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s*$")


def _norm(s: str) -> str:
    return " ".join(str(s or "").replace("\n", " ").split()).lower()


def _num(s: str) -> Optional[float]:
    t = str(s or "").strip().replace(",", "")
    if not t or t.endswith("%"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _cell(rows: List[List[str]], r: int, c: int) -> str:
    if 0 <= r < len(rows) and 0 <= c < len(rows[r]):
        return rows[r][c] or ""
    return ""


def week_date(label: str, today: dt.date) -> Optional[dt.date]:
    """'11/15' -> the most recent date with that month/day that is not more
    than a week after `today` (the tab carries no year)."""
    m = _WEEK.match(label or "")
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    for year in (today.year + 1, today.year, today.year - 1, today.year - 2):
        try:
            cand = dt.date(year, mo, d)
        except ValueError:
            return None
        if cand <= today + dt.timedelta(days=7):
            return cand
    return None


def _banner_col(row1: List[str], banner: str) -> Optional[int]:
    for j, v in enumerate(row1):
        if _norm(v) == banner:
            return j
    return None


def weekly_totals(rows: List[List[str]], today: dt.date) -> Dict[dt.date, Dict[str, float]]:
    """{week-ending Sunday: {qualified, disqualified, declined, ab_qualified,
    answered, booked, not_contacted}} for every box in the tab.

    `rows` is the tab read from row 1 and column A (formatted values)."""
    if not rows:
        return {}
    q_col = _banner_col(rows[0], QUALIFIED_BANNER)
    a_col = _banner_col(rows[0], ANSWERED_BANNER)
    if q_col is None:
        raise LookupError("no QUALIFIED RETENTION block on row 1")

    starts = []                                   # (row index, week date)
    for i in range(1, len(rows)):
        d = week_date(_cell(rows, i, q_col), today)
        if d:
            starts.append((i, d))

    out: Dict[dt.date, Dict[str, float]] = {}
    for n, (top, wk) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(rows)
        sub = top + 1                             # sub-header row
        totals: Dict[str, float] = {}
        for block_col, fields in ((q_col, Q_FIELDS), (a_col, A_FIELDS)):
            if block_col is None:
                continue
            # the TOTAL group of this block: first 'TOTAL for the WEEK' between
            # the block's first column and the next row-1 banner
            stop = next((j for j in range(block_col + 1, len(rows[0]))
                         if str(rows[0][j]).strip()), len(rows[top]))
            t_col = next((j for j in range(block_col, stop)
                          if _norm(_cell(rows, top, j)) == TOTAL_TEXT), None)
            if t_col is None:
                continue
            cols: Dict[str, int] = {}
            for j in range(t_col, t_col + 10):
                key = fields.get(_norm(_cell(rows, sub, j)))
                if key and key not in cols:
                    cols[key] = j
            for key, j in cols.items():
                vals = [_num(_cell(rows, r, j)) for r in range(sub + 1, end)
                        if _cell(rows, r, block_col).strip()]
                vals = [v for v in vals if v is not None]
                if vals:
                    totals[key] = sum(vals)
        if totals:
            out[wk] = totals
    return out

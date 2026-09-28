"""Week-ending columns on a 1on1 tab — and the two typos already in them.

Every box repeats a header row: col A 'Rep Name?', then one column per week.
The spelling is NOT uniform, because people have typed these by hand for
months:

    'WE 8/02'   'WE 8/23'      the usual form
    'WE  9/4'   Se7en Sins     DOUBLE space, and 9/4/2026 is a FRIDAY
    '09/06'     Hashiras       zero-padded, no 'WE'
    '9/13'      Hashiras       neither
    '08/06'     Template-Fiber AUGUST 6th, sitting AFTER 'WE 8/30'

The last two are the dangerous ones. A parser that believes the text files
'WE  9/4' one week early, and files '08/06' FOUR WEEKS BEHIND where it sits —
straight on top of a column that already holds good numbers.

So a header is only accepted when it lands on a Sunday AND continues the
sequence the columns to its left established. Anything else is returned as a
`Suspect` for a human to look at; it is never guessed into place and never
written to. [[feedback_no_hardcoded_columns]] [[feedback_fill_but_flag]]
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List, Optional

# 'WE 8/02' / 'WE  9/4' / '09/06' / '9/13'  -> (month, day)
_DATE = re.compile(r"^(?:WE\s*)?(\d{1,2})\s*/\s*(\d{1,2})$", re.I)


@dataclass
class Week:
    col: int                 # 1-indexed column on the tab
    raw: str                 # exactly what the cell says
    sunday: Optional[dt.date]
    suspect: str = ""        # why it was not trusted; "" means good

    @property
    def ok(self) -> bool:
        return self.sunday is not None and not self.suspect


def _parse(raw: str, year: int) -> Optional[dt.date]:
    m = _DATE.match(raw.strip())
    if not m:
        return None
    mo, dy = int(m.group(1)), int(m.group(2))
    try:
        return dt.date(year, mo, dy)
    except ValueError:
        return None


def read_header(row: List[str], *, year: int, first_col: int = 3) -> List[Week]:
    """Parse a box's header row into weeks, flagging what does not add up.

    `first_col` is 1-indexed: col A is the section label, col B the metric
    label, so the weeks start at col C.
    """
    out: List[Week] = []
    for j in range(first_col, len(row) + 1):
        raw = (row[j - 1] or "").strip()
        if not raw:
            continue
        d = _parse(raw, year)
        if d is None:
            out.append(Week(j, raw, None, "not a date"))
            continue
        why = ""
        if d.weekday() != 6:                       # 6 = Sunday
            why = f"{d.isoformat()} is a {d.strftime('%A')}, not a Sunday"
        out.append(Week(j, raw, d, why))

    _check_sequence(out)
    return out


def _check_sequence(weeks: List[Week]) -> None:
    """Flag a week that goes BACKWARDS from the one on its left.

    This is what catches '08/06' sitting after 'WE 8/30'. It reads as a valid
    Sunday-ish date on its own; only its position gives it away.
    """
    last: Optional[dt.date] = None
    for w in weeks:
        if w.sunday is None:
            continue
        if last is not None and w.sunday <= last:
            w.suspect = (w.suspect + "; " if w.suspect else "") + \
                f"{w.sunday.isoformat()} is not after {last.isoformat()} on its left"
        else:
            last = w.sunday


def find(weeks: List[Week], sunday: dt.date) -> Optional[Week]:
    """The column for one week-ending, or None. Suspect columns never match."""
    for w in weeks:
        if w.ok and w.sunday == sunday:
            return w
    return None


def sundays_back(latest: dt.date, n: int) -> List[dt.date]:
    """`n` week-ending Sundays, oldest first, ending at `latest`."""
    if latest.weekday() != 6:
        raise ValueError(f"{latest} is not a Sunday")
    return [latest - dt.timedelta(weeks=i) for i in range(n - 1, -1, -1)]

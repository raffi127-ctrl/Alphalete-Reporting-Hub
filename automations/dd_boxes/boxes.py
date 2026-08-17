"""Find and read the Due-Diligence-style rep boxes on the ICD tabs.

Layout (Eve's template, two tabs use it today — Starr Rodenhurst and Kimberly
Rodriguez):

    Reps Names | 8 WK X Average | 4 Week X Average | 0-30 Day Cancel Rate |
    30-60 Day Cancel Rate | 0-30/30/60/90 Day Churn | Start Date | <X> Sales
               |                |                   |  WE 6.07 | 6/14/26 | ...
    <rep>      |    (formula)   |    (formula)      |    2     |    5    | ...
    Total      |                |                   |          |         |
    Per rep AVG|                |                   |          |         |

Everything is located by LABEL, never by index: the header cell can sit in
column B (Kimberly) or column AG (Starr), the metric columns can be before or
after the weekly block, and the Total / Per rep AVG rows are optional. Adding a
box to another tab needs no code change — it's detected on the next run.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# header label -> canonical key. Matched on a normalized form, so casing and
# spacing drift ('30-60 Activation Rate ') doesn't break the lookup.
FIELD_LABELS = {
    "reps names": "name",
    "0-30 day cancel rate": "c030",
    "30-60 day cancel rate": "c3060",
    "0-30 day churn": "churn_0-30",
    "30 day churn": "churn_30",
    "60 day churn": "churn_60",
    "90 day churn": "churn_90",
    "start date or first day of sales": "start",
}
# the label that opens the weekly block also tells us which product it counts
SALES_LABELS = {"new int sales": "ni", "wireless sales": "wl", "total sales": "ts"}
# fallback: the average label carries the same signal
AVG_SIDE = {"new int": "ni", "nl": "wl", "wireless": "wl"}
STOP_ROWS = {"total", "per rep avg", "travel crew average"}


def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def parse_week(v) -> Optional[dt.date]:
    """'WE 6.07' or '6/14/26' or '6/14/2026' -> date. None if it isn't a week."""
    s = norm(v).upper()
    m = re.match(r"^WE\s+(\d{1,2})[.\-/](\d{1,2})$", s)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        # no year in this form — the caller reconciles it against the real
        # week columns; assume the current year and let the caller correct.
        try:
            return dt.date(dt.date.today().year, mm, dd)
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", s)
    if not m:
        return None
    mm, dd, yy = (int(x) for x in m.groups())
    if yy < 100:
        yy += 2000
    try:
        return dt.date(yy, mm, dd)
    except ValueError:
        return None


@dataclass
class Box:
    tab: str
    header_row: int                     # the row carrying 'Reps Names'
    week_row: int                       # the row carrying the WE dates
    side: str                           # 'ni' | 'wl' | 'ts'
    cols: Dict[str, int] = field(default_factory=dict)      # key -> 1-based col
    weeks: Dict[dt.date, int] = field(default_factory=dict)  # date -> 1-based col
    reps: List[tuple] = field(default_factory=list)          # (row, name)
    total_row: Optional[int] = None
    avg_row: Optional[int] = None

    @property
    def week_cols_sorted(self) -> List[int]:
        return [self.weeks[d] for d in sorted(self.weeks)]

    def __str__(self) -> str:
        return (f"{self.tab} r{self.header_row} [{self.side}] "
                f"{len(self.reps)} reps, {len(self.weeks)} week cols")


def _cell(grid, row, col) -> str:
    """1-based lookup into a get_all_values grid; '' when out of range."""
    if 0 < row <= len(grid):
        r = grid[row - 1]
        if 0 < col <= len(r):
            return (r[col - 1] or "").strip()
    return ""


def find_boxes(grid: List[List[str]], tab: str) -> List[Box]:
    """Every DD-style box on one tab, in row order."""
    out = []
    for i, row in enumerate(grid, 1):
        for j, cell in enumerate(row, 1):
            if norm(cell) != "reps names":
                continue
            box = _read_header(grid, tab, i, j)
            if box:
                out.append(box)
    return out


def _read_header(grid, tab, hrow, hcol) -> Optional[Box]:
    cols, side, first_week_col = {"name": hcol}, None, None
    for j in range(hcol, hcol + 60):
        label = norm(_cell(grid, hrow, j))
        if not label:
            continue
        if label in FIELD_LABELS:
            cols[FIELD_LABELS[label]] = j
            continue
        if label in SALES_LABELS:              # opens the weekly block
            side = SALES_LABELS[label]
            first_week_col = j
            continue
        m = re.match(r"^(8 wk|4 week)\s+(.*?)\s*average$", label)
        if m:
            cols["avg8" if m.group(1) == "8 wk" else "avg4"] = j
            if side is None:
                side = AVG_SIDE.get(m.group(2).strip(), None)
    if side is None or first_week_col is None:
        return None

    # week row: the next row down that carries parsable dates
    week_row, weeks = None, {}
    for r in (hrow + 1, hrow + 2):
        found = {}
        for j in range(first_week_col, first_week_col + 60):
            d = parse_week(_cell(grid, r, j))
            if d:
                found[d] = j
        if len(found) >= 2:
            week_row, weeks = r, found
            break
    if not weeks:
        return None

    box = Box(tab=tab, header_row=hrow, week_row=week_row, side=side,
              cols=cols, weeks=weeks)
    # rep rows: from under the week row until a Total / Per rep AVG / blank run
    # Boxes are stacked on the same tab (Tony Chavez has three), so the scan has
    # to stop at the NEXT box, not run into it: bail on another 'Reps Names'
    # header, and on the first real name that shows up AFTER the Total /
    # Per rep AVG rows — those close a box.
    r = week_row + 1
    blanks, seen_stop = 0, False
    while r <= len(grid) + 1 and blanks < 2:
        name = _cell(grid, r, hcol)
        key = norm(name)
        if key == "reps names":
            break
        if key in STOP_ROWS:
            seen_stop = True
            if key == "total":
                box.total_row = r
            else:
                box.avg_row = r
            r += 1
            continue
        if not name:
            blanks += 1
            r += 1
            continue
        if seen_stop:
            break
        blanks = 0
        box.reps.append((r, name))
        r += 1
    return box


def reconcile_week_years(box: Box, real_weeks: List[dt.date]) -> None:
    """'WE 6.07' carries no year. Snap each such column onto the real Sunday
    whose month/day matches, so a box written in the short form still lines up
    (Starr's first three columns use it, the rest are real dates)."""
    by_md = {(d.month, d.day): d for d in real_weeks}
    for d in list(box.weeks):
        if d in real_weeks:
            continue
        real = by_md.get((d.month, d.day))
        if real and real not in box.weeks:
            box.weeks[real] = box.weeks.pop(d)

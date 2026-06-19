"""Google Sheet side of the B2B WE sales board.

Layout (decoded from 'B2B WE 6.21' / 'Copy of B2B WE 6.21'):
  - Row 1: section + weekday labels. Each weekday is a 6-col block starting at a
    3-letter code cell (MON, TUE, …, SUN). Block cols = Apps, B2B NL, B2B INT,
    B2B AIR, B2B VOIP, Roll Call.
  - Row 3: per-block product sub-labels ('B2B NL', 'B2B INT', …) + the week
    range in col B (e.g. '06/15 - 06/21').
  - Reps: col B from row 4 down, with a rank number in col A, until a 'Total' row.

Everything is anchored by LABEL (weekday code in row 1, product label in row 3,
rep name in col B) — never by fixed row/column index
([[feedback_no_hardcoded_columns]]).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

import gspread.utils as _gu

from automations.recruiting_report.fill import open_by_key

SHEET_ID = "1cPOPM0EnAE_rHaIReG1oHpLCZxfPZk725tdzIRBZZGs"

DAY_CODES = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}
_CODESET = set(DAY_CODES.values())
PRODUCT_LABELS = {"nl": "b2b nl", "int": "b2b int", "air": "b2b air", "voip": "b2b voip"}


def open_sheet():
    return open_by_key(SHEET_ID)


def week_ending_sunday(day: dt.date) -> dt.date:
    """The Sunday that ends day's Mon–Sun week (day itself if it's Sunday)."""
    return day + dt.timedelta(days=(6 - day.weekday()))


def expected_tab_name(day: dt.date, prefix: str = "B2B WE") -> str:
    sun = week_ending_sunday(day)
    return f"{prefix} {sun.month}.{sun.day}"


def find_week_tab(sh, day: dt.date, sandbox: bool = False):
    """Return the worksheet for day's week. Production: 'B2B WE <M.D>' (the
    new-week tab Megan creates each week). Sandbox: 'Copy of B2B WE <M.D>'.
    Raises if the expected tab doesn't exist yet."""
    name = expected_tab_name(day)
    if sandbox:
        name = "Copy of " + name
    titles = [w.title for w in sh.worksheets()]
    if name in titles:
        return sh.worksheet(name)
    raise RuntimeError(
        f"Tab {name!r} not found (week ending {week_ending_sunday(day)}). "
        f"Existing B2B tabs: {[t for t in titles if t.startswith(('B2B WE','Copy of B2B WE'))]}. "
        f"The weekly tab is created manually — create it before running.")


def find_rep_rows(values: List[List[str]]) -> List[Tuple[int, str]]:
    """[(1-based row, rep name)] from col B, rows after the header until 'Total'."""
    reps: List[Tuple[int, str]] = []
    started = False
    for i, row in enumerate(values):
        a = (row[0] if len(row) > 0 else "").strip()
        b = (row[1] if len(row) > 1 else "").strip()
        if not started:
            # data starts at the first numbered rep row
            if a.isdigit() and b:
                started = True
            else:
                continue
        if not b:
            continue
        if b.lower() == "total":
            break
        if a.isdigit():
            reps.append((i + 1, b))
    return reps


def day_block_columns(values: List[List[str]], weekday: int) -> Dict[str, int]:
    """{'nl','int','air','voip': 0-based col index} for the weekday's block.
    Anchors on the row-1 weekday code, then the row-3 product labels within the
    block's column span."""
    code = DAY_CODES[weekday]
    row1 = values[0]
    starts = {(v or "").strip().upper(): ci for ci, v in enumerate(row1)
              if (v or "").strip().upper() in _CODESET}
    if code not in starts:
        raise RuntimeError(f"Weekday block {code!r} not found in row 1: "
                           f"{[ (v) for v in row1 if (v or '').strip() ]}")
    start = starts[code]
    later = sorted(c for c in starts.values() if c > start)
    end = later[0] if later else len(values[2])
    row3 = values[2]
    cols: Dict[str, int] = {}
    for ci in range(start, min(end, len(row3))):
        lbl = (row3[ci] or "").strip().lower()
        for key, want in PRODUCT_LABELS.items():
            if lbl == want:
                cols[key] = ci
    missing = [k for k in PRODUCT_LABELS if k not in cols]
    if missing:
        raise RuntimeError(f"Day block {code}: missing product columns {missing} "
                           f"in row 3 span [{start}:{end}].")
    return cols


def week_range_label(values: List[List[str]]) -> str:
    """The 'MM/DD - MM/DD' label in col B row 3 (sanity check)."""
    return (values[2][1] if len(values) > 2 and len(values[2]) > 1 else "").strip()

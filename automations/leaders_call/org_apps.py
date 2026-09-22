"""The org's total app count for the recognized week — the cover-slide stat.

Megan 2026-09-21: "adding total app count from prev week to the leader call
slide for whole org". The deck's title slide now carries ONE number: every app
the whole org wrote in the week being recognized, next to the week before it.

WHERE IT COMES FROM. The same workbook the Leader's Call tab lives in
(All-in-One Local Office) has the 'Alphalete ORG Sales Board' tab, and its
ALPHALETE ORG block keeps one column per week ('WE 09.20', 'WE 09.13', ...)
with an 'ALL TOTALS' row = every campaign section's TOTALS summed (Retail NL,
Fiber, Retail JE, NDS, B2B, BOX, Retail Internet, Frontier — the whole org,
Raf + Carlos + Colten). That row is the org's weekly app count as leadership
already reads it, and it is fed daily by the campaigns' own Tableau/SARA views
(org_sales_board/section_pull), so the deck says the same number the board
does — nothing re-derived here.

Source path, spelled out: workbook 1IpDs2BG… (All-in-One Local Office) →
tab 'Alphalete ORG Sales Board' → block headed 'ALPHALETE ORG' (col A) →
row labelled 'ALL TOTALS' (col A) → column whose header is 'WE m.d' for the
recognized week's Sunday. The week BEFORE is the same row under the previous
Sunday's header.

EVERYTHING BY LABEL. The block is found by its title, the row by its label,
the week by its date header — rollover inserts a new column every week and
the block grows, so no row/column number typed here would survive a month
(feedback_no_hardcoded_columns).

TIMING. The board rolls TUESDAY, so on the Monday-2pm run the recognized
week is still the newest column (live formulas) headed with that Sunday; on a
later --recover / --finalize it is a frozen column further right. Matching
the header by date makes both cases the same lookup.

FAIL-SOFT, BUT LOUD. The deck is projected on the call; a board hiccup must
not cost the recognition. A missing number comes back as None and the cover
simply has no stat — and the caller prints why, so it never goes quietly.

    python -m automations.leaders_call.org_apps                # this week
    python -m automations.leaders_call.org_apps --week 2026-09-13
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List, Optional

# Same workbook as run.LEADERS_CALL_SHEET_ID / org_sales_board.run.SHEET_ID.
# Typed here (not imported) so importing this module never drags in run.py's
# module-level Tableau URL builders and their browser deps.
SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"

ORG_BLOCK_TITLE = "ALPHALETE ORG"
ALL_TOTALS_LABEL = "ALL TOTALS"
_WE_RE = re.compile(r"^\s*WE\s+(\d{1,2})\.(\d{1,2})\s*$", re.I)


@dataclass
class OrgApps:
    week_end: dt.date        # the recognized week's Sunday
    total: int               # ALL TOTALS under that week's header
    prev: Optional[int]      # ALL TOTALS under the previous Sunday, if present

    @property
    def delta(self) -> Optional[int]:
        return None if self.prev is None else self.total - self.prev


def _cell(grid: List[List], r: int, c: int) -> str:
    if r < len(grid) and c < len(grid[r]):
        return str(grid[r][c] if grid[r][c] is not None else "").strip()
    return ""


def _num(s: str) -> Optional[int]:
    s = re.sub(r"[,\s]", "", s or "")
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def _we_md(label: str):
    m = _WE_RE.match(label or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def org_apps_from_grid(grid: List[List], week_end: dt.date) -> OrgApps:
    """Pure lookup over the tab's cell grid (get_all_values shape).
    Raises LookupError with a plain-English reason when a label is missing."""
    hr = next((i for i in range(len(grid))
               if _cell(grid, i, 0).upper().startswith(ORG_BLOCK_TITLE)), None)
    if hr is None:
        raise LookupError(f"no '{ORG_BLOCK_TITLE}' block in column A")
    # ALL TOTALS sits right under the header; scan a few rows, stop at a blank.
    tr = next((r for r in range(hr + 1, min(hr + 6, len(grid)))
               if _cell(grid, r, 0).upper() == ALL_TOTALS_LABEL), None)
    if tr is None:
        raise LookupError(f"no '{ALL_TOTALS_LABEL}' row under '{ORG_BLOCK_TITLE}'")
    header = grid[hr]
    cols = {}
    for c in range(len(header)):
        md = _we_md(_cell(grid, hr, c))
        if md:
            cols.setdefault(md, c)          # first hit wins if a label repeats
    want = (week_end.month, week_end.day)
    if want not in cols:
        have = ", ".join(f"WE {m:02d}.{d:02d}" for m, d in list(cols)[:4])
        raise LookupError(f"no 'WE {want[0]:02d}.{want[1]:02d}' column "
                          f"(newest headers: {have})")
    total = _num(_cell(grid, tr, cols[want]))
    if total is None:
        raise LookupError(f"ALL TOTALS under WE {want[0]:02d}.{want[1]:02d} "
                          f"is {_cell(grid, tr, cols[want])!r}, not a number")
    prev_sun = week_end - dt.timedelta(days=7)
    pc = cols.get((prev_sun.month, prev_sun.day))
    prev = _num(_cell(grid, tr, pc)) if pc is not None else None
    return OrgApps(week_end=week_end, total=total, prev=prev)


def org_total_apps(week_end: dt.date, sheet_id: str = SHEET_ID) -> OrgApps:
    """Read the live board and return the org's apps for `week_end`'s week.
    Raises on any lookup miss — callers decide whether that is fatal."""
    from automations.recruiting_report.fill import open_by_key
    from automations.org_sales_board.tabs import BOARD_TAB
    from automations.org_sales_board.grid import read_grid
    ws = open_by_key(sheet_id).worksheet(BOARD_TAB)
    grid = read_grid(ws, unformatted=False)     # 'WE 09.20' headers as text
    return org_apps_from_grid(grid, week_end)


def cover_lines(oa: OrgApps) -> tuple:
    """(big number, small note) for the cover slide. Note is '' with no prior."""
    big = f"{oa.total:,}"
    if oa.prev is None:
        return big, ""
    d = oa.delta
    sign = "+" if d > 0 else ("" if d < 0 else "±")
    return big, f"{sign}{d:,} vs {oa.prev:,} the week before"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--week", help="week-ending SUNDAY (YYYY-MM-DD); default = "
                    "the just-completed week")
    args = ap.parse_args()
    if args.week:
        sun = dt.date.fromisoformat(args.week)
    else:
        from automations.leaders_call.recognition_tab import week_ending_sunday
        sun = week_ending_sunday()
    try:
        oa = org_total_apps(sun)
    except LookupError as e:
        print(f"⚠ org apps for WE {sun}: {e}")
        return 1
    big, note = cover_lines(oa)
    print(f"WE {sun}: ORG TOTAL APPS {big}  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

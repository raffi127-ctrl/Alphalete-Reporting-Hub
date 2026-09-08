"""Order every box's ICDs by This Week, highest first — Eve, 2026-09-07.

"siempre ordenes a los owners con sus respectivos historicos por columna C de
forma descendente" — so the whole ROW travels: the name, the live week, the
delta, and all seven history columns stay with the person they belong to.

IT MUST BE A SHEETS-NATIVE `sortRange`, NEVER A VALUE-WRITE. Column D is `=F`
and column E is `=Iferror((C-D)/D,0)`; the totals row is `=SUM(...)` down each
column. Reading those rows and writing them back in a new order would store what
they happen to DISPLAY, freezing every one of them on today's number — and
nothing would look wrong afterwards, because a frozen value is the correct value
for the moment it froze. That is exactly how the ORG Sales Board's delta boxes
sat frozen for a week (`org_sales_board/delta_sort.py` carries the story).
`sortRange` makes the SERVER move the cells and re-point the references, which
is the one thing a value-write cannot do.

COLUMN A STAYS PUT. It is the rank gutter (1..N), so the range starts at col B
and the numbers keep their order while the people move underneath them — the
rank ends up meaning "1st by headcount", which is what a sorted box should say.

THE TOTALS ROW IS OUTSIDE THE RANGE. It sits under the roster and must not be
sorted into it; the range ends at the last ICD row.

TIES BREAK BY NAME so the order is stable: two ICDs on the same headcount would
otherwise swap places between runs and show up as a change when nothing changed.

Idempotent — a box already in order sorts to itself.

    python -m automations.org_active_headcount.sort            # dry-run
    python -m automations.org_active_headcount.sort --apply
"""
from __future__ import annotations

import argparse
import sys
from typing import List

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_active_headcount import structure as st

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

NAME_COL = 2      # col B — the ICD, and the tiebreak
KEY_COL = 3       # col C — 'Total this week', what we order on


def plan_sorts(grid: List[List], sheet_id: int) -> List[dict]:
    """One `sortRange` request per box. Pure — no I/O.

    The range runs from col B to the box's LAST week column, derived from its
    own headers rather than typed: a box that gains a reserved history column
    still sorts its whole width, and one that has fewer does not reach past
    itself into a neighbour's cells.
    """
    reqs: List[dict] = []
    for box in st.find_boxes(grid):
        rows = box["rows"]
        if len(rows) < 2:
            continue                       # nothing to order
        cols = [c for c, _ in box["week_cols"]]
        end_col = max(cols) if cols else box["delta_col"]
        reqs.append({"sortRange": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": rows[0][0] - 1,      # 0-based, inclusive
                "endRowIndex": rows[-1][0],           # 0-based, exclusive
                "startColumnIndex": NAME_COL - 1,     # col B; col A stays put
                "endColumnIndex": end_col,            # 0-based exclusive == 1-based col
            },
            # dimensionIndex is an ABSOLUTE sheet column index (0-based), not an
            # offset into the range — the same gotcha every other sorter in this
            # repo carries a comment about.
            "sortSpecs": [
                {"dimensionIndex": KEY_COL - 1, "sortOrder": "DESCENDING"},
                {"dimensionIndex": NAME_COL - 1, "sortOrder": "ASCENDING"},
            ],
        }})
    return reqs


def run(*, apply_changes: bool = False, live_tab: bool = True,
        logfn=print) -> dict:
    tab = st.BOARD_TAB if live_tab else st.SANDBOX_TAB
    sh = open_by_key(st.SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.title.strip() == tab), None)
    if ws is None:
        raise ValueError(f"tab {tab!r} not found in the workbook")
    grid = ws.get_all_values()
    reqs = plan_sorts(grid, ws.id)
    for box, req in zip(st.find_boxes(grid), reqs):
        r = req["sortRange"]["range"]
        logfn(f"  {box['campaign']:32s} rows {r['startRowIndex'] + 1}-"
              f"{r['endRowIndex']} cols B:{st.a1col(r['endColumnIndex'])}")
    if apply_changes and reqs:
        _retry(ws.spreadsheet.batch_update, {"requests": reqs})
    logfn(f"{len(reqs)} box(es) sorted." if apply_changes
          else f"{len(reqs)} box(es) would sort.")
    return {"boxes": len(reqs)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sandbox", action="store_true",
                    help="target the sandbox copy instead of the live tab")
    a = ap.parse_args()
    run(apply_changes=a.apply, live_tab=not a.sandbox)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

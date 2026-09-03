"""Sort every per-rep DELTA box high->low by 'Total this week' (col C).

WHY THIS IS ITS OWN MODULE AND NOT PART OF `sort.py`. That module sorts by
WRITING the rows back in their new order, which is right for a leaderboard (its
history is static) and fatal here: a delta box's cells are live — the per-day
'This week' =SUMIFs, the Delta %, the '=F+I' week total. Writing them back as
literals freezes each row on the number it happened to hold, and NOTHING looks
wrong afterwards: every total still balances, because the frozen values are the
correct values for that moment. It cost a week to spot on 2026-08-25, and
`sort.plan_leaderboard_sorts` has excluded these boxes ever since.

So this uses Sheets-native `sortRange`: the server MOVES the cells and re-points
the formulas, which is the one thing a value-write cannot do.

COL A STAYS PUT. It is the rank chain (1..N, written by `delta_ranks`), so the
sorted range starts at col B and the numbers stay in order while the rows move
underneath them.

Boxes are located with `rollover.find_delta_tables` — the same structural finder
`sort.py` uses to know what to avoid, so the two can never disagree about what
is a delta box.
"""
from __future__ import annotations

from typing import List

from automations.org_sales_board.rollover import find_delta_tables

NAME_COL = 2      # col B — the rep name, and the tiebreak
KEY_COL = 3       # col C — 'Total this week', what we rank on


def plan_delta_sorts(grid: List[List[str]], sheet_id: int) -> List[dict]:
    """One `sortRange` request per delta box. Pure — no I/O.

    A box's last column is the Delta of its last day: `this_cols` holds each
    day's 'This week' column and the triplet puts Delta two to its right, so the
    range ends there. Deriving it beats a constant — a box that ever carries
    fewer days still sorts its whole width and no more.
    """
    reqs: List[dict] = []
    for t in find_delta_tables(grid):
        rows = t["data_rows"]
        if len(rows) < 2:
            continue                      # nothing to order
        end_col = max(t["this_cols"]) + 2 if t["this_cols"] else KEY_COL
        reqs.append({"sortRange": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": rows[0] - 1,        # 0-based, inclusive
                "endRowIndex": rows[-1],             # 0-based, exclusive
                "startColumnIndex": NAME_COL - 1,    # col B; col A stays put
                "endColumnIndex": end_col,
            },
            # dimensionIndex is an ABSOLUTE sheet column index (0-based), not an
            # offset into the range — same gotcha the country/all-campaigns
            # sorters carry.
            "sortSpecs": [
                {"dimensionIndex": KEY_COL - 1, "sortOrder": "DESCENDING"},
                {"dimensionIndex": NAME_COL - 1, "sortOrder": "ASCENDING"},
            ],
        }})
    return reqs


def apply_delta_sort(ws, dry_run: bool = False, logfn=print) -> List[dict]:
    """Sort every delta box on `ws`. Idempotent — a sorted box sorts to itself."""
    reqs = plan_delta_sorts(ws.get_all_values(), ws.id)
    logfn(f"  delta sort: {len(reqs)} box(es)")
    if reqs and not dry_run:
        ws.spreadsheet.batch_update({"requests": reqs})
        logfn(f"  [OK] sorted {len(reqs)} delta box(es)")
    return reqs

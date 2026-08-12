"""Country Sales Board — re-rank the two per-rep tables, every day after the fill.

The tab ships two rep-by-rep tables that both carry a rank column (A = 1..77)
but neither of which ever re-sorted itself, so the ranks drifted into fiction:
row 18 read '1 Chan Park 130' while row 21 read '4 Hasani Lynch 80' — 4th place
ahead of 3rd. Eve 2026-08-12: after the daily fill, both tables sort DESCENDING.

  • the DAILY SALES BREAKDOWN (the 'Fiber - All Units' day block) by col J,
    'RUNNING WEEK TOTALS'
  • the WEEK-TOTAL leaderboard ('AT&T FIBER TEAM') by col C, the live week

Those two keys are the SAME number — the leaderboard's col C is a
`=SUMIF($B$100:$B$176, B18, …)` over the day block's col J — so both tables come
out in the SAME order, which is the point: a rep sits at the same rank wherever
you look at them.

HOW IT SORTS — and the two things it must not disturb:

  1. COLUMN A NEVER MOVES. The rank column is a chain (`A101 = =A100+1`), the
     same shape as the day-number row that drops a day the moment you type over
     it ([[project_board-daynum-chain-frozen-drops-days]]). Leaving col A out of
     the sorted range is also what makes the ranks CORRECT: the rows re-order
     underneath a 1..77 that stays put, so the top row is rank 1 by
     construction. Sorting it along would have carried each rep's old rank with
     them and produced a leaderboard numbered 1, 4, 6, 3…

  2. THE WHOLE ROW TRAVELS WITH THE REP. The leaderboard's history runs to col
     BE (55 frozen weeks) and the day block carries K/L (last week / previous
     week) beside its 7 day cells. The range is measured to the widest
     non-empty column of the block each run, never a constant, so a rollover
     that adds a week column can't shear a rep's history off their name.

Sheets-native `sortRange`: atomic server-side, and it re-points the formulas it
moves (each row's `=SUM(C100,D100,…)` follows its own row, the leaderboard's
`=SUMIF(…,B18,…)` follows its own name). Verified on the sandbox 2026-08-12 —
see the module test in the commit. Nothing here reads the sort key: the server
sorts on the values it already holds, which are the ones the fill just wrote.

Ties break on the NAME (col B, ascending) so the ~15 reps sitting at 0 early in
the week keep a stable alphabetical order instead of shuffling every morning.
"""
from __future__ import annotations

from typing import List, Optional

from automations.org_sales_board.fill_section import find_daily_section
from automations.country_sales_board import rollover as cr
from automations.country_sales_board.fill import BLOCK_LABEL

NAME_COL = 2          # col B — the rep name, in both tables (tiebreaker)
LEADER_WEEK_COL = 3   # col C — the leaderboard's live week


def _widest_col(grid: List[List[str]], rows: List[int], floor: int) -> int:
    """Rightmost column carrying anything across `rows`, never below `floor`."""
    widest = floor
    for r in rows:
        row = grid[r - 1] if r - 1 < len(grid) else []
        for i in range(len(row) - 1, -1, -1):
            if str(row[i]).strip():
                widest = max(widest, i + 1)
                break
    return widest


def plan_sorts(grid: List[List[str]], sheet_id: int,
               col_count: Optional[int] = None) -> List[dict]:
    """Build the sortRange requests for both tables. Pure — no I/O.

    Ranges start at col B: col A is the rank chain and stays where it is
    (see the module docstring)."""
    reqs: List[dict] = []

    def block(first_row: int, last_row: int, key_col: int, end_col: int,
              tag: str) -> dict:
        if col_count:
            end_col = min(end_col, col_count)
        return {"sortRange": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": first_row - 1,      # 0-indexed, inclusive
                "endRowIndex": last_row,             # 0-indexed, exclusive
                "startColumnIndex": NAME_COL - 1,    # col B — col A stays put
                "endColumnIndex": end_col,
            },
            # dimensionIndex is an ABSOLUTE sheet column index (0-based), not an
            # offset into the range — verified on the sandbox 2026-08-12 by
            # sorting on col J with the range starting at col B.
            "sortSpecs": [
                {"dimensionIndex": key_col - 1, "sortOrder": "DESCENDING"},
                {"dimensionIndex": NAME_COL - 1, "sortOrder": "ASCENDING"},
            ],
        }, "_tag": tag}

    # --- the daily breakdown: by RUNNING WEEK TOTALS (col J) ---
    anchor = find_daily_section(grid, BLOCK_LABEL)
    day_rows = sorted(anchor.icd_rows.values())
    reqs.append(block(
        day_rows[0], day_rows[-1], anchor.running_total_col,
        _widest_col(grid, day_rows, anchor.running_total_col + 2),
        f"day block ({len(day_rows)} reps, rows {day_rows[0]}-{day_rows[-1]}, "
        f"key col {anchor.running_total_col})"))

    # --- the week-total leaderboard: by the live week (col C) ---
    lb = cr.find_leaderboard(grid)
    lb_rows = lb["data_rows"]
    reqs.append(block(
        lb_rows[0], lb_rows[-1], LEADER_WEEK_COL,
        _widest_col(grid, lb_rows, lb["last_col"]),
        f"leaderboard ({len(lb_rows)} reps, rows {lb_rows[0]}-{lb_rows[-1]}, "
        f"key col {LEADER_WEEK_COL})"))
    return reqs


def sort_board(ws, grid: List[List[str]], *, dry_run: bool = False,
               logfn=print) -> int:
    """Sort both rep tables descending. Returns the number of ranges sorted."""
    reqs = plan_sorts(grid, ws.id, col_count=ws.col_count)
    for r in reqs:
        rng = r["sortRange"]["range"]
        logfn(f"  sort {'(dry-run) ' if dry_run else ''}"
              f"{r['_tag']} desc, ties by name — cols "
              f"{rng['startColumnIndex'] + 1}..{rng['endColumnIndex']}")
    if dry_run:
        return len(reqs)
    ws.spreadsheet.batch_update(
        {"requests": [{"sortRange": r["sortRange"]} for r in reqs]})
    return len(reqs)


def main() -> int:
    """Sort the board on its own, without re-pulling Tableau — for the day the
    fill ran before this step existed, or a repair after a hand edit."""
    import argparse
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.country_sales_board.run import (
        SHEET_ID, PROD_TAB, SANDBOX_TAB)

    ap = argparse.ArgumentParser(description="Re-rank the Country Sales Board")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--real", action="store_true",
                    help=f"Target {PROD_TAB!r} instead of the sandbox tab.")
    ap.add_argument("--i-mean-it", action="store_true",
                    help="Required alongside --real (writing the live tab).")
    args = ap.parse_args()
    if args.real and not args.i_mean_it:
        print(f"refusing to write {PROD_TAB!r} without --i-mean-it.")
        return 2
    tab = PROD_TAB if args.real else SANDBOX_TAB
    print(f"=== Country Sales Board sort — {tab!r} — "
          f"{'DRY-RUN' if args.dry_run else 'LIVE'} ===")
    ws = open_by_key(SHEET_ID).worksheet(tab)
    sort_board(ws, _retry(ws.get_all_values), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

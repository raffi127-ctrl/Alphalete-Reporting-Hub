"""All Campaigns Org Sales Board — re-rank the three per-rep tables after the fill.

The same defect, and the same fix, as the Country Sales Board got on 2026-08-12
(`country_sales_board/sort_board.py`). This tab ships two rep-by-rep tables that
both carry a rank column (A = 1..39) and neither ever re-sorted itself, so the
ranks drifted into fiction. Measured on the live tab 2026-08-13, right after a
clean fill — rows 18-29 of the leaderboard read:

    1 Jairo 201 · 2 Colten 161 · 3 Atef 155 · 4 Rafael 120 · 5 Aya 56 ·
    6 Frank 57 · 7 Joseph 78 · 8 Drew 105 · 9 George 53 · 10 Roshan 80 …

— 8th place ahead of 5th. The ORG board's own tab has sorted itself since
2026-06-04 (`org_sales_board/sort.py`), so the Org Board Email went out every
morning with a correctly ranked first section and an unranked second one; this
tab is where `screenshot_email.capture_all_units` renders that second section
LIVE, so what is on this tab is what the approvers and the org see.

  * the DAILY section ('All Units', header row ~60) by col J,
    'RUNNING WEEK TOTALS'
  * the WEEKLY leaderboard ('AT&T FIBER TEAM' + WE-date columns, header row ~16)
    by col C, the live week
  * the DELTA BOX ('All Units - All Campaigns', header row ~114) by col C,
    'Total this week' — added 2026-08-17 (Eve), the third table and the one the
    email's 4th block renders

All three keys are the SAME number — the leaderboard's col C is a
`=SUMIF($B$62:$B$99, B18, $J$62:$J$99)` over the day block's col J, and the
delta box's col C is `=F115+I115+…` over its own per-day `=SUMIF`s of that same
col — so all three tables come out in the SAME order, which is the point: a rep
sits at the same rank wherever you look at them.

WHY NOT REUSE org_sales_board.sort. That module rewrites col A with literal
ranks. On the ORG tab that is right; here col A is a CHAIN (`A19 = =A18+1`,
`A63 = =A62+1`) and overwriting it with literals would break the same way the
day-number row breaks when you type over it
([[project_board-daynum-chain-frozen-drops-days]]). So this follows the Country
board's shape instead — see the two rules below.

HOW IT SORTS — the two things it must not disturb:

  1. COLUMN A NEVER MOVES. Leaving the rank chain out of the sorted range is
     also what makes the ranks CORRECT: the rows re-order underneath a 1..39
     that stays put, so the top row is rank 1 by construction. Sorting col A
     along would have carried each rep's old rank with them.

  2. THE WHOLE ROW TRAVELS WITH THE REP. The leaderboard's WE history runs to
     the right of col C and the day block carries K/L (last week / previous
     week) beside its 7 day cells. The range is measured to the widest
     non-empty column of the block each run, never a constant, so a rollover
     that adds a week column can't shear a rep's history off their name.

Sheets-native `sortRange`: atomic server-side, and it re-points the formulas it
moves (each row's `=SUM(C62:I62)` follows its own row, the leaderboard's
`=SUMIF(…,B18,…)` follows its own name). The TOTALS rows (57 and 101) sit
OUTSIDE both ranges — they terminate the row scans, they are not members of
them — so their `=SUM` over the block is untouched.

Ties break on the NAME (col B, ascending) so the reps sitting at 0 early in the
week keep a stable alphabetical order instead of shuffling every morning.
"""
from __future__ import annotations

from typing import List, Optional

from automations.org_sales_board import fill_section as fs
from automations.all_campaigns_board import rollover as acr

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
            # offset into the range (verified on the Country board 2026-08-12).
            "sortSpecs": [
                {"dimensionIndex": key_col - 1, "sortOrder": "DESCENDING"},
                {"dimensionIndex": NAME_COL - 1, "sortOrder": "ASCENDING"},
            ],
        }, "_tag": tag}

    # --- the daily section: by RUNNING WEEK TOTALS (col J) ---
    # find_daily_section keys on the weekday header row, so the col-A label
    # 'All Units' on the LEADERBOARD's sub-header (row 17) can't be mistaken for
    # this one — that row has no Monday..Sunday headers under it.
    anchor = fs.find_daily_section(grid, "All Units")
    day_rows = sorted(anchor.icd_rows.values())
    if day_rows:
        reqs.append(block(
            day_rows[0], day_rows[-1], anchor.running_total_col,
            # floor = running total + 2 => K and L (last / previous week) always
            # travel with the rep even on a week where nobody has history yet.
            _widest_col(grid, day_rows, anchor.running_total_col + 2),
            f"day block ({len(day_rows)} reps, rows {day_rows[0]}-{day_rows[-1]}, "
            f"key col {anchor.running_total_col})"))

    # --- the week-total leaderboard: by the live week (col C) ---
    lb = acr.find_leaderboard_block(grid)
    lb_rows = lb["data_rows"]
    if lb_rows:
        reqs.append(block(
            lb_rows[0], lb_rows[-1], LEADER_WEEK_COL,
            _widest_col(grid, lb_rows, lb["last_col"]),
            f"leaderboard ({len(lb_rows)} reps, rows {lb_rows[0]}-{lb_rows[-1]}, "
            f"key col {LEADER_WEEK_COL})"))

    # --- the DELTA BOX: by 'Total this week' (col C), descending (Eve 2026-08-17) ---
    # The third rep table on this tab, and the one the email's 4th block shows.
    # It was never sorted: its rows sit in whatever order roster.sync added
    # people, so the chart read 361, 334, 301, 256, 135, 151, 197 … — 5th place
    # below 7th, right next to two blocks that ARE ranked. Same key as the other
    # two (col C), so all three tables come out in the same order and a rep sits
    # at the same rank wherever you look at them.
    #
    # Safe to sortRange for the same reason the other two are, plus one specific
    # to this box: its per-rep cells are '=SUMIF($B$62:$B$100,"Jairo Ruiz",…)',
    # keyed on a LITERAL NAME, so the formula travels with its own rep. The
    # row-local arithmetic ('=F115+I115+…', '=iferror((C115-D115)/D115,0)') is
    # re-pointed by sortRange to the row it lands on, and the frozen 'Last week'
    # values are plain numbers that move with the row. Nothing in the box refers
    # to another rep's row, which is what would make a sort unsafe.
    #
    # The TOTALS row is excluded by construction: find_delta_tables stops at the
    # first row with no name in col B, and that is exactly what the totals row
    # looks like ([[project_org-board-leaderboard-totals-row]]).
    tables = acr.find_delta_tables(grid)
    if tables and tables[0]["data_rows"]:
        d_rows = tables[0]["data_rows"]
        # Floor = the LAST triplet's Delta column (this_col + 2), so a rep's
        # Sunday numbers can never be sheared off their name. Measured each run,
        # never a constant — a rollover that re-shapes the triplets is followed.
        floor = max(tables[0]["this_cols"], default=LEADER_WEEK_COL) + 2
        reqs.append(block(
            d_rows[0], d_rows[-1], LEADER_WEEK_COL,
            _widest_col(grid, d_rows, floor),
            f"delta box ({len(d_rows)} reps, rows {d_rows[0]}-{d_rows[-1]}, "
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


def main(argv=None) -> int:
    """Sort the board on its own, without re-running the fill — for the day the
    fill ran before this step existed, or a repair after a hand edit."""
    import argparse
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.all_campaigns_board.run import (
        SHEET_ID, TARGET_TAB, _find_ws)

    ap = argparse.ArgumentParser(
        description="Re-rank the All Campaigns Org Sales Board's two rep tables")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the ranges it would sort and write nothing")
    ap.add_argument("--target-tab", default=TARGET_TAB)
    args = ap.parse_args(argv)

    print(f"=== All Campaigns board sort — {args.target_tab!r} — "
          f"{'DRY-RUN' if args.dry_run else 'LIVE'} ===")
    ws = _find_ws(open_by_key(SHEET_ID), args.target_tab)
    n = sort_board(ws, _retry(ws.get_all_values), dry_run=args.dry_run)
    print(f"=== {n} range(s) {'planned' if args.dry_run else 'sorted'} ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

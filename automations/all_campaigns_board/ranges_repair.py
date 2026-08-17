"""All Campaigns Org Sales Board — keep every aggregate covering every rep.

THE BUG (Eve 2026-08-13). The tab's three rep tables all grew to 39 people, but
the formulas that aggregate over them still stopped at the 38th row. Measured on
the live tab:

    C57   = =SUM(C18:C55)              leaderboard TOTALS — data runs to row 56
    C101  = =SUM(C62:C99)   … J101     day-block Totals   — data runs to row 100
    C18   = =SUMIF($B$62:$B$99, B18, $J$62:$J$99)         leaderboard, 38 of 39
    F115  = =SUMIF($B$62:$B$99, "Jairo Ruiz", $C$62:$C$99)   delta box, 38 of 39

So the last rep on the board was outside EVERY total, and — because the delta
box keys on a hard-coded name — also outside their own delta row. It cost
nothing the day it was found only because the sort had just put the smallest
rep in that row (Ronald Dawson, 0 units). It was a live undercount waiting for
anyone with sales to land last, and it silently gets worse every time
roster.sync adds a person: the rows grow, the ranges don't.

THE FIX IS A RULE, NOT A PATCH. Rewriting 99 -> 100 once would break again on
the 40th rep. Instead, every run re-derives the two blocks' real bounds and
rewrites any range ANCHORED AT A BLOCK'S FIRST DATA ROW so it ends at that
block's LAST data row. That covers all four families above with one rule, and
it is idempotent: a tab already correct produces zero writes.

WHAT IT WILL NOT TOUCH:
  * ranges that don't start at a block's first data row — the frozen WE-history
    rows (102+), the delta box's own row-local arithmetic (=F115+I115+…), the
    Current-vs-Prior box.
  * anything outside a formula. Static values are never rewritten.
  * the block bounds themselves. This only widens/narrows what a formula spans;
    it never moves a row, a name or a number.

The day block's first data row is `header + 2` (header, day-number row, then
reps) and the leaderboard's is `header + 2` as well (header with the WE dates,
then the 'All Units' sub-label). Both come from the same finders the fill and
the sort use, so a moved block is followed, not hard-coded.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from automations.org_sales_board import fill_section as fs
from automations.all_campaigns_board import rollover as acr

# One A1 range inside a formula: $B$62:$B$99, C18:C55, J62:J99 …
_RANGE = re.compile(r'(\$?)([A-Z]{1,2})(\$?)(\d+):(\$?)([A-Z]{1,2})(\$?)(\d+)')

# How far past a block's last data row a range may already reach and still be
# treated as "spanning this block" rather than something else that merely starts
# there. Two rows covers a Totals row someone included on purpose; beyond that we
# leave the formula alone rather than guess.
_SLACK = 2


def _a1(c: int) -> str:
    s = ""
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def block_bounds(grid: List[List[str]]) -> Dict[str, Tuple[int, int]]:
    """{'day': …, 'leaderboard': …, 'delta': …} — 1-based first/last data rows."""
    out: Dict[str, Tuple[int, int]] = {}
    anchor = fs.find_daily_section(grid, "All Units")
    rows = sorted(anchor.icd_rows.values())
    if rows:
        out["day"] = (rows[0], rows[-1])
    lb = acr.find_leaderboard_block(grid)
    if lb["data_rows"]:
        out["leaderboard"] = (lb["data_rows"][0], lb["data_rows"][-1])
    # THE DELTA BOX IS A BLOCK TOO (Eve 2026-08-17). It was missing here, and
    # that left exactly one family of short ranges un-widened: its OWN totals
    # row. The box's per-rep cells key on the DAY block ('=SUMIF($B$62:$B$100,
    # "Jairo Ruiz", $C$62:$C$100)'), so they were already covered by 'day' and
    # looked fine — but the totals row aggregates the box over ITSELF
    # ('=sum(F115:F152)'), anchored at the box's own first data row, which
    # belonged to no known block and so matched no rule.
    #
    # What that cost, measured on the live tab 2026-08-17: the leaderboard and
    # the day block both totalled 4050 while the delta chart's totals row read
    # 4020 — the 39th rep (Alex Nicholas, 30 units) summed into every other
    # total but not his own box's. Two blocks agreeing and a third disagreeing
    # is the worst shape for this: it reads like a real discrepancy in the data.
    # Same failure the module was written for, one block over.
    tables = acr.find_delta_tables(grid)
    if tables and tables[0]["data_rows"]:
        rows = tables[0]["data_rows"]
        out["delta"] = (rows[0], rows[-1])
    return out


def fix_formula(f: str, bounds: Dict[str, Tuple[int, int]]) -> str:
    """Rewrite every range anchored at a block's first data row to end at that
    block's last data row. Returns the formula unchanged when nothing applies."""
    if not f.startswith("="):
        return f

    def sub(m: re.Match) -> str:
        d1, c1, r1d, r1, d2, c2, r2d, r2 = m.groups()
        start, end = int(r1), int(r2)
        for first, last in bounds.values():
            if start == first and last - _SLACK <= end <= last + _SLACK and end != last:
                return f"{d1}{c1}{r1d}{start}:{d2}{c2}{r2d}{last}"
        return m.group(0)

    return _RANGE.sub(sub, f)


def plan(fgrid: List[List[str]], bounds: Dict[str, Tuple[int, int]]) -> List[dict]:
    """[{range, values}] for every cell whose formula needs widening. Pure."""
    updates: List[dict] = []
    for r, row in enumerate(fgrid, start=1):
        for c, val in enumerate(row, start=1):
            f = str(val)
            if not f.startswith("="):
                continue
            fixed = fix_formula(f, bounds)
            if fixed != f:
                updates.append({"range": f"{_a1(c)}{r}", "values": [[fixed]]})
    return updates


def repair(ws, *, dry_run: bool = False, logfn=print,
           fgrid: Optional[List[List[str]]] = None,
           grid: Optional[List[List[str]]] = None) -> int:
    """Widen every short aggregate on the tab. Returns the number of cells fixed."""
    from automations.recruiting_report.fill import _retry
    if grid is None:
        grid = _retry(ws.get_all_values)
    bounds = block_bounds(grid)
    if not bounds:
        logfn("  ranges: no blocks found — nothing to repair")
        return 0
    if fgrid is None:
        last_col = _a1(ws.col_count)
        fgrid = _retry(lambda: ws.get(f"A1:{last_col}{len(grid)}",
                                      value_render_option="FORMULA"))
    updates = plan(fgrid, bounds)
    desc = ", ".join(f"{k} {v[0]}-{v[1]}" for k, v in sorted(bounds.items()))
    if not updates:
        logfn(f"  ranges: OK — every aggregate already spans {desc}")
        return 0
    logfn(f"  ranges: {len(updates)} short aggregate(s) vs {desc}")
    for u in updates[:8]:
        logfn(f"    {u['range']}: -> {u['values'][0][0][:78]}")
    if len(updates) > 8:
        logfn(f"    (+{len(updates) - 8} more)")
    if not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logfn(f"  [OK] widened {len(updates)} formula(s)")
    return len(updates)


def main(argv=None) -> int:
    """Run the repair on its own — for a tab that drifted before this existed."""
    import argparse
    from automations.recruiting_report.fill import open_by_key
    from automations.all_campaigns_board.run import (
        SHEET_ID, TARGET_TAB, _find_ws)

    ap = argparse.ArgumentParser(
        description="Widen the All Campaigns board's aggregates to cover every rep")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the cells it would rewrite and write nothing")
    ap.add_argument("--target-tab", default=TARGET_TAB)
    args = ap.parse_args(argv)

    print(f"=== All Campaigns board range repair — {args.target_tab!r} — "
          f"{'DRY-RUN' if args.dry_run else 'LIVE'} ===")
    ws = _find_ws(open_by_key(SHEET_ID), args.target_tab)
    n = repair(ws, dry_run=args.dry_run)
    print(f"=== {n} formula(s) {'to widen' if args.dry_run else 'widened'} ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

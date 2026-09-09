"""Repair the `#REF!` criteria in the Teams block of a Sales Board tab.

WHAT IS BROKEN. Seventeen cells on every week's tab hold
`=SUMIFS($AN:$AN, $CI:$CI, #REF!)` -- the SUM range and the criteria range are
fine, only the CRITERION is gone. Somebody once deleted the cell those formulas
pointed at (the team name) and the roll has carried the wreck forward ever
since. SUMIFS with a `#REF!` criterion does not raise: it quietly returns **0**,
so the cells look like real zeros and nothing ever complained.

Found on 2026-09-09 while comparing the WE 9.13 sandbox against its live tab --
both had the same 17, which is what proved it was inherited and not something
the Talk-To work had done.

HOW IT IS FIXED. Never by typing a criterion in: the repair takes the NEAREST
HEALTHY `SUMIFS` to the left in the SAME ROW and swaps its column letter, the
same move the rest of this package uses. That formula already knows which team
the row is (`$C158`) and which column holds the team names, so the repaired cell
inherits both and cannot disagree with its neighbours.

A cell is only touched when a model is found in its own row. No model, no write.

    python -m automations.alphalete_sales_board.ref_repair                  # preview
    python -m automations.alphalete_sales_board.ref_repair --apply
    python -m automations.alphalete_sales_board.ref_repair --tab "Sales Board WE 9.13"
"""
from __future__ import annotations

import argparse
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.alphalete_sales_board.talk_to_columns import (
    PROD_SHEET_ID, SANDBOX_TAB, _cell, _col_letter, swap_col)

BROKEN = "#REF!"

# A model has to be a SUMIFS whose criterion is a plain cell in the name column
# -- that is what makes it the same KIND of sum as the broken cell beside it.
HEALTHY = re.compile(r"^=SUMIFS\(.+,\s*\$?[A-Z]{1,3}:\$?[A-Z]{1,3}\s*,"
                     r"\s*\$?[A-Z]{1,3}\$?\d+\s*\)$", re.I)
# The column a formula sums, so `swap_col` knows what to rewrite.
SUM_COL = re.compile(r"^=SUMIFS\(\s*\$?([A-Z]{1,3})\s*:", re.I)


def _index(letter: str) -> int:
    n = 0
    for ch in letter.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def plan_repairs(grid) -> list:
    """[(row, col, broken, fixed)] -- one per cell we can rebuild."""
    out = []
    for r in range(1, len(grid) + 1):
        row = grid[r - 1]
        broken = [c for c in range(1, len(row) + 1)
                  if BROKEN in _cell(grid, r, c)]
        if not broken:
            continue
        for c in broken:
            model_col = model = None
            for left in range(c - 1, 0, -1):          # nearest healthy, leftward
                f = _cell(grid, r, left)
                if BROKEN in f or not HEALTHY.match(f):
                    continue
                m = SUM_COL.match(f)
                if m and _index(m.group(1)) == left:   # it sums its OWN column
                    model_col, model = left, f
                    break
            if not model:
                out.append((r, c, _cell(grid, r, c), None))
                continue
            out.append((r, c, _cell(grid, r, c), swap_col(model, model_col, c)))
    return out


PRIOR_WEEK = "PRIOR WEEK'S TOTALS"
LAST_WEEK = "LAST WEEK'S TOTALS"
TOTALS_SUM = re.compile(
    r"^=SUM\(\$?([A-Z]{1,3})\$?(\d+)\s*:\s*\$?([A-Z]{1,3})\$?(\d+)\)$", re.I)


def plan_prior_range(grid) -> list:
    """[(row, col, broken, fixed)] for PRIOR WEEK'S TOTALS cells that sum the
    WRONG ROWS.

    Every block's totals cell spans the whole Teams list. PRIOR WEEK'S says
    `$X$161:$X$171` where the rest say `$X$158:$X$172`, so it skips the first
    three teams and the last row -- it read 60 where Se7en Sins alone had 113.
    It was invisible until the `#REF!` cells above were repaired, because the
    whole block sat at zero.

    THE RULE IS NAMED, NOT VOTED ON. The span comes from LAST WEEK'S TOTALS in
    the same row -- the block right beside it, the same shape, one week apart.
    A first attempt picked the span by majority and got it backwards on the
    sandbox, proposing to rewrite the HEALTHY cells into the broken range; a
    repair that can eat good formulas is worse than the bug (2026-09-09).
    """
    from automations.alphalete_sales_board.talk_to_columns import _labelled_block
    prior = _labelled_block(grid, PRIOR_WEEK)
    last = _labelled_block(grid, LAST_WEEK)
    if not prior[0] or not last[0]:
        return []
    want = None
    for r in range(1, len(grid) + 1):
        for c in range(last[0], last[1] + 1):
            m = TOTALS_SUM.match(_cell(grid, r, c))
            if m and _index(m.group(1)) == c:
                want = (r, int(m.group(2)), int(m.group(4)))
                break
        if want:
            break
    if not want:
        return []
    row, lo, hi = want
    out = []
    for c in range(prior[0], prior[1] + 1):
        f = _cell(grid, row, c)
        m = TOTALS_SUM.match(f)
        if not m or _index(m.group(1)) != c:
            continue
        if (int(m.group(2)), int(m.group(4))) == (lo, hi):
            continue
        col = _col_letter(c)
        out.append((row, c, f, "=SUM($%s$%d:$%s$%d)" % (col, lo, col, hi)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--current-week", action="store_true",
                    help="repair THIS week's live tab -- what the Monday run "
                         "uses, so the repair follows the roll instead of "
                         "naming a tab that goes stale every seven days")
    ap.add_argument("--sheet-id", default=PROD_SHEET_ID)
    ap.add_argument("--prior-range", action="store_true",
                    help="also give PRIOR WEEK'S TOTALS the span LAST WEEK'S uses")
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default is a preview)")
    a = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key
    ss = open_by_key(a.sheet_id)
    if a.current_week:
        import datetime as dt
        from automations.alphalete_sales_board import fill as F
        ws = F.open_tab(dt.date.today())
        a.tab = ws.title
    else:
        ws = ss.worksheet(a.tab)
    grid = ws.get("A1:%s%d" % (_col_letter(ws.col_count), ws.row_count),
                  value_render_option="FORMULA")
    vals = ws.get("A1:%s%d" % (_col_letter(ws.col_count), ws.row_count),
                  value_render_option="FORMATTED_VALUE")

    repairs = plan_repairs(grid)
    if a.prior_range:
        repairs += plan_prior_range(grid)
    if not repairs:
        print("%r: ninguna celda con %s." % (a.tab, BROKEN))
        return 0
    ok = [x for x in repairs if x[3]]
    print("%r: %d celda(s) con %s, %d reparable(s)"
          % (a.tab, len(repairs), BROKEN, len(ok)))
    for r, c, bad, fixed in repairs:
        who = _cell(vals, r, 3) or ""
        now = _cell(vals, r, c)
        print("  %s%-4d %-20s %-42s -> %s"
              % (_col_letter(c), r, who[:20], bad[:42],
                 (fixed[:46] if fixed else "SIN MODELO EN LA FILA -- se deja")))
        if fixed:
            print("       hoy muestra %r" % now)
    if not a.apply:
        print("\npreview only -- re-run with --apply to write.")
        return 0
    ws.batch_update([{"range": "%s%d" % (_col_letter(c), r),
                      "values": [[fixed]]} for r, c, _b, fixed in ok],
                    value_input_option="USER_ENTERED")
    print("\nreparadas %d celda(s) en %r." % (len(ok), a.tab))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

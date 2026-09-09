"""Audit every Talk-To cell on a Sales Board tab and name what is wrong.

WHY A SWEEP AND NOT A LOOK. These columns are written by five different passes
across four kinds of block (the seven day blocks, RUNNING WEEK, LAST WEEK,
PRIOR WEEK, and the Teams cuadro that repeats all of them), and every fix so far
was found by somebody spotting a gap in a screenshot. That is not a way to know
a tab is right. This walks all of it and reports by CATEGORY, so the answer is
"14 cells, all the same cause" instead of "there is a hole around row 45".

WHAT COUNTS AS WRONG (Eve's rule for the weekly blocks, 2026-09-09):

  * BLANK on a row that has a rep -- no cell of a real person may be empty.
    `-` when nothing can be worked out, a number when it can, `0` when the
    number really is 0. A blank reads as a broken report.
  * An ERROR value (`#REF!`, `#DIV/0!`, ...) anywhere.
  * A DASH that is not earned: the inputs are there and the number could have
    been worked out.

The DAY blocks play by a different rule and are checked against it: a day with
neither knocks nor Talk-To's is BLANK on purpose, because a grid of dashes
across six blocks buries the days that do carry numbers.

    python -m automations.alphalete_sales_board.talk_to_audit
    python -m automations.alphalete_sales_board.talk_to_audit --tab "..."
"""
from __future__ import annotations

import argparse
import collections
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.alphalete_sales_board.talk_to_columns import (
    ANCHOR, PAST_BLOCKS, PROD_SHEET_ID, SANDBOX_TAB, TRIO, WEEK_BLOCK,
    WEEK_HEADERS, _cell, _col_letter, _labelled_block, day_blocks, sub_col)

ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NUM!", "#ERROR!")
DASH = "-"


def audit(grid, totals_row: int, name_col: int, team_rows) -> list:
    """[(kind, row, col, block, header, value)] -- one per cell worth a look."""
    out = []
    # A row with NO NAME is not a data row, in the roster or in the Teams
    # cuadro: the board keeps filler rows in both, their cells are blank on
    # purpose, and counting them made this report cry over 44 empty slots.
    rows = [r for r in range(4, totals_row + 1)
            if _cell(grid, r, name_col) or r == totals_row]
    rows += [r for r in team_rows if _cell(grid, r, name_col)]

    def look(block, headers, cols_of, weekly: bool, knocks_col=None):
        """`weekly` blocks answer to Eve's rule: no knocks -> the row is EMPTY,
        knocks but no derivable value -> '-', a real zero -> 0. So a blank is
        only wrong on a row that HAS knocks, and a '-' is only wrong on a row
        that has none."""
        for h in headers:
            c = cols_of(h)
            if not c:
                out.append(("FALTA LA COLUMNA", 0, 0, block, h, ""))
                continue
            for r in rows:
                v = _cell(grid, r, c)
                if any(e in v for e in ERRORS):
                    out.append(("ERROR", r, c, block, h, v))
                    continue
                if not weekly or not knocks_col:
                    continue
                try:
                    knocks = float(_cell(grid, r, knocks_col) or 0)
                except ValueError:
                    knocks = 0
                if knocks and not v:
                    out.append(("VACIA CON KNOCKS", r, c, block, h, v))
                elif not knocks and v:
                    out.append(("SIN KNOCKS PERO CON DATO", r, c, block, h, v))
    # the weekly blocks, where a blank is never right
    for label, headers in ([(WEEK_BLOCK, WEEK_HEADERS)]
                           + [(b, WEEK_HEADERS) for b in PAST_BLOCKS]):
        b = _labelled_block(grid, label)
        if not b[0]:
            out.append(("FALTA EL BLOQUE", 0, 0, label, "", ""))
            continue
        kc = next((sub_col(grid, b, k) for k in ("TK", "EN")
                   if sub_col(grid, b, k)), None)
        look(label, headers, lambda h, b=b: sub_col(grid, b, h), True, kc)
    # the day blocks, where a day with nothing is blank ON PURPOSE
    for lab, b in sorted(day_blocks(grid).items(), key=lambda kv: kv[1][0]):
        tk = sub_col(grid, b, ANCHOR)
        tt = sub_col(grid, b, TRIO[0])
        look(lab, TRIO, lambda h, b=b: sub_col(grid, b, h), False)
        if not (tk and tt):
            continue
        for r in rows:                 # a number needs the day to have data
            for h in TRIO[1:]:
                c = sub_col(grid, b, h)
                v = _cell(grid, r, c) if c else ""
                if v and v != DASH and not _cell(grid, r, tk) \
                        and not _cell(grid, r, tt):
                    out.append(("DIA SIN DATO PERO CON NUMERO", r, c, lab, h, v))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--sheet-id", default=PROD_SHEET_ID)
    ap.add_argument("--all", action="store_true", help="listar cada celda")
    a = ap.parse_args(argv)

    from automations.energy_slack_fill.run import last_rep_row, name_col
    from automations.recruiting_report.fill import open_by_key
    ss = open_by_key(a.sheet_id)
    ws = ss.worksheet(a.tab)
    grid = ws.get("A1:%s%d" % (_col_letter(ws.col_count), ws.row_count),
                  value_render_option="FORMATTED_VALUE")
    forms = ws.get("A1:%s%d" % (_col_letter(ws.col_count), ws.row_count),
                   value_render_option="FORMULA")
    totals = last_rep_row(grid) + 1
    nc = name_col(grid)
    wk = _labelled_block(grid, WEEK_BLOCK)
    int_c = sub_col(grid, wk, "INT") if wk[0] else None
    # The Teams cuadro only: a row whose INT cell is a FORMULA. Below it the tab
    # keeps ~60 rows of week-by-week history that carry numbers in the same
    # column -- reading those as team rows made the first run of this report
    # 1227 "empty" cells, nearly all of them a history row that never had a
    # Talk-To cell to begin with.
    team_rows = [r for r in range(totals + 2, len(forms) + 1)
                 if int_c and _cell(forms, r, int_c).startswith("=")]

    found = audit(grid, totals, nc, team_rows)
    print("%r: %d celda(s) para revisar" % (a.tab, len(found)))
    by = collections.Counter((k, blk, h) for k, _r, _c, blk, h, _v in found)
    for (kind, blk, h), n in sorted(by.items(), key=lambda x: -x[1]):
        print("  %-28s %-22s %-26s %d" % (kind, blk[:22], h[:26], n))
    if a.all:
        for kind, r, c, blk, h, v in found:
            print("   %-28s %s%-4d %-22s %-24s %r"
                  % (kind, _col_letter(c), r, blk[:22], h[:24], v))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())

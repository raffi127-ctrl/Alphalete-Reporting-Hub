"""Keep the 'Lanes' tab pointed at the right two weeks of the Sales Board.

WHAT THE TAB IS (Rafael 2026-09-23, formulas by Maud 2026-09-24). Two blocks,
'Current Week' and 'Last week', five lanes each (Super Saiyan 10+, Fast 8+,
Cruise 6+, Grandma 4+, Exit 0-3). Each lane is ONE FILTER formula in the row
under the lane headers; everything below it spills on its own:

    =iferror(FILTER('Sales Board WE 9.27'!C4:C87, 'Sales Board WE 9.27'!D4:D87>=10),"")

WHAT THIS DOES, and nothing else. Rewrites the tab name and the LAST row inside
those ten formulas so that
  * Current Week reads this week's 'Sales Board WE <m>.<d>' tab,
  * Last week reads the week before,
  * both end on the row right above that tab's 'TOTALS' row in col C.
Maud's conditions are never rebuilt -- only the tab name and the end row are
substituted, so a change she makes to a lane survives the roll.

WHY IT RUNS ALL WEEK, not just Monday. Monday: Eve builds the new Sales Board
tab by hand between ~6:00 and 7:30 CT, so there is no fixed minute to flip at;
the job simply flips on the first tick after the tab exists. Rest of the week:
a rep added in a row inserted right above TOTALS lands OUTSIDE C4:C87 (Sheets
only grows a range for rows inserted inside it) and would vanish from every
lane. Every tick re-reads where TOTALS is and fixes the end row. When nothing
moved -- almost every tick -- it writes nothing.

Same tab every week (Maud + Rafael 2026-09-24: "re-writing on the same tab").

    python -m automations.alphalete_sales_board.lanes            # preview
    python -m automations.alphalete_sales_board.lanes --apply    # write
    python -m automations.alphalete_sales_board.lanes --date 2026-09-15  # preview another week
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

from automations.alphalete_sales_board import config as C
from automations.alphalete_sales_board import fill

TAB = "Lanes"
TOTALS_LABEL = "totals"
CURRENT_LABEL = "current week"
LAST_LABEL = "last week"

# 'Sales Board WE 9.27'!C4:C87 -- the tab name, then a plain A1 range.
REF_RE = re.compile(r"'(%s [^']*)'!(\$?[A-Z]+\$?)(\d+):(\$?[A-Z]+\$?)(\d+)"
                    % re.escape(fill.TAB_PREFIX))


def _log(msg: str) -> None:
    print("[lanes %s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg),
          flush=True)


def _col_letter(idx0: int) -> str:
    s, n = "", idx0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def find_blocks(grid: List[List[str]]) -> Tuple[int, Dict[str, List[int]]]:
    """(formula_row0, {'current': [cols0], 'last': [cols0]}) read off the labels.

    The 'Current Week' / 'Last week' banner sits one row above the lane headers;
    the formulas sit one row below them. A block's columns are the lane headers
    from its banner column rightwards until the first blank header.
    """
    for r, row in enumerate(grid):
        low = [c.strip().lower() for c in row]
        if CURRENT_LABEL in low and LAST_LABEL in low:
            heads = grid[r + 1] if r + 1 < len(grid) else []
            blocks = {}
            for key, label in (("current", CURRENT_LABEL), ("last", LAST_LABEL)):
                c = low.index(label)
                cols = []
                while c < len(heads) and heads[c].strip():
                    cols.append(c)
                    c += 1
                blocks[key] = cols
            return r + 2, blocks
    raise RuntimeError("no 'Current Week' / 'Last week' banner on the %r tab"
                       % TAB)


def totals_row(col_c: List[str]) -> Optional[int]:
    """1-based row of 'TOTALS' in col C, or None."""
    for i, v in enumerate(col_c):
        if v.strip().lower() == TOTALS_LABEL:
            return i + 1
    return None


def repoint(formula: str, tab: str, end_row: int) -> str:
    """The same formula, reading `tab` down to `end_row`. Raises if it has no
    Sales Board reference to repoint (someone replaced the formula)."""
    if not REF_RE.search(formula):
        raise ValueError("no 'Sales Board WE …'!range in %r" % formula)
    return REF_RE.sub(
        lambda m: "'%s'!%s%s:%s%d" % (tab, m.group(2), m.group(3),
                                      m.group(4), end_row),
        formula)


def plan(lanes_formulas: List[List[str]], lanes_values: List[List[str]],
         targets: Dict[str, Tuple[str, int]]) -> List[Dict]:
    """Cell updates that bring every lane formula onto `targets`.

    targets = {'current': (tab, end_row), 'last': (tab, end_row)}.
    """
    row0, blocks = find_blocks(lanes_values)
    frow = lanes_formulas[row0] if row0 < len(lanes_formulas) else []
    updates = []
    for key, cols in blocks.items():
        tab, end = targets[key]
        for c in cols:
            old = frow[c] if c < len(frow) else ""
            if not str(old).startswith("="):
                raise RuntimeError("%s%d has no formula (%r) -- not guessing one"
                                   % (_col_letter(c), row0 + 1, old))
            new = repoint(str(old), tab, end)
            if new != old:
                updates.append({"range": "%s%d" % (_col_letter(c), row0 + 1),
                                "values": [[new]], "old": old})
    return updates


def _find_ws(book_ws, title: str):
    want = title.strip().lower()
    for ws in book_ws:
        if ws.title.strip().lower() == want:
            return ws
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the formulas")
    ap.add_argument("--dry-run", action="store_true", help="preview (default)")
    ap.add_argument("--date", help="YYYY-MM-DD, which week is 'current' "
                                   "(default today)")
    args = ap.parse_args(argv)
    apply_writes = args.apply and not args.dry_run
    day = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
           if args.date else dt.date.today())

    from automations.recruiting_report.fill import _client
    book = _client().open_by_key(C.SPREADSHEET_ID)
    worksheets = book.worksheets()

    lanes = _find_ws(worksheets, TAB)
    if lanes is None:
        _log("no %r tab on the sales board -- nothing to do" % TAB)
        return 2

    cur_title = fill.tab_title(day)
    last_title = fill.tab_title(day - dt.timedelta(days=7))
    targets = {}
    for key, title in (("current", cur_title), ("last", last_title)):
        ws = _find_ws(worksheets, title)
        if ws is None:
            # Monday before Eve has built the new tab: leave the lanes alone,
            # the next tick flips them once it exists.
            _log("%r not there yet -- waiting, nothing written" % title)
            return 0
        end = totals_row(ws.col_values(3))
        if end is None:
            _log("no TOTALS row in col C of %r -- not guessing, nothing written"
                 % ws.title)
            return 2
        targets[key] = (ws.title, end - 1)
        _log("%-7s -> %r rows to %d" % (key, ws.title, end - 1))

    values = lanes.get_all_values()
    formulas = lanes.get("A1:Z%d" % max(len(values), 1),
                         value_render_option="FORMULA")
    try:
        updates = plan(formulas, values, targets)
    except (RuntimeError, ValueError) as e:
        _log("REFUSED: %s" % e)
        return 2

    if not updates:
        _log("lanes already on the right weeks -- nothing to change")
        return 0
    for u in updates:
        _log("%s  %s\n        -> %s" % (u["range"], u["old"], u["values"][0][0]))
    if not apply_writes:
        _log("PREVIEW -- %d cell(s) would change (pass --apply)" % len(updates))
        return 0
    lanes.batch_update([{"range": u["range"], "values": u["values"]}
                        for u in updates], value_input_option="USER_ENTERED")
    _log("wrote %d lane formula(s)" % len(updates))
    return 0


if __name__ == "__main__":
    sys.exit(main())

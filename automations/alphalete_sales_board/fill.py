"""Write the day's four columns onto this week's Sales Board tab.

TARGET, spelled out:
  workbook  'Alphalete SALES BOARD 2025' (1MC9pf…N2CmHc)
  tab       'Sales Board WE <m>.<d>'  -- the week's SUNDAY
  row       the rep's row in col C
  cols      TODAY's block -> Int | Int Up | DTV | NL

Geometry comes from rep_sales_fill.board, which reads the day banners and
sub-headers live on every run. Nothing here remembers a row or a column: the
board is re-sorted through the day (alphabetical in the morning, by production
later) and columns are inserted all week. [[feedback_no_hardcoded_columns]]

FOUR THINGS IT WILL NOT DO, and they are the whole safety story for a job that
writes 150 times a day unattended:
  * never touch Apps (a formula) or Roll Call;
  * never overwrite a roll-call status ('X', 'T', 'RT', 'STF' …) -- those share
    the same cells as the counts, so a write would erase the attendance record;
  * never blank a cell that holds a number. A sale that reached the board is
    evidence; an empty grid cell is not evidence of its absence, and a short
    SaraPlus export is a normal event;
  * never write a day that is not today. Yesterday is closed and belongs to
    rep_sales_fill, which fills it once from Tableau.

Writes go out as ONE batch_update. A per-cell loop across 60 reps would burn
the Sheets write quota inside a minute and 429 the next report to touch the
workbook, not just this one. [[reference_sheets_write_quota_429]]
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

from automations.alphalete_sales_board import config as C
from automations.rep_sales_fill import board as B

TAB_PREFIX = "Sales Board WE"


def tab_title(day: dt.date) -> str:
    sunday = C.week_ending(day)
    return "%s %d.%d" % (TAB_PREFIX, sunday.month, sunday.day)


def open_tab(day: dt.date, client=None):
    """This week's worksheet, or a clear error naming the tab we looked for."""
    from automations.recruiting_report.fill import _client
    gc = client or _client()
    book = gc.open_by_key(C.SPREADSHEET_ID)
    want = tab_title(day).lower()
    for ws in book.worksheets():
        if ws.title.strip().lower() == want:
            return ws
    raise RuntimeError(
        "no %r tab on the sales board -- the week's tab is usually rolled over "
        "on Sunday. Nothing was written." % tab_title(day))


def board_names(grid) -> List[str]:
    """Col C, roster block only (down to TOTALS)."""
    last = B.last_rep_row(grid)
    out = []
    for r in range(B.SUB_ROW + 1, last + 1):
        name = B.cell(grid, r, B.NAME_COL).strip()
        if name:
            out.append(name)
    return out


def _a1(row: int, col: int) -> str:
    letters = ""
    c = col
    while c > 0:
        c, rem = divmod(c - 1, 26)
        letters = chr(65 + rem) + letters
    return "%s%d" % (letters, row)


def plan(grid, day: dt.date, rows: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """([{range, values}], notes) for TODAY's block only.

    overwrite=True on purpose: this is the live day, and the count grows all
    afternoon, so today's cells are meant to track SaraPlus. plan_day still
    refuses a day carrying a roll-call status and still refuses to blank a
    number, which is where the actual protection lives -- not in the flag.
    """
    # day_blocks() keys are full weekday names ("Monday"), which is what it
    # maps the board's own banners ("MON", "TUES") onto.
    weekday = day.strftime("%A")
    blocks = B.day_blocks(grid)
    cols = blocks.get(weekday)
    if not cols:
        return [], ["no %s block on %r -- the tab's day banners may have "
                    "changed" % (weekday, tab_title(day))]

    updates, notes = [], []
    for item in rows:
        row, note = B.find_rep_row(grid, item["board_name"])
        if row is None:
            notes.append(note)
            continue
        writes, day_notes = B.plan_day(grid, row, cols, item["metrics"],
                                       overwrite=True)
        notes.extend("%s: %s" % (item["board_name"], n) for n in day_notes)
        for _metric, col, _cur, new in writes:
            updates.append({"range": _a1(row, col), "values": [[new]]})
    return updates, notes


def apply(worksheet, updates: List[Dict]) -> int:
    """One batch write. Returns the number of cells changed."""
    if not updates:
        return 0
    worksheet.batch_update(updates, value_input_option="USER_ENTERED")
    return len(updates)

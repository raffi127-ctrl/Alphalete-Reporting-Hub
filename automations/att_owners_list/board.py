"""Give a new ATT owner their row in all THREE Country Sales Board boxes.

Someone who shows up in the ATT program has to appear on the board the country
reads, or their sales land nowhere: the daily fill is SHEET-DRIVEN (it walks the
tab's rows and looks each one up in the pull), so an owner with no row is simply
skipped — silently, every morning. Modelled on all_campaigns_board.roster, which
solved the same problem for the campaigns board.

THE THREE BOXES (all located by label, never by row number):

  1. weekly leaderboard   col-A 'AT&T FIBER TEAM' + 'WE …' headers
       A =A{above}+1 · B name · C =SUMIF(daily B, B{r}, daily J) · D.. frozen
  2. daily sales breakdown  col-A 'Fiber - All Units' + 'RUNNING WEEK TOTALS'
       A =A{above}+1 · B name · C..I days · J =SUM(C..I) · K/L last two weeks
  3. delta units chart    col-C header 'Total this week'
       B name · C/D/E totals · then a This week/Last week/Delta triplet per day,
       where every 'This week' cell is a SUMIF that names the person AS A
       LITERAL STRING — which is why the row is copied from a neighbour and
       then has that literal swapped, rather than written from scratch.

WHERE THE ROW GOES — and why not at the bottom. Boxes 1 and 2 are ranked by
production, so the bottom is where a rep starting at 0 belongs. But this tab's
aggregates read the blocks through FIXED ranges (=SUMIF($B$99:$B$174,…),
=SUM(C99:C174), =sum(F235:F311)), and Google grows such a range only when a row
is inserted INSIDE it — never when one is appended past the end. A row appended
at the bottom therefore gets filled and counted toward NOTHING (country_sales_
board.fill.audit_aggregate_coverage exists to catch exactly that). So every
insert goes AT the last data row, pushing that row down: inside the range, one
line off the bottom, and the next sort puts them where their numbers say.

Box 3 is ALPHABETICAL, so its row goes in alphabetical position — clamped to the
last data row for the same reason. A name that sorts after the current last one
lands one row early; that is logged, not silently corrected.

Frozen history is left BLANK, never copied from the neighbour: inheriting it
would invent sales that never happened (and it is how the tab already shows a
recent joiner — Blue Mendoza's pre-join weeks are blank, not 0).
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from automations.org_sales_board import fill_section as fs
from automations.org_sales_board import rollover as org_ro
from automations.country_sales_board import rollover as cr
from automations.country_sales_board.fill import BLOCK_LABEL

from automations.att_owners_list.sheet import candidates, name_key


def _cell(grid, r0: int, c0: int) -> str:
    if r0 < 0 or r0 >= len(grid):
        return ""
    row = grid[r0]
    return str(row[c0]).strip() if c0 < len(row) else ""


def board_names(grid) -> Dict[str, str]:
    """{normalized key: the board's spelling} across all three boxes."""
    out: Dict[str, str] = {}
    lb = cr.find_leaderboard(grid)
    for r in lb["data_rows"]:
        n = _cell(grid, r - 1, 1)
        if n:
            out[name_key(n)] = n
    for n in fs.find_daily_section(grid, BLOCK_LABEL).icd_rows:
        out[name_key(n)] = n
    for t in org_ro.find_delta_tables(grid):
        for r in t["data_rows"]:
            n = _cell(grid, r - 1, 1)
            if n:
                out[name_key(n)] = n
    return out


def board_spelling(name: str) -> str:
    """Tableau's shouted 'ANDRE’ BURTON JR.' → the board's 'Andre’ Burton Jr.'.

    Two things have to hold at once and only Title Case does both: the column
    is Title Case ("Chan Park", "D'Mari Longmire"), and the daily fill matches
    board rows to the pull through a LOWERCASED comparison that does NOT
    normalize apostrophes — so the curly ’ Tableau uses must survive verbatim or
    the row never matches and sits at 0 forever. `str.title()` lowercases the
    tail and leaves every apostrophe alone, which is exactly right here."""
    return (name or "").strip().title()


def missing(grid, names: List[str], *, aliases: Optional[dict] = None) -> List[str]:
    """Which of `names` have no row on the board (alias-aware)."""
    have = set(board_names(grid))
    return [n for n in names if not (candidates(n, aliases) & have)]


def _insert_row(ws, row: int, *, inherit: bool = True) -> None:
    ws.spreadsheet.batch_update({"requests": [{"insertDimension": {
        "range": {"sheetId": ws.id, "dimension": "ROWS",
                  "startIndex": row - 1, "endIndex": row},
        "inheritFromBefore": inherit}}]})


def _copy_row(ws, src: int, dst: int, c0: int, c1: int) -> None:
    """Copy src's [c0, c1) columns onto dst so Sheets rewrites every relative
    reference for the new position."""
    ws.spreadsheet.batch_update({"requests": [{"copyPaste": {
        "source": {"sheetId": ws.id, "startRowIndex": src - 1, "endRowIndex": src,
                   "startColumnIndex": c0, "endColumnIndex": c1},
        "destination": {"sheetId": ws.id, "startRowIndex": dst - 1,
                        "endRowIndex": dst, "startColumnIndex": c0,
                        "endColumnIndex": c1},
        "pasteType": "PASTE_NORMAL"}}]})


def _rank_repair(ws, at: int, *, first_row: int, last_row: int) -> List[dict]:
    """Col-A rank cells for the inserted row AND the row under it.

    The blocks number themselves with '=A{above}+1'. An insert does not
    re-point the row that used to sit there — its formula still names the cell
    ABOVE the insert, which did not move — so the number repeats and everything
    below is one short. Rewriting the NEXT row's formula re-links the chain."""
    out = [{"range": f"{ws.title}!A{at}",
            "values": [[1 if at == first_row else f"=A{at - 1}+1"]]}]
    if at + 1 <= last_row:
        out.append({"range": f"{ws.title}!A{at + 1}", "values": [[f"=A{at}+1"]]})
    return out


def _alpha_at(grid, rows: List[int], name: str) -> int:
    """Alphabetical insert position inside a block, clamped to the last data
    row so the block's fixed ranges still grow (see the module docstring)."""
    for r in rows:
        if name.upper() < _cell(grid, r - 1, 1).upper():
            return r
    return rows[-1]


def add_one(ws, name: str, *, logfn=print) -> dict:
    """Add ONE person to all three boxes, lowest box first.

    The grid is re-read before each box rather than adjusting row numbers
    arithmetically: box 3 sits below box 2 and box 2 below box 1, so every
    insert moves the boxes under it."""
    done: dict = {}

    # ---- 3. delta units chart (lowest — do it first) --------------------
    grid = ws.get_all_values()
    tables = org_ro.find_delta_tables(grid)
    if not tables:
        raise ValueError("delta units chart not found (no 'Total this week' "
                         "header in col C)")
    t = tables[0]
    rows = t["data_rows"]
    at = _alpha_at(grid, rows, name)
    if at == rows[-1] and name.upper() > _cell(grid, rows[-1] - 1, 1).upper():
        logfn(f"    note: {name} sorts after {_cell(grid, rows[-1] - 1, 1)!r}; "
              f"inserted one row EARLY so the chart's =sum() ranges still grow")
    # The template row: the one above the insert when there is one (it does not
    # move), otherwise the row being pushed down (which lands at at+1).
    if at - 1 >= rows[0]:
        src, src_after = at - 1, at - 1
    else:
        src, src_after = at, at + 1
    old = _cell(grid, src - 1, 1)
    last_col = max(t["this_cols"]) + 2
    _insert_row(ws, at)
    time.sleep(1)
    _copy_row(ws, src_after, at, 1, last_col)
    time.sleep(1)
    frm = ws.get_all_values(value_render_option="FORMULA")
    data = [{"range": f"{ws.title}!B{at}", "values": [[name]]}]
    row_f = frm[at - 1] if at - 1 < len(frm) else []
    for c0, val in enumerate(row_f[:last_col]):
        v = str(val)
        if c0 == 1 or not v:
            continue
        if v.startswith("="):
            if old and old in v:                     # the literal SUMIF name
                data.append({"range": f"{ws.title}!{fs._col(c0 + 1)}{at}",
                             "values": [[v.replace(old, name)]]})
        else:                                        # frozen last-week number
            data.append({"range": f"{ws.title}!{fs._col(c0 + 1)}{at}",
                         "values": [[0]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": data})
    done["delta_row"] = at
    logfn(f"    delta units chart: row {at} (copied from row {src}, "
          f"{len(data) - 1} cell(s) re-pointed at {name})")

    # ---- 2. daily sales breakdown ---------------------------------------
    grid = ws.get_all_values()
    daily = fs.find_daily_section(grid, BLOCK_LABEL)
    rows = sorted(daily.icd_rows.values())
    at = rows[-1]
    src = rows[-2] if len(rows) > 1 else at + 1     # post-insert row number
    _insert_row(ws, at)
    time.sleep(1)
    _copy_row(ws, src, at, 0, daily.running_total_col)
    time.sleep(1)
    day_cols = sorted(daily.day_col_by_daynum.values())
    data = [{"range": f"{ws.title}!B{at}", "values": [[name]]},
            {"range": f"{ws.title}!{fs._col(daily.running_total_col)}{at}",
             "values": [[f"=SUM({fs._col(day_cols[0])}{at}:"
                         f"{fs._col(day_cols[-1])}{at})"]]}]
    data += _rank_repair(ws, at, first_row=rows[0], last_row=daily.totals_row)
    for c in day_cols:
        data.append({"range": f"{ws.title}!{fs._col(c)}{at}", "values": [[0]]})
    for c in (daily.running_total_col + 1, daily.running_total_col + 2):
        data.append({"range": f"{ws.title}!{fs._col(c)}{at}", "values": [[""]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": data})
    done["daily_row"] = at
    logfn(f"    daily breakdown: row {at} (0 per day, J re-summed, K/L blank)")

    # ---- 1. weekly leaderboard ------------------------------------------
    grid = ws.get_all_values()
    lb = cr.find_leaderboard(grid)
    rows = lb["data_rows"]
    at = rows[-1]
    src = rows[-2] if len(rows) > 1 else at + 1     # post-insert row number
    _insert_row(ws, at)
    time.sleep(1)
    _copy_row(ws, src, at, 0, lb["last_col"])
    time.sleep(1)
    grid = ws.get_all_values()
    daily = fs.find_daily_section(grid, BLOCK_LABEL)
    drows = sorted(daily.icd_rows.values())
    jcol = fs._col(daily.running_total_col)
    data = [{"range": f"{ws.title}!B{at}", "values": [[name]]},
            {"range": f"{ws.title}!C{at}",
             "values": [[f"=SUMIF($B${drows[0]}:$B${drows[-1]},B{at},"
                         f"${jcol}${drows[0]}:${jcol}${drows[-1]})"]]}]
    data += _rank_repair(ws, at, first_row=rows[0], last_row=lb["totals_row"])
    for c in range(4, lb["last_col"] + 1):          # frozen history — blank
        data.append({"range": f"{ws.title}!{fs._col(c)}{at}", "values": [[""]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": data})
    done["weekly_row"] = at
    logfn(f"    weekly leaderboard: row {at} (C re-pointed at the daily block, "
          f"history blank)")
    return done


def sync(ws, names: List[str], *, aliases: Optional[dict] = None,
         dry_run: bool = True, logfn=print) -> dict:
    """Add every name that has no row yet. Never removes anyone."""
    grid = ws.get_all_values()
    todo = missing(grid, names, aliases=aliases)
    already = [n for n in names if n not in todo]
    if already:
        logfn(f"  board: already on it — {', '.join(already)}")
    if not todo:
        logfn("  board: every new owner already has a row on all three boxes")
        return {"added": [], "already": already, "dry_run": dry_run}
    logfn(f"  board: {len(todo)} owner(s) with NO row: {', '.join(todo)}")
    if dry_run:
        return {"added": [], "would_add": [board_spelling(n) for n in todo],
                "already": already, "dry_run": True}
    added = []
    for n in todo:
        spelled = board_spelling(n)
        logfn(f"  + adding {spelled!r} to all three boxes "
              f"(Tableau spells it {n!r})")
        add_one(ws, spelled, logfn=logfn)
        added.append(spelled)
    return {"added": added, "already": already, "dry_run": False}

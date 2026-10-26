"""Next week's tabs on our own Sales Board, made by Lucy every Monday (Eve
2026-10-26, Loom of her hand roll: "refresh de alphalete sales board todos los
lunes después de que lucy llena y postea la sales board del domingo").

Runs in the 4am batch right after `alphalete_production` posted Sunday's board.
It copies 'Sales Board WE <last Sunday>' to 'Sales Board WE <this Sunday>' and
does on the COPY what Eve did by hand:

  * WEEKLY HISTORY (rows under the board stats, grouped, newest visible): the
    week that just closed goes on top -- its TOTALS row as values, labelled with
    its dates 'WE 10/19 - 10/25'; the older rows stay in the collapsed group.
  * LAST WEEK'S TOTALS = the old RUNNING WEEK TOTALS, PRIOR = the old LAST
    (values; the running ones are formulas and start again by themselves).
  * Terminated reps are deleted: 'T' in the Sunday Apps cell, or 'Terminated'
    on their row of the New Starts box.
  * Field Status one week further, and the name with it (Eve: "queremos
    mantener trackeado solo a los que son week 2 y 3"):
        1st Wk -> 2nd Wk, name + ' (Wk 2)', Leadership 'In Training' -> 'Entry Level'
        2nd Wk -> 3rd Wk, '(Wk 2)' -> '(Wk 3)'
        3rd Wk -> 4th Wk, '(Wk 3)' comes off
        4th Wk -> 5th wk+
  * every typed day cell (Int .. Cx, Roll Call) goes blank -- formulas stay,
    "se completa con fórmula" -- and the reps are sorted A-Z, Extra rows last.
  * the New Starts box is emptied ("ya están transferidos"). First every name
    in it is checked against the board: one missing is DM'd to Eve, not added.
  * row 2 day numbers and the C3 'WE m/d - m/d' label move to the new week.

Then 'Line Up WE <this Sunday>' is copied from last week's: the names list
(B45) reads the new tab down to the row above TOTALS, the New Starts / OFF /
O-NA / Terminated lists go blank, and a car-ride name that changed (Wk 2/3)
is renamed so it doesn't get the red triangle (car-ride columns only; the
blue Is Training box stays as it was). Stations' formulas are pointed
at the new Line Up. Lanes rolls by itself on Tuesday (lanes.py).

Nothing on last week's tabs is touched. This week's tab already there =
nothing to do (Eve made 11.1 by hand on 10/26); last week's missing = refuse
and DM Eve. Writes only with --apply.

    python -m automations.alphalete_sales_board.week_roll                   # preview
    python -m automations.alphalete_sales_board.week_roll --apply
    python -m automations.alphalete_sales_board.week_roll --sheet <sandbox id> --today 2026-10-26 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.alphalete_sales_board import config as C
from automations.sales_board_fixer import checks as K

BOARD_PREFIX = "Sales Board WE"
LINEUP_PREFIX = "Line Up WE"
STATIONS = "Stations"
DATED = re.compile(r"^\s*(Sales Board|Line Up) WE\s+(\d{1,2})\.(\d{1,2})\s*$", re.I)

RUNNING, LAST, PRIOR = "RUNNING WEEK TOTALS", "LAST WEEK'S TOTALS", "PRIOR WEEK'S TOTALS"
FIELD_STATUS = "FIELD STATUS"
LEADERSHIP = "LEADERSHIP STATUS"
WEEK_N = re.compile(r"^\s*([1-5])(?:st|nd|rd|th)\s+wk\+?\s*$", re.I)
WK_TAG = re.compile(r"\s*\(\s*Wk\s*\d\s*\)\s*$", re.I)
WE_LABEL = re.compile(r"^\s*WE\s*\d", re.I)
NEW_STARTS = "NEW STARTS"            # 'New Starts/Raf'
TERMINATED = "TERMINATED"
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
# the Line Up lists that start the week empty (Roadtrips is the office's)
LINEUP_CLEAR = {"NEW STARTS", "OFF", "O-NA", "TERMINATED"}
LINEUP_NAMES = "REP NAMES FROM"


def tab_title(prefix: str, sunday: dt.date) -> str:
    return "%s %d.%d" % (prefix, sunday.month, sunday.day)


def find_tab(titles, prefix: str, sunday: dt.date) -> Optional[str]:
    """The tab of that week: 'Line Up WE 11.01' counts as 11.1 too."""
    for t in titles:
        m = DATED.match(t)
        if m and m.group(1).lower() == prefix.split(" WE")[0].lower() \
                and (int(m.group(2)), int(m.group(3))) == (sunday.month, sunday.day):
            return t
    return None


def _norm(s) -> str:
    return " ".join(str(s or "").split()).upper()


def _cell(grid, r: int, c: int):
    return grid[r - 1][c - 1] if 0 < r <= len(grid) and 0 < c <= len(grid[r - 1]) else ""


def _typed(formulas, r: int, c: int) -> bool:
    return not str(_cell(formulas, r, c)).startswith("=")


def _col_of(row, label: str) -> int:
    return next((i + 1 for i, x in enumerate(row) if _norm(x) == label), 0)


def _label_cols(row, label: str) -> List[int]:
    """1-based columns under a banner like LAST WEEK'S TOTALS: from it up to
    the next filled cell of the banner row."""
    start = _col_of(row, label)
    if not start:
        return []
    end = next((i for i in range(start, len(row)) if str(row[i]).strip()), len(row))
    return list(range(start, end + 1))


def base_name(name: str) -> str:
    return WK_TAG.sub("", str(name)).strip()


def next_status(status: str, spelled: Dict[int, str]) -> Optional[Tuple[int, str]]:
    """'1st Wk' -> (1, '2nd Wk'). The board's own spelling wins ('5th wk+')."""
    m = WEEK_N.match(str(status))
    if not m or int(m.group(1)) >= 5:
        return None
    n = int(m.group(1))
    return n, spelled.get(n + 1) or ("%s Wk%s" % (ORDINAL[n + 1], "+" if n + 1 == 5 else ""))


def next_name(name: str, old_week: int) -> str:
    """Only weeks 2 and 3 carry the tag: 'Ana' (1st) -> 'Ana (Wk 2)' ->
    'Ana (Wk 3)' -> 'Ana'."""
    bare = base_name(name)
    if old_week == 1:
        return bare + " (Wk 2)"
    if old_week == 2:
        return bare + " (Wk 3)"
    if old_week == 3:
        return bare
    return name


def week_label(monday: dt.date) -> str:
    sun = monday + dt.timedelta(days=6)
    return "WE %d/%d - %d/%d" % (monday.month, monday.day, sun.month, sun.day)


def day_columns(values) -> List[Tuple[int, int, int]]:
    """[(apps col, first col, last col)] of each day block, Monday..Sunday.
    A block runs to the column before the next day's Apps (Thursday's Roll
    Call has no header); Sunday's ends at its Roll Call."""
    blocks = K.day_blocks(values)
    starts = sorted(cols["apps"] for cols in blocks.values() if "apps" in cols)
    out = []
    for i, a in enumerate(starts):
        if i + 1 < len(starts):
            end = starts[i + 1] - 1
        else:
            sun = next(cols for cols in blocks.values() if cols.get("apps") == a)
            end = sun.get("roll call") or max(c for h, c in sun.items()
                                              if h in ("cx", "avg app per tt", "tk"))
        out.append((a, a + 1, end))
    return out


def new_starts_box(values, start: int) -> Tuple[int, int, int]:
    """(title row, first data row, last data row) of the 'New Starts/Raf'
    box under the board, 0s when there is none."""
    title = next((r for r in range(start, len(values) + 1)
                  if _norm(_cell(values, r, 3)).startswith(NEW_STARTS)), 0)
    if not title:
        return 0, 0, 0
    first = title + 1
    while first <= len(values) and (_norm(_cell(values, first, 3)) == "CLASSROOM"
                                    or "ROLL CALL" in {_norm(x) for x in values[first - 1]}):
        first += 1
    return title, first, len(values)


def plan(values, formulas, raw, monday: dt.date) -> Dict[str, object]:
    """Everything the copy needs, read off LAST week's tab (values/formulas/raw
    = formatted / FORMULA / UNFORMATTED_VALUE). Row numbers are the old tab's."""
    lay = K.layout(values)
    nc = lay.name_col
    first, last = K.block_rows(values)
    tot = last + 1
    banner = values[lay.day_row - 1]
    cells: Dict[str, object] = {}

    # New Starts box: who was terminated there, who never reached the board
    ns_title, ns_first, ns_last = new_starts_box(values, tot)
    ns_term, ns_names = set(), []
    for r in range(ns_first, ns_last + 1) if ns_title else ():
        name = str(_cell(values, r, nc)).strip()
        if not name:
            continue
        ns_names.append(name)
        if any(_norm(x) == TERMINATED for x in values[r - 1]):
            ns_term.add(_norm(base_name(name)))

    days = day_columns(values)
    sun_apps = days[-1][0] if days else 0
    fs_c, ld_c = _col_of(banner, FIELD_STATUS), _col_of(banner, LEADERSHIP)
    spelled = {}
    for r in range(first, last + 1):
        m = WEEK_N.match(str(_cell(values, r, fs_c))) if fs_c else None
        if m:
            spelled.setdefault(int(m.group(1)), str(_cell(values, r, fs_c)).strip())

    delete, terminated, renames, on_board = [], [], {}, set()
    run_c, last_c, prior_c = (_label_cols(banner, x) for x in (RUNNING, LAST, PRIOR))
    for r in range(first, last + 1):
        name = str(_cell(values, r, nc))
        key = _norm(base_name(name))
        if key and (_norm(_cell(values, r, sun_apps)) == "T" or key in ns_term):
            delete.append(r)
            terminated.append(name.strip())
            continue
        if key:
            on_board.add(key)
        # last week's totals <- running, prior <- last
        for src, dst in ((run_c, last_c), (last_c, prior_c)):
            for s, d in zip(src, dst):
                v = _cell(raw, r, s)
                if _typed(formulas, r, d) and v != _cell(raw, r, d):
                    cells[K.col_letter(d) + str(r)] = v
        # the typed day cells start blank
        for _, c1, c2 in days:
            for c in range(c1, c2 + 1):
                if _typed(formulas, r, c) and str(_cell(formulas, r, c)).strip():
                    cells[K.col_letter(c) + str(r)] = ""
        # one week further in
        nxt = next_status(_cell(values, r, fs_c), spelled) if fs_c and key else None
        if nxt:
            week, status = nxt
            cells[K.col_letter(fs_c) + str(r)] = status
            new = next_name(name, week)
            if new != name:
                cells[K.col_letter(nc) + str(r)] = new
                renames[name.strip()] = new.strip()
            if week == 1 and ld_c and _norm(_cell(values, r, ld_c)) == "IN TRAINING":
                cells[K.col_letter(ld_c) + str(r)] = "Entry Level"

    # the TOTALS row's own week columns follow the same shift
    for src, dst in ((run_c, last_c), (last_c, prior_c)):
        for s, d in zip(src, dst):
            if _typed(formulas, tot, d) and _cell(raw, tot, s) != _cell(raw, tot, d):
                cells[K.col_letter(d) + str(tot)] = _cell(raw, tot, s)

    # the dates: row 2 day numbers under each day banner, and the C3 label
    for i, (a, _, _) in enumerate(days):
        if lay.day_row + 1 < lay.sub_row and _typed(formulas, lay.day_row + 1, a) \
                and re.fullmatch(r"\d{1,2}", str(_cell(values, lay.day_row + 1, a)).strip()):
            cells[K.col_letter(a) + str(lay.day_row + 1)] = (monday + dt.timedelta(days=i)).day
    old_label = str(_cell(values, lay.sub_row, nc)).strip()
    if WE_LABEL.match(old_label) and _typed(formulas, lay.sub_row, nc):
        cells[K.col_letter(nc) + str(lay.sub_row)] = week_label(monday)

    # New Starts box: typed cells of its data rows go blank
    for r in range(ns_first, ns_last + 1) if ns_title else ():
        for c, v in enumerate(values[r - 1], 1):
            if str(v).strip() and _typed(formulas, r, c):
                cells[K.col_letter(c) + str(r)] = ""
    missing = [n for n in ns_names if _norm(base_name(n)) not in on_board
               and _norm(base_name(n)) not in ns_term]

    # the week that closed, for the top of the history
    hist = next((r for r in range(tot + 1, len(values) + 1)
                 if WE_LABEL.match(str(_cell(values, r, nc)))), 0)
    # as wide as the history rows already are (TOTALS goes further, into Sunday)
    width = max((c for c in range(nc + 1, len(values[hist - 1]) + 1)
                 if str(_cell(values, hist, c)).strip()), default=nc) if hist else nc
    # labelled by the date, not C3: a hand-made tab can keep last week's C3
    # (11.1 still read 'WE 10/19 - 10/25' on 10/26)
    line = [week_label(monday - dt.timedelta(days=7))] + \
        [_cell(raw, tot, c) for c in range(nc + 1, width + 1)]

    return {"cells": cells, "delete": delete, "terminated": terminated,
            "renames": renames, "missing": missing, "history_row": hist,
            "history_line": line, "first": first, "last": last, "name_col": nc}


def _grid(sid: int, r1: int, r2: int, c1: int, c2: int) -> dict:
    return {"sheetId": sid, "startRowIndex": r1 - 1, "endRowIndex": r2,
            "startColumnIndex": c1 - 1, "endColumnIndex": c2}


def _sheet_meta(sh, title: str) -> dict:
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,title,index,"
                                              "gridProperties),rowGroups,basicFilter)"})
    return next(s for s in meta["sheets"] if s["properties"]["title"] == title)


def roll_board(sh, src: str, name: str, monday: dt.date, at: int) -> dict:
    ws = sh.worksheet(src)
    values = ws.get_all_values()
    formulas = ws.get_all_values(value_render_option="FORMULA")
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if not K.is_board(values):
        raise RuntimeError("'%s' does not read as a sales board -- not copying it" % src)
    p = plan(values, formulas, raw, monday)
    old = _sheet_meta(sh, src)
    p["ncols"] = old["properties"]["gridProperties"]["columnCount"]
    sh.batch_update({"requests": [{"duplicateSheet": {
        "sourceSheetId": old["properties"]["sheetId"], "insertSheetIndex": at,
        "newSheetName": name}}]})
    new = sh.worksheet(name)
    try:
        return _fill_board(sh, new, name, p)
    except Exception:
        # half a tab must not pass for this week's: the next run sees no tab
        # and makes it whole (it is Lucy's own copy, nobody typed in it yet)
        sh.del_worksheet(new)
        raise


def _fill_board(sh, new, name: str, p: dict) -> dict:
    sid = new.id
    old_cols = p["ncols"]
    if p["cells"]:
        new.batch_update([{"range": a1, "values": [[v]]} for a1, v in p["cells"].items()],
                         value_input_option="RAW")

    # the closed week on top of the history (a row inserted INSIDE the table)
    h = p["history_row"]
    if h:
        sh.batch_update({"requests": [{"insertDimension": {
            "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": h - 1, "endIndex": h},
            "inheritFromBefore": False}}]})
        nc = p["name_col"]
        new.update(range_name="%s%d:%s%d" % (K.col_letter(nc), h,
                                             K.col_letter(nc + len(p["history_line"]) - 1), h),
                   values=[p["history_line"]], value_input_option="RAW")

    # terminated rows out, then A-Z: the filter is lifted for that (a sort
    # skips nothing it can see) and put back as it was, minus the deleted rows
    flt = (_sheet_meta(sh, name).get("basicFilter") or {})
    reqs = []
    if flt:
        reqs.append({"setBasicFilter": {"filter": {"range": flt["range"]}}})
    for r in sorted(p["delete"], reverse=True):
        reqs.append({"deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                   "startIndex": r - 1, "endIndex": r}}})
    gone = len(p["delete"])
    reqs.append({"sortRange": {
        "range": _grid(sid, p["first"], p["last"] - gone, p["name_col"], old_cols),
        "sortSpecs": [{"dimensionIndex": p["name_col"] - 1, "sortOrder": "ASCENDING"}]}})
    if flt:
        # the filter's own saved sort is left out: put back, it re-sorts the
        # rows by it (10.25 had one on # Days Worked) and undoes the A-Z
        f = {k: v for k, v in flt.items() if k != "sortSpecs"}
        f["range"] = dict(flt["range"], endRowIndex=flt["range"]["endRowIndex"] - gone)
        reqs.append({"setBasicFilter": {"filter": f}})
    sh.batch_update({"requests": reqs})
    _renumber(new, p["first"], p["last"] - gone)

    # the history group: everything under the newest row, collapsed
    if h:
        top = h - gone                       # 1-based row of the new line
        meta = _sheet_meta(sh, name)
        grp = next((g for g in meta.get("rowGroups", [])
                    if top - 1 <= g["range"]["startIndex"] <= top + 1), None)
        if grp:
            end = grp["range"]["endIndex"]
            sh.batch_update({"requests": [
                {"deleteDimensionGroup": {"range": grp["range"]}},
                {"addDimensionGroup": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                 "startIndex": top, "endIndex": end}}},
                {"updateDimensionGroup": {"dimensionGroup": {
                    "range": {"sheetId": sid, "dimension": "ROWS",
                              "startIndex": top, "endIndex": end},
                    "depth": grp.get("depth", 1), "collapsed": True},
                    "fields": "collapsed"}}]})
    p["new_last"] = p["last"] - gone
    return p


def _renumber(ws, first: int, last: int) -> None:
    """The '#' column counts down the rows (=B4+1); a deleted row leaves its
    neighbour with =#REF!+1. Put the chain back on those."""
    col = ws.get(range_name="B%d:B%d" % (first, last), value_render_option="FORMULA")
    fix = [{"range": "B%d" % r, "values": [["=B%d+1" % (r - 1)]]}
           for r, row in zip(range(first, last + 1), col + [[]] * (last - first + 1))
           if r > first and "#REF!" in str(row[0] if row else "")]
    if fix:
        ws.batch_update(fix, value_input_option="USER_ENTERED")


def _renamed(v, renames: Dict[str, str]):
    return renames.get(str(v).strip()) if str(v).strip() else None


def roll_lineup(sh, src: str, name: str, old_board: str, new_board: str,
                new_last: int, old_last: int, renames: Dict[str, str], at: int) -> int:
    """Copy last week's Line Up for the new week. Returns the cells written."""
    old = _sheet_meta(sh, src)
    sh.batch_update({"requests": [{"duplicateSheet": {
        "sourceSheetId": old["properties"]["sheetId"], "insertSheetIndex": at,
        "newSheetName": name}}]})
    ws = sh.worksheet(name)
    values = ws.get_all_values()
    formulas = ws.get_all_values(value_render_option="FORMULA")
    head = next((r for r in range(1, len(values) + 1)
                 if _norm(_cell(values, r, 2)).startswith(LINEUP_NAMES)), 0)
    out: Dict[str, object] = {}
    rides = {c for row in values[:3] for c, h in enumerate(row, 1) if "CAR RIDE" in _norm(h)}
    ref = re.compile(r"('?%s'?!\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?)(\d+)" % re.escape(old_board))
    for r, row in enumerate(formulas, 1):
        for c, f in enumerate(row, 1):
            f = str(f)
            if f.startswith("=") and old_board in f:
                g = ref.sub(lambda m: m.group(1) + (str(new_last) if int(m.group(2)) == old_last
                                                    else m.group(2)), f)
                out[K.col_letter(c) + str(r)] = g.replace("'%s'" % old_board, "'%s'" % new_board)
            elif c in rides and not f.startswith("=") and (not head or r < head):
                new = _renamed(f, renames)
                if new:
                    out[K.col_letter(c) + str(r)] = new
    if head:
        for c, h in enumerate(values[head - 1], 1):
            if _norm(h) in LINEUP_CLEAR:
                for r in range(head + 1, len(values) + 1):
                    if str(_cell(values, r, c)).strip() and _typed(formulas, r, c):
                        out[K.col_letter(c) + str(r)] = ""
    if out:
        ws.batch_update([{"range": a1, "values": [[v]]} for a1, v in out.items()],
                        value_input_option="USER_ENTERED")
    return len(out)


def point_stations(sh, old_lineup: str, new_lineup: str) -> int:
    try:
        ws = sh.worksheet(STATIONS)
    except Exception:  # noqa: BLE001 -- no Stations tab, nothing to point
        return 0
    out = []
    for r, row in enumerate(ws.get_all_values(value_render_option="FORMULA"), 1):
        for c, f in enumerate(row, 1):
            f = str(f)
            if f.startswith("=") and old_lineup in f:
                out.append({"range": K.col_letter(c) + str(r), "values": [[
                    f.replace("'%s'" % old_lineup, "'%s'" % new_lineup)]]})
    if out:
        ws.batch_update(out, value_input_option="USER_ENTERED")
    return len(out)


def roll(sh, today: dt.date, apply: bool) -> Tuple[int, List[str]]:
    """(exit code, lines worth a DM). 0 done or already there, 2 refused."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,title,index))"})
    tabs = {s["properties"]["title"]: s["properties"]["index"] for s in meta["sheets"]}
    sunday = C.week_ending(today)
    prev = sunday - dt.timedelta(days=7)
    monday = sunday - dt.timedelta(days=6)
    board, lineup = find_tab(tabs, BOARD_PREFIX, sunday), find_tab(tabs, LINEUP_PREFIX, sunday)
    old_board, old_lineup = find_tab(tabs, BOARD_PREFIX, prev), find_tab(tabs, LINEUP_PREFIX, prev)
    if board and lineup:
        print("  '%s' and '%s' are already there -- nothing to do" % (board, lineup))
        return 0, []
    if not old_board:
        print("  no '%s' to copy from: a week is missing, not guessing" % tab_title(BOARD_PREFIX, prev))
        return 2, ["no '%s' tab to copy" % tab_title(BOARD_PREFIX, prev)]
    notes: List[str] = []
    new_board = board or tab_title(BOARD_PREFIX, sunday)
    renames, new_last = {}, None
    ws = sh.worksheet(old_board)
    values = ws.get_all_values()
    old_last = K.block_rows(values)[1]
    if not board:
        if not apply:
            p = plan(values, ws.get_all_values(value_render_option="FORMULA"),
                     ws.get_all_values(value_render_option="UNFORMATTED_VALUE"), monday)
            print("  '%s' -> '%s': %d cells, history <- %s %s"
                  % (old_board, new_board, len(p["cells"]), p["history_line"][0],
                     p["history_line"][1:4]))
            print("    terminated out (%d): %s" % (len(p["terminated"]), ", ".join(p["terminated"]) or "-"))
            print("    renamed (%d): %s" % (len(p["renames"]), "; ".join(
                "%s -> %s" % kv for kv in p["renames"].items()) or "-"))
            print("    New Starts not on the board: %s" % (", ".join(p["missing"]) or "-"))
            print("  PREVIEW -- nothing written (--apply writes)")
            return 0, []
        p = roll_board(sh, old_board, new_board, monday, tabs[old_board])
        renames, new_last = p["renames"], p["new_last"]
        print("  made '%s': %d terminated out, %d renamed, history <- %s"
              % (new_board, len(p["terminated"]), len(renames), p["history_line"][0]))
        if p["terminated"]:
            print("    terminated: " + ", ".join(p["terminated"]))
        if p["missing"]:
            notes.append("New Starts not on the board (not added): " + ", ".join(p["missing"]))
            print("    ! " + notes[-1])
    elif not lineup:
        # the board was made on a run that stopped before the Line Up: the
        # same names change, read again off last week's tab
        renames = plan(values, ws.get_all_values(value_render_option="FORMULA"),
                       ws.get_all_values(value_render_option="UNFORMATTED_VALUE"),
                       monday)["renames"]
    if not lineup:
        if not old_lineup:
            print("  no '%s' to copy -- Line Up not made" % tab_title(LINEUP_PREFIX, prev))
            notes.append("no '%s' tab: this week's Line Up was not made" % tab_title(LINEUP_PREFIX, prev))
            return 2, notes
        if new_last is None:
            new_last = K.block_rows(sh.worksheet(new_board).get_all_values())[1]
        new_lineup = tab_title(LINEUP_PREFIX, sunday)
        if not apply:
            print("  '%s' -> '%s' (names to row %d), Stations re-pointed -- PREVIEW"
                  % (old_lineup, new_lineup, new_last))
            return 0, notes
        idx = {s["properties"]["title"]: s["properties"]["index"] for s in sh.fetch_sheet_metadata(
            {"fields": "sheets(properties(title,index))"})["sheets"]}
        n = roll_lineup(sh, old_lineup, new_lineup, old_board, new_board, new_last, old_last,
                        renames, idx[new_board] + 1)
        s = point_stations(sh, old_lineup, new_lineup)
        print("  made '%s' (%d cells), Stations: %d formulas -> new Line Up" % (new_lineup, n, s))
    return 0, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="make the tabs (default: preview)")
    ap.add_argument("--sheet", help="test copy: use this sheet id instead of the real board")
    ap.add_argument("--today", help="YYYY-MM-DD, for a test (default: today, Central)")
    a = ap.parse_args(argv)
    if a.today:
        today = dt.date.fromisoformat(a.today)
    else:
        from zoneinfo import ZoneInfo
        today = dt.datetime.now(ZoneInfo("America/Chicago")).date()
    sheet = a.sheet or C.SPREADSHEET_ID
    print("Alphalete Sales Board week roll (%s), today %s:" % (
        "TEST COPY " + sheet if a.sheet else sheet, today))
    import time
    from automations.recruiting_report.fill import open_by_key
    for attempt in (1, 2, 3):
        try:
            rc, notes = roll(open_by_key(sheet), today, a.apply)
            break
        except Exception as e:  # noqa: BLE001 -- a failed roll has to reach Eve
            print("  FAILED: %s: %s" % (type(e).__name__, e))
            rc, notes = 1, ["it stopped: %s: %s" % (type(e).__name__, str(e)[:200])]
            # the read quota is shared by every report on the account: wait it
            # out and go again -- a second run picks up where this one stopped
            if "429" not in str(e) or attempt == 3:
                break
            time.sleep(70)
    if notes and a.apply and not a.sheet:
        tell_eve(notes)
    return rc


def tell_eve(notes) -> None:
    """The roll has no Hub card: what needs a person goes to Eve by DM."""
    try:
        from automations.shared import slack_metrics_post as smp
        from automations.sales_board_fixer.run import EVE_USER_ID
        client = smp._client()
        if "lucy" not in client.auth_test().get("user", "").lower():
            print("! this machine does not post as Lucy -- no DM")
            return
        text = "Sales Board week roll:\n" + "\n".join("- " + n for n in notes)
        ch = client.conversations_open(users=EVE_USER_ID)["channel"]["id"]
        client.chat_postMessage(channel=ch, text=text)
        print("  DM to Eve")
    except Exception as e:  # noqa: BLE001 -- the DM never hides the real exit code
        print("! DM to Eve failed: %s" % e)


if __name__ == "__main__":
    sys.exit(main())

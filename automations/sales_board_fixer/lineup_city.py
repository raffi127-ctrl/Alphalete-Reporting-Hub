"""Line Up 'City' column: always the zip lookup, and locked (Maud's Loom, 2026-11-09).

A person makes the Line Up tab by hand on Fridays, and the City formulas got lost
on the way (WE 11.08: 26 of 36 rows typed). Reps must not type a city: it comes
from the zip. So every morning, on this week's tab and on next week's once it
exists:

  * every numbered row's City cell is =XLOOKUP(zip, zip table, city table, "")
  * those cells are protected, only EDITORS can change them.

Columns and rows are found by their labels: the first 'Zip Code' / 'City' are the
line up, the second pair is the table to the right. A typed city whose zip is NOT
in the table stays and is reported: the formula would blank it and nobody could
get the city back.

Only Alphalete's own board: owners' Line Ups have other layouts.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from automations.sales_board_fixer import checks as K

EDITORS = ["alphaletereporting@gmail.com",  # Lucy's Sheets login + Eve (Eve 2026-11-09)
           "raffi127@gmail.com",            # Raf
           "alphaletemarketing@gmail.com",  # Raf, his other login
           "maudmiller4@gmail.com"]         # Maud, the workbook's owner
DESCRIPTION = "City comes from the zip code: do not type here (Lucy)"


def _label(x) -> str:
    return " ".join(str(x).split()).lower()


def layout(values) -> Optional[dict]:
    """Where the columns and numbered rows are, or None if this isn't that layout."""
    for r, row in enumerate(values, 1):
        labels = [_label(x) for x in row]
        zips = [c for c, x in enumerate(labels, 1) if x == "zip code"]
        cities = [c for c, x in enumerate(labels, 1) if x == "city"]
        if _label(row[0] if row else "") != "#" or len(zips) < 2 or len(cities) < 2:
            continue
        first = r + 1
        last = r
        while last < len(values) and str((values[last] or [""])[0]).strip().isdigit():
            last += 1
        if last < first:
            return None
        return {"first": first, "last": last, "zip": zips[0], "city": cities[0],
                "table_zip": zips[1], "table_city": cities[1], "header": r}
    return None


def formula(lay: dict, row: int) -> str:
    return '=XLOOKUP(%s%d, %s:%s, %s:%s, "")' % (
        K.col_letter(lay["zip"]), row,
        K.col_letter(lay["table_zip"]), K.col_letter(lay["table_zip"]),
        K.col_letter(lay["table_city"]), K.col_letter(lay["table_city"]))


def _cell(grid, r: int, c: int):
    row = grid[r - 1] if r - 1 < len(grid) else []
    return row[c - 1] if c - 1 < len(row) else ""


def _same(a, b) -> bool:
    return re.sub(r"\s+", "", str(a)).lower() == re.sub(r"\s+", "", str(b)).lower()


def plan_cells(values, formulas, lay: dict) -> Tuple[Dict[str, str], List[str]]:
    """({a1: formula}, [lines about typed cities left alone])."""
    table = {str(_cell(values, r, lay["table_zip"])).strip()
             for r in range(lay["header"] + 1, len(values) + 1)}
    table.discard("")
    cells, kept = {}, []
    for r in range(lay["first"], lay["last"] + 1):
        want = formula(lay, r)
        have = _cell(formulas, r, lay["city"])
        if _same(have, want):
            continue
        z = str(_cell(values, r, lay["zip"])).strip()
        typed = str(_cell(values, r, lay["city"])).strip()
        a1 = K.col_letter(lay["city"]) + str(r)
        if z and z not in table and typed:
            kept.append("%s: zip %s is not in the table, kept the typed '%s'" % (a1, z, typed))
            continue
        cells[a1] = want
    return cells, kept


def _grid_range(sheet_id: int, lay: dict) -> dict:
    return {"sheetId": sheet_id, "startRowIndex": lay["first"] - 1, "endRowIndex": lay["last"],
            "startColumnIndex": lay["city"] - 1, "endColumnIndex": lay["city"]}


def _editors(p: dict) -> set:
    return {u.lower() for u in (p.get("editors") or {}).get("users", [])}


def plan_protection(sheet_id: int, lay: dict, protections: List[dict]) -> Optional[dict]:
    """The one request that leaves the City cells protected, or None if they are.
    A protection already on this column is corrected, never a second one on top."""
    rng = _grid_range(sheet_id, lay)
    want = {u.lower() for u in EDITORS}
    mine = [p for p in protections
            if p.get("range", {}).get("startColumnIndex") == rng["startColumnIndex"]
            and p.get("range", {}).get("endColumnIndex") == rng["endColumnIndex"]]
    if not mine:
        return {"addProtectedRange": {"protectedRange": {
            "range": rng, "description": DESCRIPTION, "warningOnly": False,
            "editors": {"users": EDITORS}}}}
    p = mine[0]
    same_range = all(p["range"].get(k, 0) == rng[k] for k in rng)
    # the owner can always edit, Sheets may list them or not
    same_people = (_editors(p) | {EDITORS[-1]}) == want
    if same_range and same_people and not p.get("warningOnly"):
        return None
    return {"updateProtectedRange": {
        "protectedRange": {"protectedRangeId": p["protectedRangeId"], "range": rng,
                           "warningOnly": False, "editors": {"users": EDITORS}},
        "fields": "range,warningOnly,editors"}}


def do_tab(sh, title: str, do_apply: bool) -> List[str]:
    """Lines for Eve; [] when there's nothing a person needs to know. Never raises:
    the rest of the morning's fixes go on whatever happens here."""
    try:
        ws = sh.worksheet(title)
        values = ws.get_all_values()
        lay = layout(values)
        if not lay:
            print("  %s: no zip table, City left alone" % title)
            return []
        cells, kept = plan_cells(values, ws.get_all_values(value_render_option="FORMULA"), lay)
        meta = sh.fetch_sheet_metadata({
            "fields": "sheets(properties(sheetId,title),protectedRanges)"})
        sheet = next(s for s in meta["sheets"] if s["properties"]["title"] == title)
        req = plan_protection(ws.id, lay, sheet.get("protectedRanges") or [])
        print("  %s: City %s%d-%d, %d formulas to put back, protection: %s" % (
            title, K.col_letter(lay["city"]), lay["first"], lay["last"], len(cells),
            next(iter(req)) if req else "ok"))
        for line in kept:
            print("    " + line)
        if do_apply:
            # protection first: if this login is locked out, it fails before any write
            if req:
                sh.batch_update({"requests": [req]})
            if cells:
                ws.batch_update([{"range": a, "values": [[f]]} for a, f in cells.items()],
                                value_input_option="USER_ENTERED")
        return ["'%s' %s" % (title, line) for line in kept]
    except Exception as e:  # noqa: BLE001 -- one step of the fixer
        print("  ! %s: City not checked: %s: %s" % (title, type(e).__name__, e))
        return ["'%s': City formulas/protection not done: %s" % (title, str(e)[:150])]

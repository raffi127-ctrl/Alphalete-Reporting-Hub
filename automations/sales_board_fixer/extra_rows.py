"""Spare rows at the bottom of each Sales Board -- keep at least 10.

Raf's ask (Slack, 2026-10-27): "an audit where it checks for 'extra' rows, and
if there's not like 10 rows in the 'extra' column, it just creates it for the
owner." A spare row is where the next new rep gets typed in; when a board runs
out, someone inserts one by hand and it comes in without formulas or format.

Each board keeps its own kind of spare row, read off the board:
  - our board, Cyrus: blank name, hidden
  - Frank, Drew, Ryan, Miami: 'ZZ EXTRA'
  - Valeria: 'xx', hidden
  - Atef: none at all -- the last rep row is the model, formulas only.

New rows go in ABOVE the last row of the block, never under it: a total like
=SUM(D5:D73) only grows when rows land inside its range, so a row added
between 73 and TOTALS would be left out of every total, Line Up and Lane.
The model row is copied whole (formulas, format, its placeholder name), and
hidden again if the model is hidden; a rep row as model gives only its
formulas and format. Nothing is ever deleted or overwritten.

    python -m automations.sales_board_fixer.extra_rows             # look only
    python -m automations.sales_board_fixer.extra_rows --apply     # add what's missing
    python -m automations.sales_board_fixer.extra_rows --only Atef
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from dataclasses import dataclass

from automations.sales_board_fixer import checks as K
from automations.sales_board_fixer import run as R

MIN_SPARE = 10
# a placeholder name on a spare row: 'ZZ EXTRA', 'Extra', 'xx'
PLACEHOLDER = re.compile(r"^(zz\s*)?extra\s*\d*$|^x{2,}$", re.I)


@dataclass
class Plan:
    spare: int           # spare rows the board has now
    add: int             # rows to add
    model: int           # row copied into the new ones
    model_is_rep: bool   # no spare row to copy: formulas + format of a rep row
    at: int              # new rows start here (1-based), pushing this row down
    last: int            # last row of the block


def is_spare(name: str) -> bool:
    return not name.strip() or bool(PLACEHOLDER.match(name.strip()))


def plan(values) -> Plan:
    first, last = K.block_rows(values)
    spare = [r for r in range(first, last + 1) if is_spare(K.name_at(values, r))]
    model = spare[-1] if spare else last
    return Plan(len(spare), max(0, MIN_SPARE - len(spare)), model, not spare, last, last)


def requests(sheet_id: int, p: Plan, hidden: bool, model_cells) -> list:
    """batch_update requests for plan p. model_cells = the model row's
    [{userEnteredValue, userEnteredFormat}] as read before the insert.

    Written with updateCells, not copyPaste: our board's spare rows are hidden
    by its filter, and copyPaste refuses a range with a filtered-out row
    (2026-10-27, the first --apply)."""
    if not p.add:
        return []
    at0 = p.at - 1                                   # 0-based, inside the block
    reqs = [{"insertDimension": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS",
                  "startIndex": at0, "endIndex": at0 + p.add},
        "inheritFromBefore": True}}]
    if p.model_is_rep:
        # the rep (pushed under the new rows) goes back up, so the blanks sit
        # at the bottom of the list, not between the last two reps
        reqs.append({"moveDimension": {
            "source": {"sheetId": sheet_id, "dimension": "ROWS",
                       "startIndex": at0 + p.add, "endIndex": at0 + p.add + 1},
            "destinationIndex": at0}})
        at0 += 1
    rows = []
    for i in range(p.add):
        r = at0 + 1 + i
        cells = []
        for cell in model_cells:
            val = (cell or {}).get("userEnteredValue") or {}
            out = {"userEnteredFormat": (cell or {}).get("userEnteredFormat") or {}}
            if "formulaValue" in val:
                out["userEnteredValue"] = {"formulaValue": K.denormalize(
                    K.normalize(val["formulaValue"], p.model), r)}
            elif val and not p.model_is_rep:
                # a spare row's placeholder ('ZZ EXTRA', 'xx', a 0) comes along;
                # a rep's name and numbers never do
                out["userEnteredValue"] = val
            cells.append(out)
        rows.append({"values": cells})
    reqs.append({"updateCells": {
        "range": {"sheetId": sheet_id, "startRowIndex": at0, "endRowIndex": at0 + p.add,
                  "startColumnIndex": 0, "endColumnIndex": len(model_cells)},
        "rows": rows, "fields": "userEnteredValue,userEnteredFormat"}})
    if hidden:
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                      "startIndex": at0, "endIndex": at0 + p.add},
            "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
    return reqs


RANGE = re.compile(r"(\$?[A-Z]{1,3}\$?)(\d+):(\$?[A-Z]{1,3}\$?)(\d+)")


def short_totals(formulas, first: int, last: int) -> dict:
    """{a1: formula} for the TOTALS row: every range that starts on the first
    rep row but stops before the last row of the block is stretched to it.
    Atef's totals (2026-10-27) summed 4:20 with his last rep on row 21; Cyrus's
    stopped above his spare rows -- a rep typed there never reached the total."""
    row = formulas[last] if last < len(formulas) else []
    out = {}
    for c, f in enumerate(row, start=1):
        f = str(f)
        if not f.startswith("="):
            continue
        new = RANGE.sub(lambda m: "%s%s:%s%d" % (m.group(1), m.group(2), m.group(3), last)
                        if int(m.group(2)) == first and first < int(m.group(4)) < last
                        else m.group(0), f)
        if new != f:
            out[K.a1(last + 1, c)] = new
    return out


def _model_cells(sh, title: str, row: int) -> list:
    meta = sh.fetch_sheet_metadata({
        "includeGridData": True, "ranges": ["'%s'!%d:%d" % (title, row, row)],
        "fields": "sheets(data(rowData(values(userEnteredValue,userEnteredFormat))))"})
    rd = meta["sheets"][0]["data"][0].get("rowData") or [{}]
    return rd[0].get("values", [])


def _hidden(sh, title: str, row: int) -> bool:
    meta = sh.fetch_sheet_metadata({
        "includeGridData": True, "ranges": ["'%s'!A%d" % (title, row)],
        "fields": "sheets(data(rowMetadata(hiddenByUser,hiddenByFilter)))"})
    rm = (meta["sheets"][0]["data"][0].get("rowMetadata") or [{}])[0]
    return bool(rm.get("hiddenByUser") or rm.get("hiddenByFilter"))


def board_tabs(sh, owner=None) -> list:
    if owner is None:
        have = R._tabs(sh)
        return [t for t in R.week_tabs(dt.date.today())
                if t in have and t.lower().startswith("sales board")][:1]
    if owner.get("tabs"):
        return [t for t in owner["tabs"] if t in R._tabs(sh)]
    return R.owner_tabs(sh, owner.get("boards", 1), owner.get("week_end", False),
                        owner.get("newest_right", False))


def do_tab(sh, title: str, label: str, apply: bool, stamp: str) -> dict:
    ws = sh.worksheet(title)
    values = ws.get_all_values()
    if not K.is_board(values):
        return {}
    p = plan(values)
    hidden = (not p.model_is_rep) and _hidden(sh, title, p.model)
    out = {"spare": p.spare, "add": p.add, "model": p.model,
           "model_is_rep": p.model_is_rep, "hidden": hidden, "at": p.at}
    what = ("sin filas libres: copio fórmulas + formato de la fila %d" % p.model
            if p.model_is_rep else "copio la fila libre %d%s" % (p.model, " (oculta)" if hidden else ""))
    print("%s%s: %d filas libres%s" % (label, title, p.spare,
          " -> agrego %d arriba de la fila %d (%s)" % (p.add, p.at, what) if p.add else " -- OK"))
    tot = short_totals(ws.get_all_values(value_render_option="FORMULA"), *K.block_rows(values))
    if tot and not p.add:
        print("  TOTALS no llega a la última fila: %d celdas (%s)" % (len(tot), ", ".join(tot)[:60]))
    out["totals"] = len(tot)
    if not apply or not (p.add or tot):
        return out
    # the board re-sorts itself: the block must still end where it was read
    if K.block_rows(ws.get_all_values())[1] != p.last:
        print("  el board se movió mientras leía -- no escribo, mañana de nuevo")
        return out
    print("  backup:", R.backup(R.load(sh, title), stamp))
    if p.add:
        sh.batch_update({"requests": requests(ws.id, p, hidden, _model_cells(sh, title, p.model))})
        print("  agregadas: %d" % p.add)
    # after an insert the block is longer: read it again before stretching
    tot = short_totals(ws.get_all_values(value_render_option="FORMULA"),
                       *K.block_rows(ws.get_all_values()))
    if tot:
        ws.batch_update([{"range": a, "values": [[f]]} for a, f in tot.items()],
                        value_input_option="USER_ENTERED")
        print("  TOTALS estirado hasta la última fila: %d celdas" % len(tot))
    out["written"] = True
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="agregar las filas que faltan")
    ap.add_argument("--only", default="", help="solo este board (nombre del dueño, o 'nuestro')")
    a = ap.parse_args(argv)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M") + "_extra"
    owners = json.loads(R.OWNERS_FILE.read_text(encoding="utf-8"))["owners"]
    targets = [("Nuestro", R.SHEET_ID, None, True)] + [
        (o["name"], o["sheet_id"], o, o.get("apply", False)) for o in owners]
    results = {}
    for name, sid, o, on in targets:
        if a.only and a.only.lower() not in name.lower():
            continue
        try:
            sh = R._book(sid)
            for title in board_tabs(sh, o):
                res = do_tab(sh, title, name + " · ", a.apply and on, stamp)
                if res:
                    results[name + " · " + title] = res
        except Exception as e:  # noqa: BLE001 -- one board never stops the rest
            print("== %s: se cortó (%s: %s)" % (name, type(e).__name__, str(e)[:120]))
        time.sleep(2)                      # Sheets read quota
    R.OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = R.OUT_DIR / ("%s.json" % stamp)
    path.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print("reporte:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

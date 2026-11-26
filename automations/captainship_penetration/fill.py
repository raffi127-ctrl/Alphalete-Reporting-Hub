"""Sheet side of the Captainship Penetration box: one tab per captainship.

Where (Eve 2026-11-26: "same sheet as the fiber activations, the metrics are
alike"): the fiber captains' tabs go in the per-captain Fiber Activations
workbook (fiber_activations.captains.NEW_SHEET_ID); Rafael's goes in HIS
activations workbook (fiber_activations.fill.SHEET_ID), beside his
'Captainship Activations'. Tabs are created by this module from scratch the
first time; after that it only inserts today's column and adds missing owners -
it never deletes a row or a tab.

Layout (same shape as the activation-rate boxes, so daily_box_render draws it):

    A1  <Captain> - Captainship Penetration
    A2  PENETRATION RATE (ONGOING)    B2 date (newest), C2 the day before ...
    A3  Captainship Avg               B3 %
    A4  Owner                         B4 '%'
    A5.. owners (Tableau spelling)    B5.. %

Colors: Raf's penetration legend (his Line Up / the zip penetration blocks) -
red under 1%, yellow 1-1.49%, green 1.5%+ - as conditional-format rules on the
tab, so the email (which reads the rules) and the sheet never disagree. NOT the
churn cuts (Eve 11/26).
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Dict, List

from automations.new_internet_churn import fill as _shared

BOX = "penetration"
HEADER = "PENETRATION RATE (ONGOING)"
AVG = "Captainship Avg"
OWNER_HDR = "Owner"

# Raf's legend colors (fiber_zip_penetration.core) - pastel red/yellow/green.
RED = {"red": 0.957, "green": 0.8, "blue": 0.8}
YELLOW = {"red": 1.0, "green": 0.949, "blue": 0.8}
GREEN = {"red": 0.851, "green": 0.918, "blue": 0.827}
HEADER_BG = {"red": 0.976, "green": 0.796, "blue": 0.612}   # #F9CB9C orange

# (condition, color) in Sheets' first-match-wins order.
BANDS = [
    ({"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0.01"}]}, RED),
    ({"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0.015"}]}, YELLOW),
    ({"type": "NUMBER_GREATER_THAN_EQ",
      "values": [{"userEnteredValue": "0.015"}]}, GREEN),
]


def location(slug: str):
    """(sheet_id, tab title) for this captain."""
    from automations.fiber_activations import captains as C, fill as F
    from automations.captainship_penetration.core import CAPTAIN_OWNER
    if slug == "rafael":
        return F.SHEET_ID, "Captainship Penetration"
    return C.NEW_SHEET_ID, f"{CAPTAIN_OWNER[slug]}'s Captainship Penetration"


def open_ws(slug: str):
    sid, tab = location(slug)
    return _shared.open_by_key(sid).worksheet(tab)


def find_boxes_in(col_a: List[str]) -> dict:
    """Pure half of find_boxes, over column A's values."""
    col_a = [(v or "").strip() for v in col_a]
    header = next((i + 1 for i, v in enumerate(col_a)
                   if "PENETRATION RATE" in v.upper() and "ONGOING" in v.upper()),
                  None)
    if header is None:
        return {}
    avg = rep_hdr = None
    for r in range(header + 1, len(col_a) + 1):
        v = col_a[r - 1].upper()
        if v in ("OWNER", "REP"):
            rep_hdr = r
            break
        if avg is None and "AVG" in v:
            avg = r
    avg = avg or header + 1
    rep_hdr = rep_hdr or header + 2
    rep_rows = {col_a[r - 1].lower(): r
                for r in range(rep_hdr + 1, len(col_a) + 1) if col_a[r - 1]}
    return {BOX: {"header_row": header, "office_avg_row": avg,
                  "rep_header_row": rep_hdr, "rep_rows": rep_rows}}


def find_boxes(ws) -> dict:
    """{'penetration': {header_row, office_avg_row, rep_header_row, rep_rows}}
    found by col-A LABEL (never row numbers)."""
    grid = _shared._retry(ws.get_all_values)
    return find_boxes_in([(r[0] if r else "") for r in grid])


def ensure_tab(slug: str, title: str, *, dry_run=False, logfn=print):
    """(worksheet, created) - the tab, created with layout + colors if missing."""
    sid, tab = location(slug)
    sh = _shared.open_by_key(sid)
    try:
        return sh.worksheet(tab), False
    except Exception:  # noqa: BLE001 - gspread WorksheetNotFound
        pass
    if dry_run:
        logfn(f"  (dry-run) would CREATE tab {tab!r}")
        return None, True
    ws = sh.add_worksheet(title=tab, rows=60, cols=40)
    ws.update(range_name="A1:B4", values=[
        [title, ""], [HEADER, ""], [AVG, ""], [OWNER_HDR, "%"]],
        value_input_option="USER_ENTERED")
    sid_ = ws.id
    reqs = [
        {"repeatCell": {"range": {"sheetId": sid_, "startRowIndex": 0,
                                  "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {
                            "bold": True, "fontSize": 12}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": {"sheetId": sid_, "startRowIndex": 1,
                                  "endRowIndex": 2},
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": HEADER_BG,
                            "textFormat": {"bold": True},
                            "numberFormat": {"type": "DATE",
                                             "pattern": "ddd m/d/yy"}}},
                        "fields": "userEnteredFormat(backgroundColor,"
                                  "textFormat,numberFormat)"}},
        {"repeatCell": {"range": {"sheetId": sid_, "startRowIndex": 2,
                                  "startColumnIndex": 1},
                        "cell": {"userEnteredFormat": {"numberFormat": {
                            "type": "PERCENT", "pattern": "0.00%"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": {"sheetId": sid_, "startRowIndex": 2,
                                  "endRowIndex": 4},
                        "cell": {"userEnteredFormat": {"textFormat": {
                            "bold": True}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid_, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 220}, "fields": "pixelSize"}},
    ]
    # Rules start at column A, not B: the daily insert at B would push a range
    # that STARTS at B over to C and leave today's column uncolored. Column A
    # holds names, which a NUMBER_* condition never matches.
    for i, (cond, bg) in enumerate(BANDS):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": [{"sheetId": sid_, "startRowIndex": 2,
                        "startColumnIndex": 0}],
            "booleanRule": {"condition": cond,
                            "format": {"backgroundColor": bg}}}}})
    sh.batch_update({"requests": reqs})
    logfn(f"  created tab {tab!r}")
    return ws, True


def plan(grid: List[List[str]], box: dict, today: dt.date,
         owners: Dict[str, str]) -> dict:
    """Pure: {"insert_col": bool, "new_owners": [names not on the tab]}.
    A column is inserted unless B<header> is empty (brand-new tab) or already
    shows today's date (a re-run overwrites today)."""
    r = box["header_row"]
    row = grid[r - 1] if len(grid) >= r else []
    b = (row[1] if len(row) > 1 else "").strip()
    want = _shared._date_label(today)
    new = [o for o in owners if o.lower() not in box["rep_rows"]]
    return {"insert_col": bool(b) and b != want, "new_owners": sorted(new)}


def cells_for(title: str, box: dict, today: dt.date, data: dict) -> list:
    """Pure: today's column-B writes. Every owner row on the tab gets a value
    or an explicit blank (an owner who left the captainship keeps the row and
    its history, but no number today)."""
    cells = [{"range": f"'{title}'!B{box['header_row']}",
              "values": [[today.isoformat()]]},
             {"range": f"'{title}'!B{box['rep_header_row']}", "values": [["%"]]},
             {"range": f"'{title}'!B{box['office_avg_row']}",
              "values": [[data["avg"]]]}]
    by_lower = {o.lower(): v for o, v in data["owners"].items()}
    for name, row in sorted(box["rep_rows"].items(), key=lambda kv: kv[1]):
        cells.append({"range": f"'{title}'!B{row}",
                      "values": [[by_lower.get(name, "")]]})
    return cells


def write_day(ws, today: dt.date, data: dict, *, dry_run=False,
              logfn=print) -> dict:
    """Open (or reuse) today's column B and write avg + every owner."""
    boxes = find_boxes(ws)
    if BOX not in boxes:
        raise RuntimeError(f"{ws.title}: no '{HEADER}' box on the tab")
    box = boxes[BOX]
    grid = _shared._retry(ws.get_all_values)
    p = plan(grid, box, today, data["owners"])
    if dry_run:
        logfn(f"  (dry-run) {ws.title}: insert_col={p['insert_col']} "
              f"new owners={p['new_owners']} avg={data['avg']} "
              f"owners={data['owners']}")
        return p
    if p["new_owners"]:
        start = max([box["rep_header_row"], *box["rep_rows"].values()]) + 1
        end = start + len(p["new_owners"]) - 1
        if ws.row_count < end:
            ws.add_rows(end - ws.row_count + 10)
        ws.update(range_name=f"A{start}:A{end}",
                  values=[[o] for o in p["new_owners"]])
        time.sleep(1)
        box = find_boxes(ws)[BOX]
    if p["insert_col"]:
        if ws.col_count - max((len(r) for r in grid), default=0) < 2:
            ws.add_cols(12)
        top = box["header_row"] - 1
        rng = {"sheetId": ws.id, "startRowIndex": top,
               "endRowIndex": ws.row_count}
        ws.spreadsheet.batch_update({"requests": [{"insertRange": {
            "range": {**rng, "startColumnIndex": 1, "endColumnIndex": 2},
            "shiftDimension": "COLUMNS"}}]})
        time.sleep(1)
        ws.spreadsheet.batch_update({"requests": [{"copyPaste": {
            "source": {**rng, "startColumnIndex": 2, "endColumnIndex": 3},
            "destination": {**rng, "startColumnIndex": 1, "endColumnIndex": 2},
            "pasteType": "PASTE_FORMAT"}}]})
        time.sleep(2)
    ws.spreadsheet.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": cells_for(ws.title, box, today, data)})
    logfn(f"  ✓ {ws.title}: {len(data['owners'])} owners, avg {data['avg']}"
          f"{' (new column)' if p['insert_col'] else ''}"
          f"{' +%d new' % len(p['new_owners']) if p['new_owners'] else ''}")
    return p

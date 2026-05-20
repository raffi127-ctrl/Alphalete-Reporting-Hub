"""Fill the First/Last Sale section on each ICD tab.

Per tab:
  1. Find section by anchor: cell whose value is 'First Sale Avg Office'.
  2. Insert missing day rows so the chart is 10 rows (header + sub-header
     + Week Avg + Sun-Sat) — uses the Sheets API insertDimension.
  3. For owners in the upload: write times + Order Count for each day. Days
     the owner has no data for get 'No Logged Knocks' in time cells + 0
     orders so every row is populated.
  4. For owners NOT in the upload: replace the WE header with 'Not On
     Emailed Report' (light-red background + black bold text) and clear
     body cells.
  5. Marcellus Butler's section is the formatting source (column/row
     headers / borders / blues) — Megan-formatted by hand.

Public API:
  fill_for_tab(sh, ws, week, parsed, aliases_map, src_chart, src_sid, dry_run)
  -> log lines list
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple, Any

import gspread

from automations.recruiting_report import fill as rfill


DAYS_FULL = ["Week Avg", "Sunday", "Monday", "Tuesday", "Wednesday",
             "Thursday", "Friday", "Saturday"]
NO_DATA_TIME = "No Logged Knocks"
NOT_ON_UPLOAD = "Not On Emailed Report"
# Google Sheets 'Light red 3' — for the WE header cell on absent-owner tabs
LIGHT_RED = {"red": 244/255, "green": 199/255, "blue": 195/255}
BLACK = {"red": 0, "green": 0, "blue": 0}
# Tabs the FSLS fill should skip entirely — Raf Hidalgo's tab has a different
# layout and no FK/LK section.
EXPECTED_NO_SECTION = {"Raf Hidalgo"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def fmt_we_header(d: dt.date) -> str:
    return f"WE {d.month}.{d.day}"


def fmt_time(t) -> str:
    """datetime.time(13, 39) -> '1:39 PM' — Sheets parses this; the cell's
    existing format renders as '1:39 p.m.' per Megan's preferred style."""
    if not t:
        return ""
    s = t.strftime("%I:%M %p")
    return s[1:] if s.startswith("0") else s


def find_owner(tab: str, parsed: Dict[str, dict],
               aliases_map: Dict[str, List[str]]) -> Optional[dict]:
    """Lookup the parsed entry for a Sheet tab using the alias list as the
    canonical-name bridge."""
    cands = {tab}
    for canon, al in aliases_map.items():
        if _norm(tab) in {_norm(canon)} | {_norm(a) for a in al}:
            cands.update([canon] + list(al))
    for c in cands:
        ent = parsed.get(_norm(c))
        if ent:
            return ent
    return None


def find_section(grid: List[List[str]]) -> Optional[dict]:
    """Locate the First/Last Sale section on a tab. Anchor: a cell whose
    value is exactly 'First Sale Avg Office'."""
    for i, row in enumerate(grid, start=1):
        for j, v in enumerate(row, start=1):
            if v.strip() != "First Sale Avg Office":
                continue
            first_col = j
            label_col = None
            for k in range(j - 1, max(j - 4, 0), -1):
                if (row[k - 1] if k - 1 < len(row) else "").strip() == "Week Avg":
                    label_col = k
                    break
            if not label_col:
                continue
            header_row, header_col = i - 1, None
            if header_row >= 1:
                hrow = grid[header_row - 1]
                for k, v2 in enumerate(hrow, start=1):
                    if re.match(r"^WE\s+\d", v2.strip()):
                        header_col = k
                        break
            body_rows: Dict[str, int] = {}
            for off in range(1, 13):
                rr = i + off
                if rr - 1 >= len(grid):
                    break
                lbl = (grid[rr - 1][label_col - 1]
                       if label_col - 1 < len(grid[rr - 1]) else "").strip()
                if lbl in DAYS_FULL:
                    body_rows[lbl] = rr
                elif body_rows:
                    break
            return {
                "header_row": header_row, "header_col": header_col,
                "subheader_row": i, "label_col": label_col,
                "first_col": first_col, "last_col": first_col + 1,
                "orders_col": first_col + 2, "body_rows": body_rows,
            }
    return None


def insert_missing_days(sh, ws, sheet_id: int) -> Optional[dict]:
    """Insert blank rows so the section's body_rows == DAYS_FULL. Re-reads
    after each insert. Returns the final section dict."""
    while True:
        grid = rfill._retry(ws.get_all_values)
        sec = find_section(grid)
        if not sec or not sec["body_rows"]:
            return sec
        body = dict(sec["body_rows"])
        missing_day = None
        prev_row = None
        for d in DAYS_FULL:
            if d in body:
                prev_row = body[d]
            else:
                missing_day = d
                break
        if not missing_day:
            return sec
        insert_at = (prev_row + 1) if prev_row else sec["subheader_row"] + 1
        req = {"insertDimension": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                      "startIndex": insert_at - 1, "endIndex": insert_at},
            "inheritFromBefore": True}}
        rfill._retry(sh.batch_update, {"requests": [req]})
        # Write the day label so find_section picks it up on the next pass
        a1 = gspread.utils.rowcol_to_a1(insert_at, sec["label_col"])
        rfill._retry(ws.update, a1, [[missing_day]],
                     value_input_option="USER_ENTERED")


def copyfmt_request(src_sheet_id, src_bounds, dst_sheet_id, dst_bounds):
    s_top, s_bot, s_left, s_right = src_bounds
    d_top, d_bot, d_left, d_right = dst_bounds
    return {"copyPaste": {
        "source": {"sheetId": src_sheet_id,
                   "startRowIndex": s_top - 1, "endRowIndex": s_bot,
                   "startColumnIndex": s_left - 1, "endColumnIndex": s_right},
        "destination": {"sheetId": dst_sheet_id,
                        "startRowIndex": d_top - 1, "endRowIndex": d_bot,
                        "startColumnIndex": d_left - 1, "endColumnIndex": d_right},
        "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}}


def section_bounds(sec: dict) -> Tuple[int, int, int, int]:
    body_rows = sec["body_rows"].values()
    return (sec["header_row"], max(body_rows),
            sec["label_col"], sec["orders_col"])


def fill_present(ws, sec, week: dt.date, owner: dict) -> int:
    """Owner is in the upload — fill all 8 day rows."""
    updates: List[Tuple[str, Any]] = []
    if sec["header_col"]:
        updates.append((gspread.utils.rowcol_to_a1(sec["header_row"], sec["header_col"]),
                        fmt_we_header(week)))
    days = owner["days"]
    for label in DAYS_FULL:
        row = sec["body_rows"].get(label)
        if row is None:
            continue
        if label in days:
            f, l, o = days[label]
            updates.append((gspread.utils.rowcol_to_a1(row, sec["first_col"]), fmt_time(f)))
            updates.append((gspread.utils.rowcol_to_a1(row, sec["last_col"]), fmt_time(l)))
            updates.append((gspread.utils.rowcol_to_a1(row, sec["orders_col"]),
                            o if o is not None else 0))
        else:
            updates.append((gspread.utils.rowcol_to_a1(row, sec["first_col"]), NO_DATA_TIME))
            updates.append((gspread.utils.rowcol_to_a1(row, sec["last_col"]), NO_DATA_TIME))
            updates.append((gspread.utils.rowcol_to_a1(row, sec["orders_col"]), 0))
    rfill._retry(ws.batch_update,
                 [{"range": a1, "values": [[v]]} for a1, v in updates],
                 value_input_option="USER_ENTERED")
    return len(updates)


def fill_absent(ws, sec) -> int:
    """Owner not in upload — 'Not On Emailed Report' header (light-red bg
    + black bold text) and clear body cells."""
    updates: List[Tuple[str, Any]] = []
    header_a1 = None
    if sec["header_col"]:
        header_a1 = gspread.utils.rowcol_to_a1(sec["header_row"], sec["header_col"])
        updates.append((header_a1, NOT_ON_UPLOAD))
    for label, row in sec["body_rows"].items():
        updates.append((gspread.utils.rowcol_to_a1(row, sec["first_col"]), ""))
        updates.append((gspread.utils.rowcol_to_a1(row, sec["last_col"]), ""))
        updates.append((gspread.utils.rowcol_to_a1(row, sec["orders_col"]), ""))
    rfill._retry(ws.batch_update,
                 [{"range": a1, "values": [[v]]} for a1, v in updates],
                 value_input_option="USER_ENTERED")
    if header_a1 and sec["header_col"]:
        sheet_id = ws._properties["sheetId"]
        req = {"repeatCell": {
            "range": {"sheetId": sheet_id,
                      "startRowIndex": sec["header_row"] - 1,
                      "endRowIndex": sec["header_row"],
                      "startColumnIndex": sec["header_col"] - 1,
                      "endColumnIndex": sec["header_col"]},
            "cell": {"userEnteredFormat": {
                "backgroundColor": LIGHT_RED,
                "backgroundColorStyle": {"rgbColor": LIGHT_RED},
                "textFormat": {
                    "foregroundColor": BLACK,
                    "foregroundColorStyle": {"rgbColor": BLACK},
                    "bold": True,
                }}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.backgroundColorStyle,"
                       "userEnteredFormat.textFormat.foregroundColor,"
                       "userEnteredFormat.textFormat.foregroundColorStyle,"
                       "userEnteredFormat.textFormat.bold"),
        }}
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [req]})
    return len(updates)


def fill_for_tab(sh, ws, week: dt.date, parsed: Dict[str, dict],
                 aliases_map: Dict[str, List[str]],
                 src_chart_bounds: Tuple[int, int, int, int],
                 src_sheet_id: int, dry_run: bool = False) -> Dict[str, Any]:
    """Process one tab. Returns a result dict with status + counts."""
    tab = ws.title
    if tab in EXPECTED_NO_SECTION:
        return {"tab": tab, "status": "EXPECTED_NO_SECTION"}
    sheet_id = ws._properties["sheetId"]
    grid = rfill._retry(ws.get_all_values)
    sec = find_section(grid)
    if not sec or not sec["body_rows"]:
        return {"tab": tab, "status": "NO_SECTION"}

    # Ensure all 8 day rows exist (insert if needed)
    initial = set(sec["body_rows"].keys())
    sec = insert_missing_days(sh, ws, sheet_id)
    after = set(sec["body_rows"].keys())
    inserted = sorted(after - initial, key=lambda d: DAYS_FULL.index(d))

    owner = find_owner(tab, parsed, aliases_map)
    dst_bounds = section_bounds(sec)
    same_shape = ((dst_bounds[1] - dst_bounds[0]) ==
                  (src_chart_bounds[1] - src_chart_bounds[0])) and \
                 ((dst_bounds[3] - dst_bounds[2]) ==
                  (src_chart_bounds[3] - src_chart_bounds[2]))
    fmt_status = "skip"
    if same_shape and not dry_run:
        req = copyfmt_request(src_sheet_id, src_chart_bounds,
                              sheet_id, dst_bounds)
        rfill._retry(sh.batch_update, {"requests": [req]})
        fmt_status = "copied"

    if owner:
        n = fill_present(ws, sec, week, owner) if not dry_run else 0
        return {"tab": tab, "status": "OK", "channel": owner.get("channel"),
                "cells": n, "inserted": inserted, "fmt": fmt_status}
    else:
        n = fill_absent(ws, sec) if not dry_run else 0
        return {"tab": tab, "status": "ABSENT", "cells": n,
                "inserted": inserted, "fmt": fmt_status}

"""Captainship Activations tab writer — daily Wed-Tue fill.

All anchor rows + metric cells are resolved by label lookup (per CLAUDE.md:
'No hardcoded rows or columns'). Survives the row insertion that happens
every Wednesday.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import gspread

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB_NAME = "Captainship Activations"

AVG_LABEL = "Last 4 week AVG"
CHURN_LABEL = "60 Day Churn"
ROLLING_LABEL = "Approval / Activation Rate"

# Sheet day-of-week → col letter (Wed-Tue cycle).
# Python weekday(): Mon=0, Tue=1, Wed=2, ...
DOW_TO_PURPLE_COL = {2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 0: "G", 1: "H"}
DOW_TO_ORANGE_COL = {2: "R", 3: "S", 4: "T", 5: "U", 6: "V", 0: "W", 1: "X"}

# Fixed columns in the schema (purple / orange charts).
COL_WE_PURPLE = "A"
COL_RAF_EOW_SALES = "I"
COL_ACTIVATIONS_PURPLE = "J"
COL_PCT_VS_LAST_PURPLE = "L"
COL_WE_ORANGE = "Q"
COL_COUNTRY_EOW_SALES = "Y"
COL_EST_REVENUE = "Z"


def _find_avg_row(ws: gspread.Worksheet) -> int:
    col_a = ws.col_values(1)
    for i, v in enumerate(col_a, 1):
        if v.strip() == AVG_LABEL:
            return i
    raise RuntimeError(f"Could not find '{AVG_LABEL}' row in col A")


def _find_metric_cells(ws: gspread.Worksheet, avg_row: int) -> dict:
    """Return {'churn_cell': 'G99', 'rolling_cell': 'H99'} (or shifted)."""
    # Look in the few rows after AVG for the labels.
    rng = ws.get(f"A{avg_row + 1}:L{avg_row + 12}",
                 value_render_option="FORMATTED_VALUE")
    churn_cell = rolling_cell = None
    for offset, row in enumerate(rng):
        for col_idx, cell in enumerate(row):
            label = (cell or "").strip()
            if label == CHURN_LABEL:
                col_letter = chr(ord("A") + col_idx)
                churn_cell = f"{col_letter}{avg_row + 1 + offset + 1}"
            elif label == ROLLING_LABEL:
                col_letter = chr(ord("A") + col_idx)
                rolling_cell = f"{col_letter}{avg_row + 1 + offset + 1}"
    if not churn_cell or not rolling_cell:
        raise RuntimeError(
            f"Couldn't find metric labels ('{CHURN_LABEL}', '{ROLLING_LABEL}') "
            f"in {TAB_NAME} below AVG row {avg_row}"
        )
    return {"churn_cell": churn_cell, "rolling_cell": rolling_cell}


def _cp_format(sheet_id, src_row, dst_row, col_start, col_end):
    """Helper: build a copyPaste request that copies CELL FORMAT only."""
    return {"copyPaste": {
        "source": {"sheetId": sheet_id,
                   "startRowIndex": src_row - 1, "endRowIndex": src_row,
                   "startColumnIndex": col_start, "endColumnIndex": col_end},
        "destination": {"sheetId": sheet_id,
                        "startRowIndex": dst_row - 1, "endRowIndex": dst_row,
                        "startColumnIndex": col_start, "endColumnIndex": col_end},
        "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL",
    }}


def _insert_new_we_row(ws: gspread.Worksheet, avg_row: int) -> int:
    """Insert a blank row at avg_row (pushes AVG down by 1). Sets col A formula
    to auto-increment WE date, clones the previous data row's formatting,
    strips inherited bold, and slides the rolling-4 A/Q date highlight forward
    by one week. AVG row formulas are NOT touched — Sheets' insert-row keeps
    formulas like =SUM(B90:B93)/4 intact (refs above the insertion point don't
    shift), and that range already matches the 'last 4 completed weeks'.

    Returns the new row number (= old avg_row)."""
    new_row = avg_row
    prev_data_row = avg_row - 1
    ws.insert_row([""] * 26, index=new_row)

    # Col A formula auto-increments WE Sunday by 7; Q mirrors A.
    # Col L: % activated vs last week = current week's J / previous week's I.
    #        IFERROR keeps the cell blank until Tuesday fills J.
    # Col Z: Estimated Revenue = (latest filled R..X) * 2 — dynamic, so each
    #        day during the cycle Z reflects today's country activation × 2.
    ws.batch_update([
        {"range": f"A{new_row}", "values": [[f"=A{prev_data_row}+7"]]},
        {"range": f"Q{new_row}", "values": [[f"=A{new_row}"]]},
        {"range": f"L{new_row}",
         "values": [[f'=IFERROR(J{new_row}/I{prev_data_row}, "")']]},
        {"range": f"Z{new_row}",
         "values": [[f'=IFERROR(INDEX(R{new_row}:X{new_row}, 1, '
                     f'COUNT(R{new_row}:X{new_row})) * 2, "")']]},
    ], value_input_option="USER_ENTERED")

    sheet_id = ws.id
    sh = ws.spreadsheet

    # Rolling-4 logic on each Wed insert at row R:
    #   - In-progress row R: A/Q NOT highlighted (just-inserted).
    #   - Row R-1 (just-completed): A/Q highlighted (joins last-4-completed).
    #   - Row R-5 (falls out of last-4-completed): A/Q de-highlighted.
    # Use R-6 as the canonical "outside the window" reference for un-highlight
    # and R-2 as a known-still-highlighted reference for re-highlight.
    A_COL, A_END = 0, 1     # col A
    Q_COL, Q_END = 16, 17   # col Q
    requests = [
        # 1. Whole-row format clone from prev_data_row → new_row.
        _cp_format(sheet_id, prev_data_row, new_row, 0, 26),
        # 2. Strip bold across the new row (AVG-row template leaks bold).
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id,
                          "startRowIndex": new_row - 1, "endRowIndex": new_row,
                          "startColumnIndex": 0, "endColumnIndex": 26},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": False}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        },
        # 3. New row A/Q (in-progress): copy un-highlighted format from R-6.
        _cp_format(sheet_id, new_row - 6, new_row, A_COL, A_END),
        _cp_format(sheet_id, new_row - 6, new_row, Q_COL, Q_END),
        # 4. Row R-1 (just-completed) A/Q: keep highlighted (re-stamp from R-2).
        _cp_format(sheet_id, new_row - 2, new_row - 1, A_COL, A_END),
        _cp_format(sheet_id, new_row - 2, new_row - 1, Q_COL, Q_END),
        # 5. Row R-5 (falls out of last-4-completed) A/Q: un-highlight (R-6).
        _cp_format(sheet_id, new_row - 6, new_row - 5, A_COL, A_END),
        _cp_format(sheet_id, new_row - 6, new_row - 5, Q_COL, Q_END),
        # 6. Re-bold the value cols on the new row (the whole-row unbold in
        #    step 2 wiped these; I/J/K/L and Y/Z are bold on every data row).
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id,
                          "startRowIndex": new_row - 1, "endRowIndex": new_row,
                          "startColumnIndex": 8, "endColumnIndex": 12},  # I..L
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id,
                          "startRowIndex": new_row - 1, "endRowIndex": new_row,
                          "startColumnIndex": 24, "endColumnIndex": 26},  # Y..Z
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        },
    ]
    sh.batch_update({"requests": requests})

    return new_row


def find_anchors_and_maybe_insert(
    ws: gspread.Worksheet,
    today: dt.date,
    dry_run: bool = True,
) -> dict:
    """Resolve all anchor positions. If today is Wednesday, also insert a new
    row above the AVG row (unless dry_run)."""
    avg_row = _find_avg_row(ws)
    data_row = avg_row - 1
    today_is_wed = today.weekday() == 2

    inserted = False
    if today_is_wed:
        if dry_run:
            inserted = "would_insert"
        else:
            data_row = _insert_new_we_row(ws, avg_row)
            avg_row += 1  # AVG row pushed down by 1
            inserted = True

    metrics = _find_metric_cells(ws, avg_row)
    return {
        "data_row": data_row,
        "avg_row": avg_row,
        "churn_cell": metrics["churn_cell"],
        "rolling_cell": metrics["rolling_cell"],
        "inserted_new_row": inserted,
    }


def write_daily(
    ws: gspread.Worksheet,
    anchors: dict,
    today: dt.date,
    raf_today_activations: int,
    country_today_activations: int,
    raf_eow_sales: int,
    country_eow_sales: int,
    raf_60d_churn: str,
    raf_rolling_4w: str,
    dry_run: bool = True,
) -> dict:
    """Write today's snapshot. Returns a dict of cells → values for logging."""
    dow = today.weekday()
    purple_col = DOW_TO_PURPLE_COL[dow]
    orange_col = DOW_TO_ORANGE_COL[dow]
    row = anchors["data_row"]

    writes = {
        f"{purple_col}{row}": raf_today_activations,
        f"{orange_col}{row}": country_today_activations,
        f"{COL_RAF_EOW_SALES}{row}": raf_eow_sales,
        f"{COL_COUNTRY_EOW_SALES}{row}": country_eow_sales,
        anchors["churn_cell"]: raf_60d_churn,
        anchors["rolling_cell"]: raf_rolling_4w,
    }

    # 'Activations' (col J) auto-fills with the LATEST non-empty day in this
    # row's Wed→Tue span (B:H) — the most recent daily cumulative available.
    # Written as a sheet formula (not a static value) so it tracks each day's
    # fill and any manual edits, regardless of which day the script last ran.
    # LOOKUP(<huge number>, range) returns the last NUMERIC cell in the range:
    # gap-safe (unlike INDEX+COUNT) for rows with a skipped day, and reliable
    # in Google Sheets (the 1/(range<>"") variant evaluates blank here). The
    # day cells are always numbers, so this lands on the most recent day. On
    # Tuesday that's H, preserving the historical H=J invariant.
    writes[f"{COL_ACTIVATIONS_PURPLE}{row}"] = (
        f'=IFERROR(LOOKUP(9.99999999999999E+307,B{row}:H{row}),"")'
    )

    if dry_run:
        return writes

    body = [{"range": cell, "values": [[v]]} for cell, v in writes.items()]
    ws.batch_update(body, value_input_option="USER_ENTERED")
    return writes

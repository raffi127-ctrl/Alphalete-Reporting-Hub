"""Write the sorted Schedules rows to a tab and color each Rep group.

The report OVERWRITES prior data every run (it's a daily snapshot, no history) —
so we clear the data region (row 2 down), write the fresh sorted rows, reset all
backgrounds to white, then paint each contiguous Rep group its gradient color.

Columns are matched to the tab's header row BY LABEL (never by fixed index), and
we only ever touch the two destination tabs — never the 'template' tab.
"""
from __future__ import annotations

from typing import Dict, List

import gspread

from automations.schedules_6_days_out import colors, pull

SHEET_ID = "1qUiljtWXhcy3OGhQ_81LnNPIsUXjad3MJi-VzjEIDV8"  # sandbox "VAs' Data"
TAB_RAF = "Schedules 6 days out (Raf)"
TAB_STARR = "Schedules 6 days out (Starr)"

_WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _header_index(header: List[str], label: str) -> int:
    """Index of `label` in the header row, by normalized match. -1 if absent."""
    target = _norm(label)
    for i, h in enumerate(header):
        if _norm(h) == target:
            return i
    return -1


def write_tab(sh, tab_name: str, rows: List[Dict[str, str]],
              dry_run: bool = False) -> dict:
    """Overwrite `tab_name`'s data with `rows` (already sorted by Rep) and
    color each Rep group. Returns a summary dict."""
    ws = sh.worksheet(tab_name)
    header = ws.row_values(1)
    ncols = max(len(header), len(pull.SHEET_COLUMNS))

    # Map each sheet column we emit onto a header position by label.
    col_pos = {sheet_col: _header_index(header, sheet_col)
               for sheet_col in pull.SHEET_COLUMNS}
    missing = [c for c, i in col_pos.items() if i < 0]

    # Build the value matrix in the tab's real column order.
    width = len(header) if header else len(pull.SHEET_COLUMNS)
    matrix: List[List[str]] = []
    for r in rows:
        line = [""] * width
        for sheet_col, pos in col_pos.items():
            if 0 <= pos < width:
                line[pos] = r.get(sheet_col, "")
        matrix.append(line)

    # How many old data rows are there (to clear past the new block)?
    grid = ws.get_all_values()
    old_data_rows = max(len(grid) - 1, 0)  # excludes header

    if dry_run:
        return {"tab": tab_name, "new_rows": len(rows),
                "old_rows_cleared": old_data_rows,
                "missing_header_cols": missing, "dry_run": True}

    last_col = gspread.utils.rowcol_to_a1(1, max(width, 1)).rstrip("1")

    # 1) Clear the old data region's VALUES (row 2 → old last row).
    if old_data_rows:
        ws.batch_clear([f"A2:{last_col}{old_data_rows + 1}"])

    # 2) Write the fresh rows starting at row 2.
    if matrix:
        ws.update(matrix, f"A2", value_input_option="USER_ENTERED")

    # 3) Repaint backgrounds: reset the whole (old ∪ new) data region to white,
    #    then color each contiguous Rep group. One batched API call.
    _paint(ws, rows, ncols=max(width, 1),
           clear_to_row=max(old_data_rows, len(rows)))

    return {"tab": tab_name, "new_rows": len(rows),
            "old_rows_cleared": old_data_rows, "missing_header_cols": missing}


def _paint(ws, rows: List[Dict[str, str]], *, ncols: int,
           clear_to_row: int, color_by: str = "Owner Name") -> None:
    """Reset data backgrounds to white, then paint each `color_by` group its
    gradient color. Rows are pre-sorted by Owner Name, so each group is a
    contiguous block."""
    requests = [{
        "repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 1,
                      "endRowIndex": 1 + max(clear_to_row, 0),
                      "startColumnIndex": 0, "endColumnIndex": ncols},
            "cell": {"userEnteredFormat": {"backgroundColor": _WHITE}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    }]

    group_color = colors.gradient_for_groups(
        [r.get(color_by, "") for r in rows])
    # Walk contiguous color-key groups.
    start = 0
    while start < len(rows):
        key = rows[start].get(color_by, "")
        end = start
        while end + 1 < len(rows) and rows[end + 1].get(color_by, "") == key:
            end += 1
        bg = colors.rgb01_to_sheet(group_color[key])
        requests.append({
            "repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": 1 + start, "endRowIndex": 2 + end,
                          "startColumnIndex": 0, "endColumnIndex": ncols},
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
        start = end + 1

    if requests:
        ws.spreadsheet.batch_update({"requests": requests})

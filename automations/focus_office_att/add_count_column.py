"""Add (or normalize) the row-count column at A on every tab.

Behavior per tab:
  - If col A already has the count (header '#' or any numeric/formula
    content in rows 3+), just normalize: re-write the formula, header,
    and styling so it matches Cody's design.
  - Otherwise: insert a new col A, set the formula + header + style.

Style:
  - Header cell A2 = '#', bold + centered + pale-blue header color
  - Rows 3-200 = formula '=ROW()-2'
  - Background: matches Rep Name col (pale gray)
  - Centered + bold

After this runs, every tab has the same layout: col A = count,
col B = Rep Name, col C onwards = the data cols.

Run:
    .venv/bin/python -m automations.focus_office_att.add_count_column
"""
from __future__ import annotations

import sys

from automations.recruiting_report import fill as _fill

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"

REP_NAME_BG = {"red": 0.94, "green": 0.95, "blue": 0.97}      # matches Rep Name rail
HEADER_ROW2_BG = {"red": 0.85, "green": 0.89, "blue": 0.95}    # pale blue (matches row 2 headers)
HEADER_ROW2_FG = {"red": 0.10, "green": 0.15, "blue": 0.25}


def _has_count_column(ws) -> bool:
    """Detect whether col A is already a count column."""
    a_vals = ws.col_values(1)[:6]
    # Header '#' OR row 3+ has a digit/formula (=ROW...)
    if len(a_vals) >= 2 and a_vals[1].strip() == "#":
        return True
    if len(a_vals) >= 3 and a_vals[2].strip() and (a_vals[2].strip().isdigit() or a_vals[2].startswith("=")):
        return True
    return False


def add_or_normalize_count_col(ws) -> str:
    """Returns 'inserted' or 'normalized' depending on what action was taken."""
    sheet_id = ws.id
    already_present = _has_count_column(ws)
    requests = []
    if not already_present:
        # Insert a new col at position A (shifts everything right by 1)
        requests.append({
            "insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 1,
                },
                "inheritFromBefore": False,
            },
        })
    # Set header cell A2 = '#'
    requests.append({
        "updateCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1, "endRowIndex": 2,         # row 2
                "startColumnIndex": 0, "endColumnIndex": 1,
            },
            "rows": [{"values": [{
                "userEnteredValue": {"stringValue": "#"},
                "userEnteredFormat": {
                    "backgroundColor": HEADER_ROW2_BG,
                    "textFormat": {"bold": True, "foregroundColor": HEADER_ROW2_FG, "fontSize": 9},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                },
            }]}],
            "fields": "userEnteredValue,userEnteredFormat",
        },
    })
    # Set formula across rows 3-200: only number a row when col B (Rep Name)
    # has a value — keeps the count from running past the last rep.
    formula_rows = []
    for r in range(3, 201):  # rows 3..200 inclusive
        formula_rows.append({"values": [{
            "userEnteredValue": {"formulaValue": f'=IF($B{r}="","",ROW()-2)'},
            "userEnteredFormat": {
                "backgroundColor": REP_NAME_BG,
                "textFormat": {"bold": True, "fontSize": 11},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "numberFormat": {"type": "NUMBER", "pattern": "0"},
            },
        }]})
    requests.append({
        "updateCells": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 2, "endRowIndex": 200,
                "startColumnIndex": 0, "endColumnIndex": 1,
            },
            "rows": formula_rows,
            "fields": "userEnteredValue,userEnteredFormat",
        },
    })
    # Auto-resize col A to fit the numbers (narrow)
    requests.append({
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": 1,
            },
        },
    })
    ws.spreadsheet.batch_update({"requests": requests})
    return "normalized" if already_present else "inserted"


def main() -> int:
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    tabs = sh.worksheets()
    print(f"adding/normalizing count column on {len(tabs)} tab(s)…")
    for ws in tabs:
        try:
            action = add_or_normalize_count_col(ws)
            print(f"  ✓ {ws.title} ({action})")
        except Exception as e:
            print(f"  ✗ {ws.title}: {type(e).__name__}: {str(e)[:120]}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

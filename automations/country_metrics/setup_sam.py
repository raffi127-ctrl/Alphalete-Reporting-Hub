"""One-time: add a SAM captainship section to the Country Metrics tab.

Clones an existing captainship block (WAYNE) so SAM gets the same layout,
borders, formula cells (Sales (ALL), AVG Units, % of Owners over 100) and
labels; recolors the SAM header a distinct color; clears the copied data so
SAM starts empty; and extends COUNTRY's owner-sum formulas (Total Owners,
Owners Over 100) to include SAM — so COUNTRY's Grand Total keeps matching
Tableau (which counts Sam's Team).

Re-runnable: if a SAM section already exists, it does nothing.

    python -m automations.country_metrics.setup_sam
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE))

from automations.recruiting_report import fill as rfill  # noqa: E402

# Real Sheet ('ATT Program - Focus Report'), official 'Country Metrics' tab
# (the prior one is archived as '_Country Metrics (OLD)') — Eve, 2026-05-28.
SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"
TAB = "Country Metrics"

CLONE_FROM = "WAYNE"        # existing captainship block to mirror
NEW_SECTION = "SAM"
GAP_ROWS = 3               # blank rows between sections (matches the others)
BLOCK_ROWS = 18            # header + 17 metric rows
N_COLS = 85               # A..CG (the full used width)

# Distinct header color for SAM — pink #E91E63, the one hue not used by the
# other sections (gold / teal / periwinkle / taupe / green / orange). The old
# teal was too close to RAF's teal (Eve, 2026-05-28).
SAM_COLOR = {"red": 0.9137255, "green": 0.1176471, "blue": 0.3882353}

# Row offsets inside a section block (0 = the section-name/date header row).
OFF_FIRST_METRIC = 1       # Rolling 4 weeks
OFF_WIRELESS = 12          # last product row (AT&T AIR is offset 11, left blank)
OFF_TOTAL_OWNERS = 14
OFF_OWNERS_OVER_100 = 16


def _col_a1(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _find_row(col_a: list[str], label: str):
    for i, v in enumerate(col_a):
        if str(v).strip().upper() == label.upper():
            return i + 1  # 1-based
    return None


def _header_colored_cols(sh, gid_unused, a1_range: str) -> list[int]:
    """0-based column indices in `a1_range` (a single row) that have a
    non-white background — i.e. the header's colored band."""
    resp = sh.client.request(
        "get",
        f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
        params={"ranges": a1_range, "includeGridData": "true",
                "fields": "sheets/data/rowData/values/effectiveFormat/backgroundColor"},
    )
    data = resp.json()
    try:
        row = data["sheets"][0]["data"][0]["rowData"][0]["values"]
    except (KeyError, IndexError):
        return []
    cols = []
    for j, cell in enumerate(row):
        bg = (cell.get("effectiveFormat") or {}).get("backgroundColor") or {}
        r, g, b = bg.get("red", 1), bg.get("green", 1), bg.get("blue", 1)
        if not (r > 0.95 and g > 0.95 and b > 0.95):
            cols.append(j)
    return cols


def main() -> int:
    sh = rfill.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB)
    gid = ws.id

    col_a = ws.col_values(1)

    if _find_row(col_a, NEW_SECTION):
        print(f"'{NEW_SECTION}' section already exists — nothing to do.")
        return 0

    clone_row = _find_row(col_a, CLONE_FROM)
    country_row = _find_row(col_a, "COUNTRY")
    if not clone_row or not country_row:
        print(f"!! couldn't find '{CLONE_FROM}' and/or 'COUNTRY' in column A")
        return 1

    sam_row = clone_row + BLOCK_ROWS + GAP_ROWS
    print(f"clone '{CLONE_FROM}' rows {clone_row}-{clone_row + BLOCK_ROWS - 1} "
          f"-> '{NEW_SECTION}' at row {sam_row}")

    # 1) Copy the whole block (format + borders + formulas + labels + data).
    sh.batch_update({"requests": [{
        "copyPaste": {
            "source": {"sheetId": gid,
                       "startRowIndex": clone_row - 1, "endRowIndex": clone_row - 1 + BLOCK_ROWS,
                       "startColumnIndex": 0, "endColumnIndex": N_COLS},
            "destination": {"sheetId": gid,
                            "startRowIndex": sam_row - 1, "endRowIndex": sam_row - 1 + BLOCK_ROWS,
                            "startColumnIndex": 0, "endColumnIndex": N_COLS},
            "pasteType": "PASTE_NORMAL",
        }
    }]})

    # 2) Rename the section header.
    ws.update(values=[[NEW_SECTION]], range_name=f"A{sam_row}")

    # 3) Clear the copied DATA (keep labels in col A, the date header row, and
    #    the three formula rows: Sales (ALL), AVG Units, % of Owners over 100).
    last = _col_a1(N_COLS)
    ws.batch_clear([
        f"B{sam_row + OFF_FIRST_METRIC}:{last}{sam_row + OFF_WIRELESS}",
        f"B{sam_row + OFF_TOTAL_OWNERS}:{last}{sam_row + OFF_TOTAL_OWNERS}",
        f"B{sam_row + OFF_OWNERS_OVER_100}:{last}{sam_row + OFF_OWNERS_OVER_100}",
    ])

    # 4) Recolor the SAM header band a distinct color (same cells the clone
    #    colors, so the look matches but the hue differs).
    band = _header_colored_cols(sh, gid, f"{TAB}!A{clone_row}:{last}{clone_row}")
    if band:
        lo, hi = min(band), max(band) + 1
    else:
        lo, hi = 0, 1  # fall back to just the name cell
    sh.batch_update({"requests": [{
        "repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": sam_row - 1, "endRowIndex": sam_row,
                      "startColumnIndex": lo, "endColumnIndex": hi},
            "cell": {"userEnteredFormat": {"backgroundColor": SAM_COLOR}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    }]})
    print(f"recolored header cols {_col_a1(lo+1)}..{_col_a1(hi)} teal")

    # 5) Extend COUNTRY's owner-sum formulas to include SAM's cells, across
    #    every week column that already carries the formula.
    updates = []
    for off, label in ((OFF_TOTAL_OWNERS, "Total Owners"), (OFF_OWNERS_OVER_100, "Owners Over 100")):
        co_row = country_row + off
        sam_row_n = sam_row + off
        formulas = ws.get_values(f"B{co_row}:{last}{co_row}", value_render_option="FORMULA")
        formulas = formulas[0] if formulas else []
        n_ext = 0
        for k, f in enumerate(formulas):
            colL = _col_a1(k + 2)  # B = column 2
            sam_cell = f"{colL}{sam_row_n}"
            if isinstance(f, str) and f.startswith("=") and f.rstrip().endswith(")") and sam_cell not in f:
                new = f.rstrip()[:-1] + f",{sam_cell})"
                updates.append({"range": f"{colL}{co_row}", "values": [[new]]})
                n_ext += 1
        print(f"  COUNTRY {label} (row {co_row}): extending {n_ext} column formulas to +{NEW_SECTION}")
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

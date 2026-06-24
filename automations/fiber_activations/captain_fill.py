"""Per-captain tab writer — value-only, format-untouched.

Differences vs Rafael's automations.fiber_activations.fill:
  - Writes BOTH the violet (captain) and orange (country) day cells. Country is
    the SAME global numbers written into all 5 tabs each run.
  - Z (Estimated Revenue) is never written — it's a per-row formula.
  - The Wednesday row insert is STRUCTURE-ONLY: insert inheriting the row above's
    format (the captain's own color, via inherit_from_before=True), set the A/Q
    WE date + the L/Z formulas, and NOTHING else. ZERO format operations — the
    conditional-format rule slides the rolling-4 highlight on its own, banding
    auto-extends, and the captain color is inherited. Row 8 (AVG) is never
    touched (its OFFSET formula re-derives the 4-week window after the insert).

Anchor lookup (AVG row, WE row, churn/appr metric cells) is reused verbatim from
fill.py — all label/date based, no hardcoded rows.
"""
from __future__ import annotations

import datetime as dt

import gspread

from automations.fiber_activations import fill as F   # reuse Raf's anchor logic
from automations.fiber_activations.pull import cycle_sunday

# Fixed schema columns (shared with Raf's layout).
COL_VIOLET_EOW = "I"          # Total EOW Captainship Sales (per captain)
COL_VIOLET_ACTIVATIONS = "J"  # Activations (=LOOKUP formula)
COL_COUNTRY_EOW = "Y"         # Total Country Sales (global)


def _insert_we_row_structure_only(ws: gspread.Worksheet, avg_row: int) -> int:
    """Insert ONE blank WE row at `avg_row` (pushes AVG down by 1), inheriting
    the format of the row above (the captain's color) via inherit_from_before.
    Sets only the A/Q WE date and the L/% + Z/revenue formulas (value-entries,
    not format). NO copyPaste / repeatCell / color ops. Returns the new row."""
    new_row = avg_row
    prev = avg_row - 1
    # inherit_from_before=True → new row copies format from row `prev` (above),
    # which carries the captain's banding/accents. Without it, gspread inherits
    # from the row BELOW (the AVG row) and leaks AVG formatting.
    ws.insert_row([""] * 26, index=new_row,
                  value_input_option="USER_ENTERED", inherit_from_before=True)
    ws.batch_update([
        {"range": f"A{new_row}", "values": [[f"=A{prev}+7"]]},
        {"range": f"Q{new_row}", "values": [[f"=A{new_row}"]]},
        {"range": f"L{new_row}",
         "values": [[f'=IFERROR(J{new_row}/I{prev}, "")']]},
        {"range": f"Z{new_row}",
         "values": [[f'=IFERROR(INDEX(R{new_row}:X{new_row}, 1, '
                     f'COUNT(R{new_row}:X{new_row})) * 2, "")']]},
    ], value_input_option="USER_ENTERED")
    return new_row


def find_anchors(ws: gspread.Worksheet, today: dt.date,
                 dry_run: bool = True) -> dict:
    """Resolve data row (by WE date), AVG row, and churn/appr metric cells.
    Inserts a structure-only row if this cycle's WE row doesn't exist yet."""
    avg_row = F._find_avg_row(ws)
    we_sunday = cycle_sunday(today)
    existing = F._find_we_row(ws, we_sunday, avg_row)

    inserted = False
    if existing is not None:
        data_row = existing            # idempotent: write to the existing row
    elif dry_run:
        data_row = avg_row - 1
        inserted = "would_insert"
    else:
        data_row = _insert_we_row_structure_only(ws, avg_row)
        avg_row += 1                   # AVG pushed down by the insert
        inserted = True

    metrics = F._find_metric_cells(ws, avg_row)
    return {
        "data_row": data_row,
        "avg_row": avg_row,
        "churn_cell": metrics["churn_cell"],
        "rolling_cell": metrics["rolling_cell"],
        "inserted_new_row": inserted,
    }


def write_tab(
    ws: gspread.Worksheet,
    anchors: dict,
    today: dt.date,
    *,
    cap_activations: int,
    cap_eow: int,
    churn: str,
    appr: str,
    country_activations: int,
    country_eow: int,
    dry_run: bool = True,
) -> dict:
    """Write one captain tab: violet (captain) + orange (country) day cells.
    Z is left to its formula; row 8 is never touched. Returns cells->values."""
    dow = today.weekday()
    purple_col = F.DOW_TO_PURPLE_COL[dow]
    orange_col = F.DOW_TO_ORANGE_COL[dow]
    row = anchors["data_row"]

    writes = {
        # --- violet (this captain) ---
        f"{purple_col}{row}": cap_activations,
        f"{COL_VIOLET_EOW}{row}": cap_eow,
        f"{COL_VIOLET_ACTIVATIONS}{row}":
            f'=IFERROR(LOOKUP(9.99999999999999E+307,B{row}:H{row}),"")',
        anchors["churn_cell"]: churn,
        anchors["rolling_cell"]: appr,
        # --- orange (global country, same in all 5 tabs) ---
        f"{orange_col}{row}": country_activations,
        f"{COL_COUNTRY_EOW}{row}": country_eow,
    }

    if dry_run:
        return writes
    body = [{"range": cell, "values": [[v]]} for cell, v in writes.items()]
    ws.batch_update(body, value_input_option="USER_ENTERED")
    return writes

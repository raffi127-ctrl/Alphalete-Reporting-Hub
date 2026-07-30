"""Primitives for stamping a fixed cell style onto a Sheets range.

Why stamping instead of copying yesterday's column
--------------------------------------------------
Every one-column-per-day report in here opens today's column by inserting it at
B and then copyPaste-ing the previous day's formatting onto it. That drifts.
Sheets stores a border ONCE for the two cells that share it, so painting a thick
right edge on column C silently clears column D's left edge; tomorrow's copy
inherits the cleared version, and the grid decays a little every morning until a
human re-formats the tab by hand (Eve, on the ABP tab, 2026-07-30).

A report that declares its style as data and re-stamps it after each insert
cannot drift: every day's column comes out byte-identical no matter what the
column beside it looks like.

These are only the building blocks — each report owns its own STYLE table,
because the tabs genuinely differ (Raf's ABP tab is Georgia on black, his
captainship tabs are Calibri on dark green, Rashad's is yellow with no borders).
"""
from __future__ import annotations

# Explicit zeros, never {}: the Sheets API drops zero-valued fields on the wire,
# so a bare {} round-trips as "unset" in some readers but IS pure black here.
BLACK = {"red": 0.0, "green": 0.0, "blue": 0.0}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}

# The mask to send with a repeatCell built by cell(): every property cell()
# can set, so anything the payload omits is CLEARED rather than left behind.
FORMAT_FIELDS = ("userEnteredFormat(backgroundColor,borders,"
                 "horizontalAlignment,verticalAlignment,textFormat,"
                 "numberFormat,wrapStrategy)")

_WIDTHS = {"SOLID": 1, "SOLID_MEDIUM": 2, "SOLID_THICK": 3, "DOTTED": 1,
           "DASHED": 1, "DOUBLE": 3}


def borders(**edges) -> dict:
    """borders(top='SOLID', right='SOLID_THICK') -> a borders payload."""
    return {k: {"style": v, "width": _WIDTHS[v]} for k, v in edges.items()}


def text(font: str, size: int, *, bold: bool = False,
         color: dict | None = None) -> dict:
    tf = {"fontFamily": font, "fontSize": size, "bold": bold}
    if color is not None:
        tf["foregroundColor"] = color
    return tf


def cell(*, bg: dict, borders: dict, font: str, size: int, bold: bool = False,
         fg: dict | None = None, number: dict | None = None,
         wrap: bool = False, halign: str = "CENTER",
         valign: str = "MIDDLE") -> dict:
    """One fully-specified userEnteredFormat, for use with FORMAT_FIELDS."""
    fmt = {
        "backgroundColor": bg,
        "borders": borders,
        "horizontalAlignment": halign,
        "verticalAlignment": valign,
        "textFormat": text(font, size, bold=bold, color=fg),
        "wrapStrategy": "WRAP" if wrap else "OVERFLOW_CELL",
    }
    if number:
        fmt["numberFormat"] = number
    return fmt


def repeat_cell(sheet_id: int, fmt: dict, *, row_start_0: int, row_end_0: int,
                col_start_0: int, col_end_0: int) -> dict:
    """A repeatCell request applying `fmt` (and clearing everything else it
    could have set) over a half-open, 0-indexed rectangle."""
    return {"repeatCell": {
        "range": {"sheetId": sheet_id,
                  "startRowIndex": row_start_0, "endRowIndex": row_end_0,
                  "startColumnIndex": col_start_0, "endColumnIndex": col_end_0},
        "cell": {"userEnteredFormat": fmt},
        "fields": FORMAT_FIELDS}}

"""ABP % color thresholds — single source of truth for both the rendered
image and the sheet's conditional formatting.

Higher ABP% is better (opposite of churn). PROPOSED defaults (Megan
2026-07-10, pending Raf's real target bands):
    green  : pct >= 85%
    yellow : 75% <= pct < 85%
    red    : pct < 75%
Change GREEN_MIN / YELLOW_MIN here and both the PNG and the sheet update.
"""
from __future__ import annotations

from typing import Optional

GREEN_MIN = 85.0   # >= this → green
YELLOW_MIN = 75.0  # >= this (and < GREEN_MIN) → yellow; below → red

# RGB for the image (match churn's palette)
_GREEN = (147, 196, 125)
_YELLOW = (255, 217, 102)
_RED = (224, 102, 102)
_WHITE = (255, 255, 255)


def band_for(pct_value: float) -> str:
    if pct_value >= GREEN_MIN:
        return "green"
    if pct_value >= YELLOW_MIN:
        return "yellow"
    return "red"


def band_color_rgb(pct_str: str):
    """Band color for a '66.7%' string. Blank/unparseable → white."""
    s = (pct_str or "").strip().rstrip("%")
    if not s:
        return _WHITE
    try:
        v = float(s)
    except ValueError:
        return _WHITE
    return {"green": _GREEN, "yellow": _YELLOW, "red": _RED}[band_for(v)]


def _rgb01(rgb):
    return {"red": rgb[0] / 255, "green": rgb[1] / 255, "blue": rgb[2] / 255}


def conditional_format_requests(sheet_id: int, start_row_0: int,
                                end_row_0: int, end_col_0: int = 200) -> list:
    """Three addConditionalFormatRule requests for the %-columns over the
    given row band. pct is stored as a FRACTION (0.85), so thresholds are
    /100. First matching rule wins → green, then yellow, then red. Blanks
    (no number) match none → stay white.

    The range spans B..end_col_0 (ALL date columns, present + future) so a
    daily column-insert at B keeps every %-column covered — the rule
    re-evaluates each cell's OWN value, so colors never carry stale
    (Megan 2026-07-10). The interleaved units columns hold text like
    '3/5', which NUMBER conditions skip, so they stay uncolored."""
    g = GREEN_MIN / 100.0
    y = YELLOW_MIN / 100.0
    rng = {"sheetId": sheet_id, "startRowIndex": start_row_0,
           "endRowIndex": end_row_0, "startColumnIndex": 1,
           "endColumnIndex": end_col_0}

    def rule(cond, rgb, idx):
        return {"addConditionalFormatRule": {"index": idx, "rule": {
            "ranges": [rng],
            "booleanRule": {
                "condition": cond,
                "format": {"backgroundColor": _rgb01(rgb)},
            }}}}

    return [
        rule({"type": "NUMBER_GREATER_THAN_EQ",
              "values": [{"userEnteredValue": str(g)}]}, _GREEN, 0),
        rule({"type": "NUMBER_GREATER_THAN_EQ",
              "values": [{"userEnteredValue": str(y)}]}, _YELLOW, 1),
        rule({"type": "NUMBER_LESS",
              "values": [{"userEnteredValue": str(y)}]}, _RED, 2),
    ]

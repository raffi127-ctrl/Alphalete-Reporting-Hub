"""Per-Rep gradient palette, shared by fill.py (Sheet cells) and render.py
(the PNG) so the screenshot matches the Sheet exactly.

Spec (Eve): sort rows alphabetically by Rep, give each distinct Rep its OWN
soft (non-strident) color, arranged as an ASCENDING gradient down the list.

We sample N evenly-spaced points along a low-saturation, high-lightness HSV
sweep. Low saturation + high value = pastel, never harsh. Adjacent Reps differ
by a steady hue step, so the table reads as a gentle gradient top→bottom.
"""
from __future__ import annotations

import colorsys
from typing import List, Tuple

# Hue sweep range (fraction of the wheel). 0.58→0.06 walks blue → teal → green →
# yellow → soft orange: a calm, warm-leaning gradient that stays readable with
# black text. Kept off the harsh red/magenta end on purpose.
_HUE_START = 0.58
_HUE_END = 0.06
_SATURATION = 0.28   # low = pastel, not strident
_VALUE = 0.97        # bright so black text stays legible


def gradient_rgb01(n: int) -> List[Tuple[float, float, float]]:
    """Return `n` pastel (r, g, b) tuples in 0..1, evenly spaced along the
    gradient. n<=0 → []. n==1 → a single mid-gradient color."""
    if n <= 0:
        return []
    if n == 1:
        hues = [(_HUE_START + _HUE_END) / 2]
    else:
        step = (_HUE_END - _HUE_START) / (n - 1)
        hues = [_HUE_START + step * i for i in range(n)]
    return [colorsys.hsv_to_rgb(h % 1.0, _SATURATION, _VALUE) for h in hues]


def gradient_for_groups(values_in_order: List[str]) -> dict:
    """Map each DISTINCT group value (first-seen order — callers pass an
    already-sorted row list so colors run as an ascending gradient) to its
    gradient color (r, g, b) in 0..1. The group key is whatever the caller
    colors by: Owner Name for a full-captainship table, Rep for a single-owner
    table."""
    distinct: List[str] = []
    for v in values_in_order:
        if v not in distinct:
            distinct.append(v)
    palette = gradient_rgb01(len(distinct))
    return {v: palette[i] for i, v in enumerate(distinct)}


# Back-compat alias (fill.py / older callers): coloring by Rep is just the
# generic group-coloring with Rep as the key.
gradient_for_reps = gradient_for_groups


def rgb01_to_sheet(c: Tuple[float, float, float]) -> dict:
    """(r,g,b) 0..1 → gspread/Sheets API backgroundColor dict."""
    return {"red": c[0], "green": c[1], "blue": c[2]}


def rgb01_to_255(c: Tuple[float, float, float]) -> Tuple[int, int, int]:
    """(r,g,b) 0..1 → 0..255 int tuple for PIL."""
    return (round(c[0] * 255), round(c[1] * 255), round(c[2] * 255))

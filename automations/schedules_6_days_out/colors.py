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


# ---------------------------------------------------------------------------
# Family palette — owners are grouped into color FAMILIES (greens, blues,
# ambers, lavenders, …). Owners near each other in the list share a family;
# each owner gets a unique shade WITHIN its family. Keeps the table from looking
# saturated with colors while still letting you tell every owner apart.
# ---------------------------------------------------------------------------

# Base hue per family, ordered so adjacent families look clearly different.
_FAMILIES = [
    0.33,  # green
    0.60,  # blue
    0.12,  # amber / yellow-orange
    0.78,  # lavender / soft purple
    0.47,  # teal
    0.95,  # rose / pink
]
# Owners per family before rotating to the next family.
_FAMILY_SIZE = 4

# Shade spread WITHIN a family (light→deep). All stay pastel and keep black
# text legible (value never drops below ~0.76). The small hue nudge gives the
# "mint vs olive" feel the spec describes for the green family.
_SAT_MIN, _SAT_MAX = 0.16, 0.44
_VAL_MAX, _VAL_MIN = 0.98, 0.82
_HUE_SPREAD = 0.05


def family_palette(values_in_order: List[str],
                   family_size: int = _FAMILY_SIZE) -> dict:
    """Map each DISTINCT group value (first-seen order) to a pastel (r,g,b) in
    0..1, grouping consecutive values into color families and giving each a
    unique shade within its family."""
    distinct: List[str] = []
    for v in values_in_order:
        if v not in distinct:
            distinct.append(v)

    out = {}
    for i, v in enumerate(distinct):
        fam = (i // family_size) % len(_FAMILIES)
        shade = i % family_size
        # Normalized shade position 0..1 (light → deep) — works for any size.
        t = shade / max(family_size - 1, 1)
        hue = _FAMILIES[fam] + (t - 0.5) * _HUE_SPREAD
        sat = _SAT_MIN + t * (_SAT_MAX - _SAT_MIN)
        val = _VAL_MAX - t * (_VAL_MAX - _VAL_MIN)
        out[v] = colorsys.hsv_to_rgb(hue % 1.0, sat, val)
    return out


def rgb01_to_sheet(c: Tuple[float, float, float]) -> dict:
    """(r,g,b) 0..1 → gspread/Sheets API backgroundColor dict."""
    return {"red": c[0], "green": c[1], "blue": c[2]}


def rgb01_to_255(c: Tuple[float, float, float]) -> Tuple[int, int, int]:
    """(r,g,b) 0..1 → 0..255 int tuple for PIL."""
    return (round(c[0] * 255), round(c[1] * 255), round(c[2] * 255))

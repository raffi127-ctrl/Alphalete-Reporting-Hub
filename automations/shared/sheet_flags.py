"""Universal 'fill-but-flag' helper (Megan 2026-05-25).

Policy across every report: FILL whatever the data is — never blank a value and
never silently write a clean-looking wrong number. When a value looks off, write
it AND turn the cell font RED so a human eyeballs it. This module is the shared
primitive: a weird-value checker + a red-font applier.
"""
from __future__ import annotations

from typing import List, Optional

# Bold red, readable on white. Used for any flagged cell.
RED = {"red": 0.85, "green": 0.12, "blue": 0.12}
_RED_FMT = {"textFormat": {"foregroundColor": RED, "bold": True}}


def looks_weird_pct(value) -> bool:
    """True when a PERCENTAGE value is outside 0–100% — the universal
    'this can't be right' signal (e.g. a Fiber penetration of 377%: more sales
    than leads). Only flags values that came in as a percent string ('377.73%'),
    so a plain count like 256 is never mis-flagged."""
    if value is None:
        return False
    raw = str(value).strip()
    if "%" not in raw:
        return False
    try:
        n = float(raw.replace("%", "").replace(",", ""))
    except ValueError:
        return False
    return n > 100 or n < 0


def apply_red_font(ws, a1_cells: List[str], retry=None) -> None:
    """Set each A1 cell's font to bold red. `retry` is an optional wrapper
    (e.g. recruiting_report.fill._retry) for 429 backoff. Best-effort — a
    formatting failure never blocks the data write that already happened."""
    for a1 in a1_cells:
        try:
            if retry:
                retry(ws.format, a1, _RED_FMT)
            else:
                ws.format(a1, _RED_FMT)
        except Exception:
            pass


def clear_font(ws, a1_cells: List[str], retry=None) -> None:
    """Reset a cell's font to default black (used when a previously-weird value
    becomes normal on a later run, so a stale red flag doesn't linger)."""
    fmt = {"textFormat": {"foregroundColor": {"red": 0, "green": 0, "blue": 0},
                          "bold": False}}
    for a1 in a1_cells:
        try:
            if retry:
                retry(ws.format, a1, fmt)
            else:
                ws.format(a1, fmt)
        except Exception:
            pass

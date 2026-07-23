"""Number pulls for the override-bulletin fill (phases 2-4).

Each function fetches ONE piece of the weekly override for a given week and
returns a plain {normalized_owner_name: amount} dict (or a scalar for the
Raf-only pieces), so fill.py can assemble section-1/section-2 and report anyone
it can't match. See FILL_SOURCES.md for the full spec.

WEEK KEYS. The override sheet labels weeks m.d.yy ("7.12.26"). Sources use their
own conventions (Raf PNL "WE 7/12"; DD Detail runs a day behind). Each pull maps
the sheet's week to its source internally; callers pass the sheet label.

The Tableau pulls MUST run on Lucy 1 (Raf's login — only Raf's org views see the
whole downline) and are built on download_crosstab_patchright. The Raf-PNL pull
below is a plain Google-Sheets read and runs anywhere.
"""
from __future__ import annotations

import datetime as dt


def _norm_name(s: str) -> str:
    """Fold a person name for matching across sources: drop any '[office]' /
    '(office)' suffix, lowercase, collapse whitespace. 'CARLOS HIDALGO [alphalete
    specialized marketing, inc.]' and ' Carlos Hidalgo ' both -> 'carlos hidalgo'."""
    s = (s or "").split("[")[0].split("(")[0]
    return " ".join(s.lower().split())


def _we_key(week_mdy: str) -> str:
    """'7.12.26' -> 'WE 7/12' (the Raf PNL header form)."""
    m, d, _y = week_mdy.split(".")
    return f"WE {int(m)}/{int(d)}"


# --------------------------------------------------------------------------
# Raf Captain Override — Google Sheet (Raf PNL 2026, row 335)
# --------------------------------------------------------------------------
RAF_PNL_WORKBOOK = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
RAF_PNL_TAB = "Raf PNL 2026"
RAF_CAPTAIN_ROW = 335        # "Captain Override" row


def _money(raw):
    if raw is None:
        return None
    s = str(raw).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def raf_captain_override(week_mdy: str, ws=None):
    """Raf's Captain Override for the given sheet week (e.g. '7.12.26').

    Reads Raf PNL 2026 row 335 at the target week's WE block — the value sits in
    the block's Profit/Loss column, i.e. the WE-header column + 2 (the label
    'Captain Override' is one cell left, under 'Got Paid'). Returns the amount or
    None if the week/value isn't present."""
    if ws is None:
        from automations.recruiting_report import fill as _fill
        ws = _fill._client().open_by_key(RAF_PNL_WORKBOOK).worksheet(RAF_PNL_TAB)
    vals = ws.get_all_values()
    header = vals[0]
    want = _we_key(week_mdy)
    base = next((i for i, h in enumerate(header) if (h or "").strip() == want), None)
    if base is None:
        return None
    row = vals[RAF_CAPTAIN_ROW - 1] if RAF_CAPTAIN_ROW - 1 < len(vals) else []
    vcol = base + 2                                  # Profit/Loss col of the block
    return _money(row[vcol]) if vcol < len(row) else None

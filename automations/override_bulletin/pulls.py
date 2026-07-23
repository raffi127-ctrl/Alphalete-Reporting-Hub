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


# --------------------------------------------------------------------------
# Regular override — Tableau ORG OVERRIDE SUMMARY crosstab
# --------------------------------------------------------------------------
OVERRIDE_SUMMARY_VIEW = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "OverridesICDView/ORGOVERRIDESUMMARY")


def _num_locale(s: str):
    """Parse a money string in either US ('72,253.17') or EU ('72.253,17')
    format, tolerating '$', parens-negatives and spaces. None if not a number."""
    if s is None:
        return None
    t = str(s).strip().replace("$", "").replace(" ", "")
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if "," in t and "." in t:
        # last separator is the decimal
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") \
            else t.replace(",", "")
    elif "," in t:
        # comma-only: decimal if it looks like ",dd" at the end, else thousands
        t = t.replace(",", ".") if re.search(r",\d{1,2}$", t) else t.replace(",", "")
    try:
        v = float(t)
        return -v if neg else v
    except ValueError:
        return None


def parse_override_summary(rows, week_header, *, name_col=0):
    """Sum each ICD owner's campaign rows for one week column.

    `rows` is the downloaded crosstab as a list of row-lists. The owner name sits
    in `name_col`; continuation rows for the owner's other campaigns have a blank
    name (Megan 2026-07-22: "add up the sum of everything listed with that ICD").
    `week_header` is the target week's column header (e.g. '07/12/2026'); we find
    that column in the header rows. Returns {normalized_owner: total}. Skips the
    grand-total row ('Total general' / 'Grand Total')."""
    # locate the week column (and the header row) by matching its header
    wk_col = hdr_row = None
    for ri, r in enumerate(rows[:6]):
        for ci, cell in enumerate(r):
            if str(cell).strip() == str(week_header).strip():
                wk_col, hdr_row = ci, ri
                break
        if wk_col is not None:
            break
    if wk_col is None:
        raise ValueError(f"week column {week_header!r} not found in crosstab header")

    out, cur = {}, None
    for r in rows[hdr_row + 1:]:               # skip the header rows
        name = (r[name_col] if name_col < len(r) else "").strip()
        low = name.lower()
        if low in ("total general", "grand total", "total"):
            cur = None
            continue
        if name:
            cur = _norm_name(name)
            out.setdefault(cur, 0.0)
        if cur is None:
            continue
        val = _num_locale(r[wk_col]) if wk_col < len(r) else None
        if val is not None:
            out[cur] += val
    return {k: round(v, 2) for k, v in out.items()}

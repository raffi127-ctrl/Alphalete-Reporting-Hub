"""Pull the New Internet Churn Crosstab for Raf's Local Office.

The custom view URL preconfigures both the Tableau filters Eve sets by
hand (Product Type = NEW INTERNET, ICD Owner Name (rep) = RAFAEL
HIDALGO), so the export gives us rep-level data for Raf's office only —
no URL params or Python-side owner filtering needed.

The CSV is wide-format with metric-type rows: each (rep, color) yields
four rows (Activated SPE/SP, Disconnect count (SPE/SP), Churn Rate
(Unit vs Order), Calculation1 (1)), and each metric row has a value in
only ONE of the four period columns (0-30 / 30 / 60 / 90 Day Churn).
We walk the rows once and pivot into:
    {
      "office_total": {
          "0-30": {"pct": "1.47%", "num": 7, "denom": 477},
          "30":   {...}, "60": {...}, "90": {...},
      },
      "reps": {
          "Aaron Horn": {"90": {"pct": "0.00%", "num": 0, "denom": 1, "color": "Green"}},
          "Africa Botala Lajay": {"0-30": {...}, "30": {...}},
          ...
      },
    }
"""
from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright

# Custom view URL: NewINTLocalOffice (Megan 2026-05-29) bakes in all
# three filters at the right values:
#   * Churn View = New Internet Churn View   (← the parameter that was
#     missing from NewINTRafExpanded, which left wireless pulls
#     computed with NI formula. Eve's bug. Replaced with a freshly-
#     saved custom view so all 3 dropdowns are locked correctly.)
#   * Product Type (Broken Out) = NEW INTERNET
#   * ICD Owner Name (rep) = RAFAEL HIDALGO
VIEW_URL = os.environ.get("CHURN_NI_VIEW_URL") or (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "6a425046-e284-4e60-9ffa-7656aa7b9776/INTLocalOffice?:iid=2"
)
WORKSHEET = "ICD Churn"

PERIODS = ("0-30", "30", "60", "90")


def fetch_crosstab(out_path: Optional[Path] = None,
                   verbose: bool = False,
                   page=None) -> Path:
    """Download the ICD Churn Crosstab. Pass `page` to reuse an existing
    tableau_session (the combined churn runner opens one session and
    reuses it for both New Internet + Wireless pulls)."""
    out_path = out_path or Path(tempfile.gettempdir()) / "new_internet_churn_local_office.csv"
    # Harvest cutover (DEFAULT-OFF): only when HARVEST_MODE=on does this read the
    # dated cache instead of scraping; a cache miss/stale/error falls straight
    # through to the live download below. With no env var, behaviour is unchanged.
    if os.environ.get("HARVEST_MODE", "off").strip().lower() == "on":
        from automations.harvest import adapter
        cached = adapter.try_cache_view(VIEW_URL, WORKSHEET, out_path)
        if cached is not None:
            return cached
    download_crosstab_patchright(VIEW_URL, WORKSHEET, out_path,
                                  verbose=verbose, page=page)
    return out_path


def _to_num(v: str) -> Optional[float]:
    """Parse a numeric crosstab cell ('1.0', '7,123', '0.00%'-style values
    are NOT routed here — only the count/denominator fields are). Returns
    None for blanks so we can distinguish 'no data' from 'zero'."""
    v = v.strip()
    if not v:
        return None
    try:
        return float(v.replace(",", ""))
    except ValueError:
        return None


def parse(csv_path: Path) -> dict:
    """Pivot the wide-format ICD Churn Crosstab into office + per-rep data."""
    with open(csv_path, "r", encoding="utf-16-le") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if not rows:
        return {"office_total": {}, "reps": {}}

    header = [h.lstrip("﻿").strip() for h in rows[0]]
    rep_i = header.index("Rep Name")
    # Color column name varies across views:
    #   New Internet Churn View:  '30-60 Color Churn (copy)'
    #   Wireless Churn View:      '30-60 Color Churn (Wireless)'
    # Match by prefix so both work.
    color_col = next(
        (c for c in header if c.startswith("30-60 Color Churn")),
        None,
    )
    if color_col is None:
        raise ValueError(
            f"No '30-60 Color Churn ...' column found in {header}. "
            "The Tableau Crosstab schema changed."
        )
    color_i = header.index(color_col)
    # The unnamed metric-type column sits between color and the 0-30 column.
    # Tolerate a YOUNG office (e.g. Rashad) that doesn't have 30/60/90-day churn
    # yet — only parse the period columns actually present. Missing periods stay
    # absent from the parsed result; the fill writes blanks for those sections.
    # (Raf has all 4, so his behavior is unchanged.)
    period_cols = {p: header.index(f"{p} Day Churn")
                   for p in PERIODS if f"{p} Day Churn" in header}
    if not period_cols:
        return {"office_total": {}, "reps": {}}
    # The unnamed metric-type column sits just left of the first period column.
    metric_i = min(period_cols.values()) - 1

    # SLICE MODE (office_metrics, opt-in): CHURN_SLICE_OWNER points fetch_crosstab
    # at an ALL-OFFICE view (INTAllTeams / WirelessAllTeams) and this filters the
    # rows to that office's ICD owner, then recomputes the office total from the
    # office's own reps (the all-office view has NO per-office Total row — only a
    # Grand Total — so we sum the counts, which aggregate cleanly). Unset = the
    # original per-office-view behaviour, byte-identical.
    slice_owner = os.environ.get("CHURN_SLICE_OWNER", "").strip()
    owner_i = (header.index("ICD Owner Name (rep)")
               if slice_owner and "ICD Owner Name (rep)" in header else None)

    office_total: dict = {}
    reps: dict = {}

    for r in rows[1:]:
        if len(r) <= max(period_cols.values()):
            continue
        if owner_i is not None and (r[owner_i] or "").strip().upper() != slice_owner.upper():
            continue                       # slicing: keep only this office's rows
        rep_name = r[rep_i].strip()
        color = r[color_i].strip()
        metric = r[metric_i].strip()
        is_total = rep_name == "Total"

        for period, col_i in period_cols.items():
            cell = r[col_i].strip()
            if not cell:
                continue
            target = office_total if is_total else reps.setdefault(rep_name, {})
            slot = target.setdefault(period, {})
            if not is_total and color and color != "Total":
                slot.setdefault("color", color)
            if metric == "Churn Rate (Unit vs Order)":
                slot["pct"] = cell
            elif metric == "Disconnect count (SPE/SP)":
                slot["num"] = _to_num(cell)
            elif metric == "Activated SPE/SP":
                slot["denom"] = _to_num(cell)
            # Calculation1 (1) is a tableau normalizer — skip.

    if owner_i is not None:
        office_total = _recompute_office_total(reps)     # no per-office Total row
    return {"office_total": office_total, "reps": reps}


def _recompute_office_total(reps: dict) -> dict:
    """Office total from a sliced all-office pull: sum each period's disconnect
    count + activations across the office's reps, then rate = num/denom. Churn
    counts aggregate cleanly, so this equals the per-office view's Total row
    (verified cell-for-cell via `runner --prove-churn`). Rate formatted to one
    decimal to match the view's crosstab text (e.g. '7.7%')."""
    total: dict = {}
    for periods in reps.values():
        for period, slot in periods.items():
            t = total.setdefault(period, {"num": 0.0, "denom": 0.0})
            if slot.get("num") is not None:
                t["num"] += slot["num"]
            if slot.get("denom") is not None:
                t["denom"] += slot["denom"]
    for t in total.values():
        # Churn rate = disconnects/activations, formatted to 2 decimals to match
        # the view's crosstab text (proven: 6/152 → '3.95%', not '3.9%').
        t["pct"] = f"{(t['num'] / t['denom'] * 100):.2f}%" if t["denom"] else "0.00%"
    return total


def fmt_units(slot: dict) -> str:
    """Format a {num, denom} slot as 'N/D' for the sheet's units column.
    Returns '' if either component is missing — keeps the cell blank so
    the conditional formatting reads 'no data'."""
    num = slot.get("num")
    denom = slot.get("denom")
    if num is None or denom is None:
        return ""
    # Comma-thousands separator (Eve 2026-05-30): 1563 -> 1,563. Written RAW to
    # the sheet, so the comma+slash stays text (no date re-parsing of 'N/D').
    return f"{int(num):,}/{int(denom):,}"

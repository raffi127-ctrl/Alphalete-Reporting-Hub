"""Team Breakdowns ('Next Promotion') fill.

Per tab: find every 'Next Promotion' header in column A; for each section,
locate the 'Total Units' row below, then list reps from column B between
them. For each rep + each section's date column matching the current OPT
week, look up the rep's production from the PRODUCT SALES SUMMARY crosstab
(includes UPGRADE / VIDEO — broader than the Production Breakdown which
filters to NI + WIRELESS only) and write as 'X NI, Y DTV, Z NL, W UG'.

Rep-name matching uses aggressive normalize (strips all non-alphanum,
parens) + first-last fallback (so 'Jean Bueno' matches
'Jean Carlos Bueno' and 'Suave' nicknames in parens are stripped).

Smart fallback for missed reps:
  - If the rep row has past-week data on the tab -> they're a known rep
    with no sales this week -> write '-'.
  - If the rep row is historically blank -> write 'Unmatched Name - Check
    Spelling' so the user knows to fix.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import gspread

from automations.recruiting_report import fill as rfill


# Product Type -> short label, in display order
PRODUCT_LABELS = [("NEW INTERNET", "NI"), ("VIDEO", "DTV"),
                  ("WIRELESS", "NL"), ("UPGRADE", "UG")]

# Tabs whose 'Total Units' row should show a single INTEGER (sum of all
# product units that week) instead of the broken-out '15 NI, 1 DTV' form.
# Megan wants this only for Starr's section (Miguel Carranza), 2026-07-23 —
# every other tab keeps the broken-out total. [[project_miguel-carranza-starr-next-promotion]]
INT_TOTAL_TABS = {"Starr Rodenhurst"}


def _strip_parens(s: str) -> str:
    """'Tagiilimafaaolataga Setu Fiame (Suave)' -> 'Tagi... Fiame'."""
    return re.sub(r"\([^)]*\)", "", s or "").strip()


def _rep_norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _strip_parens(s).lower())


def _first_last(s: str) -> str:
    """Aggressive first+last word norm — for matching 'Jean Bueno' to
    'Jean Carlos Bueno'."""
    parts = re.findall(r"[A-Za-z]+", _strip_parens(s))
    if len(parts) >= 2:
        return _rep_norm(parts[0] + parts[-1])
    return _rep_norm(s)


def parse_crosstab_per_rep(path: Path) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """Returns (by_norm, by_first_last) — both indexed dicts, value is
    {raw, products{ptype: week_total}}."""
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    headers = [h.strip() for h in rows[0]]
    rep_col = headers.index("Rep")
    ptype_col = headers.index("Product Type (Broken Out)")
    total_col = headers.index("Product Total")
    by_norm: Dict[str, dict] = {}
    by_fl: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) <= total_col:
            continue
        rep = (r[rep_col] or "").strip()
        if not rep or rep.lower() == "total":
            continue
        ptype = (r[ptype_col] or "").strip().upper()
        total = r[total_col].strip()
        n = int(total) if total.lstrip("-").isdigit() else 0
        if not n:
            continue
        nkey = _rep_norm(rep)
        ent = by_norm.setdefault(nkey, {"raw": rep, "products": {}})
        ent["products"][ptype] = ent["products"].get(ptype, 0) + n
        fl = _first_last(rep)
        if fl and fl != nkey:
            by_fl.setdefault(fl, ent)
    return by_norm, by_fl


def lookup_rep(name: str, by_norm: Dict[str, dict],
               by_fl: Dict[str, dict]) -> Optional[dict]:
    return by_norm.get(_rep_norm(name)) or by_fl.get(_first_last(name))


def format_production(products: Dict[str, int]) -> str:
    parts = []
    for ptype, label in PRODUCT_LABELS:
        c = products.get(ptype, 0)
        if c:
            parts.append(f"{c} {label}")
    return ", ".join(parts)


def find_sections(grid: List[List[str]]) -> List[dict]:
    out = []
    for i, r in enumerate(grid, 1):
        if (r[0] if r else "").strip() != "Next Promotion":
            continue
        header_row = i
        total_row = None
        for j in range(header_row + 1, min(header_row + 30, len(grid) + 1)):
            if (grid[j - 1][0] if grid[j - 1] else "").strip() == "Total Units":
                total_row = j
                break
        if not total_row:
            continue
        reps = []
        for j in range(header_row + 1, total_row):
            row = grid[j - 1]
            b = (row[1] if len(row) > 1 else "").strip()
            if b:
                reps.append((j, b))
        out.append({"header_row": header_row, "total_row": total_row,
                    "reps": reps, "header": grid[header_row - 1]})
    return out


def find_date_col(header_row_vals: List[str], target_date: dt.date) -> Optional[int]:
    for j, v in enumerate(header_row_vals, 1):
        vs = v.strip()
        if not re.match(r"^\d+/\d+/\d+$", vs):
            continue
        try:
            m, d, y = (int(x) for x in vs.split("/"))
            if y < 100:
                y += 2000
            if dt.date(y, m, d) == target_date:
                return j
        except ValueError:
            continue
    return None


def date_cols(header_row_vals: List[str]) -> List[int]:
    cols = []
    for j, v in enumerate(header_row_vals, 1):
        vs = v.strip()
        if re.match(r"^\d+/\d+/\d+$", vs):
            try:
                m, d, y = (int(x) for x in vs.split("/"))
                cols.append(j)
            except ValueError:
                pass
    return cols


def rep_has_history(grid: List[List[str]], rep_row: int,
                    all_date_cols: List[int], current_col: int) -> bool:
    """True if the rep's row has ANY past data in date cols other than
    the current week. '-' counts as past history. Ignores our own
    'Unmatched' marker so re-runs don't lock in."""
    row = grid[rep_row - 1]
    for c in all_date_cols:
        if c == current_col:
            continue
        v = (row[c - 1] if c - 1 < len(row) else "").strip()
        if v and v != "Unmatched Name - Check Spelling":
            return True
    return False


def fmt_we_header(d) -> str:
    return f"WE {d.month}.{d.day}"


def fill_for_tab(ws, we_sunday: dt.date,
                 by_norm: Dict[str, dict], by_fl: Dict[str, dict],
                 dry_run: bool = False) -> dict:
    """Process one tab's Team Breakdowns sections. Returns a status dict."""
    tab = ws.title
    grid = rfill._retry(ws.get_all_values)
    sections = find_sections(grid)
    if not sections:
        return {"tab": tab, "status": "NO_SECTION", "n_sections": 0}

    all_updates: List[Tuple[str, Any]] = []
    unmatched: List[str] = []
    n_filled_sections = 0
    for sec in sections:
        date_col = find_date_col(sec["header"], we_sunday)
        if not date_col:
            continue
        all_dates = date_cols(sec["header"])
        total_products: Dict[str, int] = {}
        for r, name in sec["reps"]:
            ent = lookup_rep(name, by_norm, by_fl)
            if ent:
                prods = ent["products"]
                for ptype, c in prods.items():
                    total_products[ptype] = total_products.get(ptype, 0) + c
                formatted = format_production(prods)
            else:
                if rep_has_history(grid, r, all_dates, date_col):
                    formatted = "-"
                else:
                    formatted = "Unmatched Name - Check Spelling"
                    unmatched.append(name)
            all_updates.append((gspread.utils.rowcol_to_a1(r, date_col), formatted))
        if tab in INT_TOTAL_TABS:
            _units = sum(total_products.values())
            total_str = str(_units) if _units else ""
        else:
            total_str = format_production(total_products)
        all_updates.append((gspread.utils.rowcol_to_a1(sec["total_row"], date_col),
                            total_str))
        n_filled_sections += 1

    if all_updates and not dry_run:
        rfill._retry(ws.batch_update,
                     [{"range": a1, "values": [[v]]} for a1, v in all_updates],
                     value_input_option="USER_ENTERED")
    return {"tab": tab, "status": "OK", "n_sections": n_filled_sections,
            "cells": len(all_updates), "unmatched": unmatched}

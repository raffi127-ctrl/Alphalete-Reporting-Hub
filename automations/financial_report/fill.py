"""Write the financial section into the focus-report Google Sheets.

For each ICD tab across the focus-report spreadsheets, match the tab to an
office in the parsed FINANCIAL SUMMARY data and write the financial rows into
the latest week columns. Only ever writes the mapped financial cells.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

import gspread

from automations.recruiting_report import fill as rfill
from .parse import FINANCIAL_METRICS, norm_name

# The focus-report spreadsheets the financial section fills.
OUTPUT_SHEETS = {
    "ATT Program - Focus Report":          "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE",
    "Carlos 1on1s - Focus Report":         "1KLF8diMJ8pwIQWW9IqN7CL288t1l9VGUKxzBcMl8Of4",
    "Alphalete Org 1on1s - Focus Reports": "1C6BLttOSZhs_dREySac19XkxnMl-Ab_sYacNSl2l6AQ",
}

# How far below the 'Total Funds Available' anchor the financial rows run.
_SECTION_SPAN = 14
# A tab-name campaign suffix, e.g. ' - NDS' / ' - BOX' / ' - B2B'.
_CAMPAIGN_SUFFIX = re.compile(r"\s*-\s*[A-Za-z0-9/&]+\s*$")


def _norm(s) -> str:
    """Lowercase, trim, collapse whitespace, drop spaces around %/ — so
    'Operating %' and 'Operating%' match."""
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"\s*([%/])\s*", r"\1", s)


def _tab_to_name(tab: str) -> str:
    """ICD name from a tab title — drops a leading 'x -' (archived marker)
    and a trailing ' - <campaign>' (NDS / BOX / B2B / ...)."""
    t = re.sub(r"^\s*x\s*-\s*", "", tab or "", flags=re.I)
    t = _CAMPAIGN_SUFFIX.sub("", t)
    return t.strip()


def _match_owner(tab: str, by_owner: Dict[str, dict],
                 bridge: Optional[Dict[str, List[str]]] = None) -> Optional[dict]:
    """Match a Sheet tab to a financial office. The financial files spell
    names legally (RAFAEL HIDALGO, LAMAR MITCHELL III) while tabs use
    nicknames (Raf Hidalgo, Tre Mitchell) — `bridge` maps a normalized tab
    name to alternate names (the recruiting mapping's AppStream owner)."""
    name = _tab_to_name(tab)
    cands = [name]
    m = re.match(r"^(.*?)\s*\((.+?)\)\s*$", name)
    if m:
        cands += [m.group(2).strip(), m.group(1).strip()]
    if bridge:
        cands += bridge.get(norm_name(tab), [])
        cands += bridge.get(norm_name(name), [])
    for c in cands:
        hit = by_owner.get(norm_name(c))
        if hit:
            return hit
    # Same-surname subset fallback — one name has an extra middle name.
    tw = norm_name(name).split()
    if len(tw) >= 2:
        for key, office in by_owner.items():
            kw = key.split()
            if kw and kw[-1] == tw[-1] and (set(tw) <= set(kw) or set(kw) <= set(tw)):
                return office
    return None


def _date_columns(header_row: List[str]) -> Dict[dt.date, int]:
    """{date -> 0-indexed column} for every date-looking header cell."""
    out: Dict[dt.date, int] = {}
    for i, h in enumerate(header_row):
        txt = str(h or "").strip()
        for fmt in ("%m/%d/%y", "%m/%d/%Y", "%-m/%-d/%y"):
            try:
                out[dt.datetime.strptime(txt, fmt).date()] = i
                break
            except ValueError:
                pass
    return out


def _closest_col(date_cols: Dict[dt.date, int], target: dt.date,
                 tol_days: int = 4) -> Optional[int]:
    """Column whose header date is closest to `target`, within tol_days."""
    best, best_diff = None, tol_days + 1
    for d, c in date_cols.items():
        diff = abs((d - target).days)
        if diff < best_diff:
            best, best_diff = c, diff
    return best


def fill_financial_for_tab(ws: gspread.Worksheet, office: dict,
                           weeks: List[dt.date], dry_run: bool) -> List[str]:
    """Write the financial rows for one ICD tab. Returns log lines."""
    tab = ws.title
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip] {tab}: empty tab"]
    date_cols = _date_columns(grid[0])
    col_b = [(r[1] if len(r) > 1 else "") for r in grid]

    anchor = next((j for j, v in enumerate(col_b)
                   if _norm(v) == _norm("Total Funds Available")), None)
    if anchor is None:
        return [f"[skip] {tab}: no financial section"]
    section = {_norm(col_b[j]): j
               for j in range(anchor, min(anchor + _SECTION_SPAN, len(col_b)))
               if col_b[j].strip()}

    wk_cols = [_closest_col(date_cols, w) for w in weeks]
    if not any(c is not None for c in wk_cols):
        return [f"[skip] {tab}: no matching week columns for {weeks}"]

    updates: List[Tuple[str, object]] = []
    missing: List[str] = []
    for out_label, xl_label in FINANCIAL_METRICS.items():
        row = section.get(_norm(out_label))
        if row is None:
            missing.append(out_label)
            continue
        vals = office["metrics"].get(xl_label)
        if not vals:
            continue
        for k, col in enumerate(wk_cols):
            if col is None or k >= len(vals) or vals[k] is None:
                continue
            updates.append((gspread.utils.rowcol_to_a1(row + 1, col + 1),
                            vals[k]))

    if not updates:
        return [f"[skip] {tab}: nothing to write"]
    if dry_run:
        log = [f"[DRY-RUN] {tab} ← {office['office']}: {len(updates)} cells"]
    else:
        rfill._retry(ws.batch_update,
                     [{"range": a1, "values": [[v]]} for a1, v in updates],
                     value_input_option="USER_ENTERED")
        log = [f"[OK] {tab} ← {office['office']}: wrote {len(updates)} cells"]
    if missing:
        log.append(f"    (rows not on tab: {', '.join(missing)})")
    return log

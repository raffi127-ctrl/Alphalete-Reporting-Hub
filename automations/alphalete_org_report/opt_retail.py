"""Retail OPT phase for the Alphalete Org 1on1s - Focus Reports sheet.

First pass scopes to the Costco section at the bottom of the
"Boaktear Chowdhury (Akib/MJ) - Retail" tab (rows ~103-108). Pulls
weekly wireless line counts per Costco store from the
RETAILSALESSUMMARYBYCLUB view (one HTTP request, fast).

Other Retail metrics (per-ICD blocks for MJ + Akib, churn rates, ABP %,
etc.) are still being mapped — they'll get added here as Megan shares
each Tableau source.

Source: Megan, 2026-05-22 — view 'AkibMJClubList' on
DropshipV_2/RETAILSALESSUMMARYBYCLUB. The default HTTP CSV export gives
the per-store weekly breakdown directly (no UI Crosstab needed).
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional

import gspread

from automations.recruiting_report import fill as rfill
from automations.alphalete_org_report import tableau_http
from automations.alphalete_org_report.opt_nds import (
    ALPHALETE_ORG_SHEET_ID,
    OUTPUT_DIR,
    _current_target_week_col_label,
    _find_week_col,
)


# HTTP-direct view URL. Critical: appending the custom-view UUID +
# name to the path filters to Akib + MJ only. Without it, the HTTP
# endpoint returns the workbook's unfiltered default view, which leaks
# other reps' Costco sales (e.g. BC #579 = 18, a non-Akib/MJ store)
# and inflates Total Store Count. Confirmed 2026-05-22 against Megan's
# AkibMJSummary view.
RETAIL_BY_CLUB_URL = (
    "https://us-east-1.online.tableau.com/t/sci/views/"
    "DropshipV_2/RETAILSALESSUMMARYBYCLUB/"
    "35f6a7b4-eab4-4821-8f30-cabc530c648e/AkibMJSummary.csv"
)
RETAIL_BY_CLUB_FILENAME = "opt_retail_by_club.csv"


# Pattern: extracts the store identifier ('#669', 'BC #655', '#1735') from
# both sheet labels and CSV labels so they normalize to the same key.
# Examples handled:
#   'Costco #669'            -> ('', 669)
#   'Costco # 1173'          -> ('', 1173)     # extra space in sheet
#   'Costco BC #655'         -> ('BC', 655)
#   'Costco 1735 (3/5)'      -> ('', 1735)     # missing '#'
_STORE_NUM_RE = re.compile(r"(?i)(BC)?\s*#?\s*(\d{3,4})")


def _normalize_store_label(label: str) -> Optional[tuple]:
    """Reduce a store label to a (kind, number) tuple where kind is 'BC'
    for Business Center stores and '' for regular Costco. Returns None if
    no store number found."""
    if not label:
        return None
    # Strip 'Costco' prefix to focus on the identifier
    rest = re.sub(r"(?i)^\s*costco\s*", "", label.strip())
    m = _STORE_NUM_RE.search(rest)
    if not m:
        return None
    bc, num = m.group(1), m.group(2)
    return ("BC" if bc else "", int(num))


def parse_retail_by_club(path: Path) -> Dict[tuple, int]:
    """Parse RETAILSALESSUMMARYBYCLUB and return
    {(kind, number): wk_total_int} per Costco store.

    The CSV is long-format with one row per (Location, Measure) pair:
      Location (copy) | Measure Names | Measure Values
    We filter to rows where Measure Names == 'WK Total' and the Location
    starts with 'Costco'. Aggregate 'NDS' and 'All' rows are skipped."""
    rows = tableau_http.parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    loc_i = tableau_http.col_idx(header, "Location (copy)")
    meas_i = tableau_http.col_idx(header, "Measure Names")
    val_i = tableau_http.col_idx(header, "Measure Values")
    if loc_i is None or meas_i is None or val_i is None:
        return {}
    out: Dict[tuple, int] = {}
    for r in rows[1:]:
        if len(r) <= max(loc_i, meas_i, val_i):
            continue
        loc = (r[loc_i] or "").strip()
        if not loc.lower().startswith("costco"):
            continue   # skip NDS / All aggregate rows
        if (r[meas_i] or "").strip() != "WK Total":
            continue
        key = _normalize_store_label(loc)
        if key is None:
            continue
        try:
            val = int(float((r[val_i] or "0").replace(",", "")))
        except (ValueError, AttributeError):
            continue
        out[key] = val
    return out


def fill_costco_section(ws: gspread.Worksheet,
                        by_club: Dict[tuple, int],
                        week_col_label: str,
                        dry_run: bool = False,
                        logfn=print) -> List[str]:
    """Find Costco store rows (col B labels like 'Costco #669',
    'Costco BC #655', 'Costco 1735 (3/5)') on the Boaktear tab and write
    each store's WK Total to the current week column. Stores with no
    sales this week (absent from the CSV) get 0."""
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-retail] {ws.title}: empty tab"]

    week_col = _find_week_col(grid, week_col_label)
    if week_col is None:
        return [f"[skip-retail] {ws.title}: no column for week {week_col_label}"]

    updates = []
    for ri, row in enumerate(grid):
        label = (row[1] if len(row) > 1 else "").strip()
        if not label.lower().startswith("costco"):
            continue
        key = _normalize_store_label(label)
        if key is None:
            continue
        # Default to 0 if the store had no sales this week (absent from CSV
        # entirely OR present with WK Total = 0). Megan 2026-05-22: stores
        # like Costco #376 with no sales for the week land as 0.
        wk_total = by_club.get(key, 0)
        a1 = gspread.utils.rowcol_to_a1(ri + 1, week_col + 1)
        updates.append({"range": a1, "values": [[str(wk_total)]]})
        log.append(f"  {a1} ({label}) ← {wk_total}")

    # Total Store Count = count of stores selling this week (Megan: "Store
    # count will equal the count of stores that have sales in them that
    # week"). Look up the label on Boaktear's tab + write the count.
    selling_stores = sum(1 for v in by_club.values() if v > 0)
    for ri, row in enumerate(grid):
        label = (row[1] if len(row) > 1 else "").strip().lower()
        if label == "total store count":
            a1 = gspread.utils.rowcol_to_a1(ri + 1, week_col + 1)
            updates.append({"range": a1, "values": [[str(selling_stores)]]})
            log.append(f"  {a1} (Total Store Count) ← {selling_stores}")
            break

    if dry_run:
        return [f"[DRY-RUN retail-costco] {ws.title}: would write {len(updates)} cells"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        return [f"[OK retail-costco] {ws.title}: wrote {len(updates)} cells"] + log
    return [f"[skip-retail] {ws.title}: no Costco rows found"]


def run_retail_costco(dry_run: bool = False, logfn=print) -> dict:
    """Pull RETAILSALESSUMMARYBYCLUB, fill the Costco section on Boaktear's
    Retail tab. Returns {filled: [...], skipped: [...], errors: [...]}."""
    errors: List[str] = []

    # Step 1: HTTP-pull the per-club crosstab. Uses the explicit custom-view
    # URL (UUID + AkibMJSummary) so we get Akib + MJ filtered data, not the
    # workbook's default (which includes other reps' Costco sales).
    out_path = OUTPUT_DIR / RETAIL_BY_CLUB_FILENAME
    try:
        logfn(f"OPT Retail: HTTP downloading {RETAIL_BY_CLUB_FILENAME}…")
        session = tableau_http._grab_session()
        r = session.get(RETAIL_BY_CLUB_URL, allow_redirects=True, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(
                f"HTTP {r.status_code} ({len(r.content)} bytes)")
        out_path.write_bytes(r.content)
    except Exception as e:
        msg = f"{RETAIL_BY_CLUB_FILENAME}: {type(e).__name__}: {str(e)[:120]}"
        logfn(f"OPT Retail: ✗ HTTP {msg}")
        errors.append(msg)
        return {"filled": [], "skipped": [], "errors": errors}

    # Step 2: parse the per-store totals.
    by_club = parse_retail_by_club(out_path)
    logfn(f"OPT Retail: parsed {len(by_club)} Costco store(s): "
          f"{sorted(by_club.items())}")

    # Step 3: walk the Retail tabs (Boaktear is the only Costco one).
    client = rfill._client()
    sh = client.open_by_key(ALPHALETE_ORG_SHEET_ID)
    week_col_label = _current_target_week_col_label()
    logfn(f"OPT Retail: target week column = {week_col_label!r}")

    filled: List[str] = []
    skipped: List[str] = []
    for ws in rfill._retry(sh.worksheets):
        title = ws.title
        # Boaktear's tab is the only one with Costco store rows for now.
        if "boaktear" not in title.lower() or not title.endswith(" - Retail"):
            continue
        lines = fill_costco_section(ws, by_club, week_col_label, dry_run, logfn)
        for ln in lines:
            logfn(f"OPT Retail: {ln}")
        if lines and lines[0].startswith(("[OK", "[DRY-RUN")):
            filled.append(title)
        else:
            skipped.append(title)

    return {"filled": filled, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = run_retail_costco(dry_run=args.dry_run)
    print(f"\nFilled: {len(result['filled'])} tab(s); "
          f"Skipped: {len(result['skipped'])}; "
          f"Errors: {len(result['errors'])}")

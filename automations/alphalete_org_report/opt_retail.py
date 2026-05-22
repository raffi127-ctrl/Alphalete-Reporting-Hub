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
    _find_row_by_label,
    _find_week_col,
    _norm_owner,
)


# Each Retail tab's combined-ICD setup. Multi-ICD tabs (like Boaktear's
# Akib + MJ tab) need a list so we can scope row-label lookups to each
# ICD's section. Sara Plus By Day data is keyed on the ICD's full name —
# match it case-insensitively against the section-header text in col A.
RETAIL_TAB_ICDS: Dict[str, List[str]] = {
    "Boaktear Chowdhury (Akib/MJ) - Retail": ["amjad malhas", "boaktear chowdhury"],
    "Ronald Dawson - Retail":                ["ronald dawson"],
}


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


def _find_icd_section_ranges(grid: List[List[str]],
                              icds: List[str]) -> Dict[str, tuple]:
    """For a multi-ICD tab, return {icd_norm: (start_row_0idx, end_row_0idx)}.

    Section start = the row whose col A contains the ICD's name (case-
    insensitive substring). Section end = row before the next ICD's
    section start, or end of grid for the last section. Stops scanning
    after we've found all of the listed ICDs in order.

    Single-ICD tabs (only one entry in `icds`) span the whole grid."""
    icds_norm = [i.lower() for i in icds]
    starts: List[int] = []
    for icd in icds_norm:
        found = None
        # Search col A for the first row containing this ICD name
        scan_from = (starts[-1] + 1) if starts else 0
        for ri in range(scan_from, len(grid)):
            cell = (grid[ri][0] if grid[ri] else "").strip().lower()
            if icd in cell:
                found = ri
                break
        if found is None:
            continue   # tab missing this ICD's section
        starts.append(found)
    out: Dict[str, tuple] = {}
    for idx, ri in enumerate(starts):
        end = starts[idx + 1] - 1 if idx + 1 < len(starts) else len(grid) - 1
        out[icds_norm[idx]] = (ri, end)
    return out


def _find_label_row_in_range(grid: List[List[str]], label: str,
                              start: int, end: int,
                              label_col: int = 1) -> Optional[int]:
    """Like opt_nds._find_row_by_label but scoped to a row range. Returns
    the 0-indexed row of the first label match in [start, end] inclusive."""
    sub = grid[start: end + 1]
    rel = _find_row_by_label(sub, label, label_col)
    return start + rel if rel is not None else None


def _csv_canonical_label(key: tuple) -> str:
    """Reverse _normalize_store_label — turn ('BC', 579) back into
    'Costco BC #579' for new-row inserts. Mirrors the CSV's label
    convention so future runs match the inserted rows cleanly."""
    kind, num = key
    return f"Costco BC #{num}" if kind == "BC" else f"Costco #{num}"


def fill_costco_section(ws: gspread.Worksheet,
                        by_club: Dict[tuple, int],
                        week_col_label: str,
                        dry_run: bool = False,
                        logfn=print) -> List[str]:
    """Find Costco store rows (col B labels like 'Costco #669',
    'Costco BC #655', 'Costco 1735 (3/5)') on the Boaktear tab and write
    each store's WK Total to the current week column. Stores with no
    sales this week (absent from the CSV) get 0.

    If the CSV has a new club with sales > 0 that doesn't yet have a row,
    insert a new row directly below the last existing Costco row with the
    club label + value. Megan 2026-05-22: 'if ever a new club pops up
    with akib or mj (or the icd you're pulling) with production, we need
    it added to this section with a club label and production count'."""
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-retail] {ws.title}: empty tab"]

    week_col = _find_week_col(grid, week_col_label)
    if week_col is None:
        return [f"[skip-retail] {ws.title}: no column for week {week_col_label}"]

    # Scan for existing Costco rows (label + normalized key + 0-indexed row)
    existing: List[tuple] = []   # (row_0idx, key, original_label)
    for ri, row in enumerate(grid):
        label = (row[1] if len(row) > 1 else "").strip()
        if not label.lower().startswith("costco"):
            continue
        key = _normalize_store_label(label)
        if key is None:
            continue
        existing.append((ri, key, label))
    existing_keys = {k for _, k, _ in existing}

    # New clubs from the CSV with sales > 0 + no matching row yet.
    new_clubs = sorted(
        ((k, v) for k, v in by_club.items() if v > 0 and k not in existing_keys),
        key=lambda kv: (kv[0][0], kv[0][1]),
    )

    # Insert new rows just below the last existing Costco row. Doing this
    # FIRST so subsequent batch_update row references line up with the
    # post-insert layout.
    inserted_rows: List[tuple] = []   # (row_0idx_post_insert, key, label, value)
    if new_clubs and existing and not dry_run:
        insert_at_0 = max(r for r, _, _ in existing) + 1  # 0-indexed
        ws_id = ws.id
        requests = [{
            "insertDimension": {
                "range": {"sheetId": ws_id, "dimension": "ROWS",
                          "startIndex": insert_at_0,
                          "endIndex": insert_at_0 + len(new_clubs)},
                "inheritFromBefore": True,
            }
        }]
        rfill._retry(ws.spreadsheet.batch_update, {"requests": requests})
        # Re-read so the grid + week_col reflect post-insert state
        grid = rfill._retry(ws.get_all_values)
        for offset, (k, v) in enumerate(new_clubs):
            new_row_0 = insert_at_0 + offset
            label = _csv_canonical_label(k)
            inserted_rows.append((new_row_0, k, label, v))
            log.append(f"  + inserted row {new_row_0 + 1}: {label!r} (new club, {v} sales)")

    updates = []

    # Write labels for inserted rows in col B (so future runs match them).
    for new_row_0, k, label, _v in inserted_rows:
        a1 = gspread.utils.rowcol_to_a1(new_row_0 + 1, 2)  # col B = 2
        updates.append({"range": a1, "values": [[label]]})

    # Write week values for existing Costco rows + inserted rows.
    for ri, row in enumerate(grid):
        label = (row[1] if len(row) > 1 else "").strip()
        if not label.lower().startswith("costco"):
            continue
        key = _normalize_store_label(label)
        if key is None:
            continue
        wk_total = by_club.get(key, 0)
        a1 = gspread.utils.rowcol_to_a1(ri + 1, week_col + 1)
        updates.append({"range": a1, "values": [[str(wk_total)]]})
        log.append(f"  {a1} ({label}) ← {wk_total}")

    # Total Store Count = count of stores selling this week.
    selling_stores = sum(1 for v in by_club.values() if v > 0)
    for ri, row in enumerate(grid):
        label = (row[1] if len(row) > 1 else "").strip().lower()
        if label == "total store count":
            a1 = gspread.utils.rowcol_to_a1(ri + 1, week_col + 1)
            updates.append({"range": a1, "values": [[str(selling_stores)]]})
            log.append(f"  {a1} (Total Store Count) ← {selling_stores}")
            break

    # Dry-run path: report the new clubs that WOULD have been inserted.
    if dry_run and new_clubs:
        for k, v in new_clubs:
            log.append(f"  [DRY-RUN] would insert: {_csv_canonical_label(k)!r} ← {v}")
    if dry_run:
        return [f"[DRY-RUN retail-costco] {ws.title}: would write {len(updates)} cells, insert {len(new_clubs)} new row(s)"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        return [f"[OK retail-costco] {ws.title}: wrote {len(updates)} cells, inserted {len(inserted_rows)} new row(s)"] + log
    return [f"[skip-retail] {ws.title}: no Costco rows found"]


def fill_per_icd_office_totals(ws: gspread.Worksheet,
                                sara_byday: Dict[str, Dict[str, int]],
                                tab_icds: List[str],
                                week_col_label: str,
                                dry_run: bool = False,
                                logfn=print) -> List[str]:
    """Fill per-ICD office-total metrics (Internet, Total New Lines) into
    each ICD's section of the tab. AVG Sales per Leader is computed in
    the sheet via formula reference and skipped here — Active Headcount
    needs to be populated first before we can compute it.

    For multi-ICD tabs, the function scopes its row-label lookups to
    each ICD's section so 'Internet' in MJ's block doesn't shadow 'Internet'
    in Akib's block."""
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-retail-office] {ws.title}: empty tab"]
    week_col = _find_week_col(grid, week_col_label)
    if week_col is None:
        return [f"[skip-retail-office] {ws.title}: no column for week {week_col_label}"]

    ranges = _find_icd_section_ranges(grid, tab_icds)
    if not ranges:
        return [f"[skip-retail-office] {ws.title}: no ICD sections found"]

    updates: List[Dict] = []
    for icd_norm, (start, end) in ranges.items():
        # Sara Plus By Day keys are the ICD's first+last names (Title Case).
        # Try a few canonical forms in order; pick the first match.
        candidates = [icd_norm, icd_norm.replace("amjad", "amjad")]
        # Sara Plus key uses _norm_owner format (lowercase, [office] stripped)
        data = sara_byday.get(icd_norm, {})
        if not data:
            # Fall back: scan for any key whose last word matches
            last = icd_norm.split()[-1]
            for k in sara_byday:
                if k.split()[-1] == last:
                    data = sara_byday[k]
                    break
        if not data:
            log.append(f"  [miss-icd] {icd_norm!r}: no Sara Plus By Day data")
            continue

        # Metric → (sheet label, source measure name)
        for sheet_label, src_measure in [
            ("Internet",        "Internet"),
            ("Total New Lines", "Wireless Lines"),
        ]:
            row_0 = _find_label_row_in_range(grid, sheet_label, start, end)
            if row_0 is None:
                log.append(f"  [miss-row] {icd_norm!r} → no '{sheet_label}' row")
                continue
            val = data.get(src_measure)
            if val is None:
                log.append(f"  [miss-measure] {icd_norm!r} → no '{src_measure}' in data")
                continue
            a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
            updates.append({"range": a1, "values": [[str(val)]]})
            log.append(f"  {a1} {icd_norm!r} {sheet_label} ← {val}")

    if dry_run:
        return [f"[DRY-RUN retail-office] {ws.title}: would write {len(updates)} cells"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        return [f"[OK retail-office] {ws.title}: wrote {len(updates)} cells"] + log
    return [f"[skip-retail-office] {ws.title}: nothing to write"]


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

    # Per-ICD office totals come from the existing Sara Plus By Day pull
    # (already cached by the NDS run). The Retail ICDs (Amjad Malhas,
    # Boaktear Chowdhury, Ronald Dawson) all appear in that CSV.
    sara_byday = tableau_http.parse_sara_plus_byday(
        OUTPUT_DIR / "opt_nds_sara_plus_byday.csv")
    logfn(f"OPT Retail: parsed {len(sara_byday)} ICDs from Sara Plus By Day")

    # Step 3: walk the Retail tabs.
    client = rfill._client()
    sh = client.open_by_key(ALPHALETE_ORG_SHEET_ID)
    week_col_label = _current_target_week_col_label()
    logfn(f"OPT Retail: target week column = {week_col_label!r}")

    filled: List[str] = []
    skipped: List[str] = []
    for ws in rfill._retry(sh.worksheets):
        title = ws.title
        if not title.endswith(" - Retail"):
            continue
        ok_any = False
        # Costco section is only on Boaktear's tab; per-ICD office totals
        # apply to any Retail tab that's in RETAIL_TAB_ICDS.
        if "boaktear" in title.lower():
            for ln in fill_costco_section(ws, by_club, week_col_label,
                                           dry_run, logfn):
                logfn(f"OPT Retail: {ln}")
                if ln.startswith(("[OK", "[DRY-RUN")):
                    ok_any = True
        if title in RETAIL_TAB_ICDS:
            for ln in fill_per_icd_office_totals(
                    ws, sara_byday, RETAIL_TAB_ICDS[title],
                    week_col_label, dry_run, logfn):
                logfn(f"OPT Retail: {ln}")
                if ln.startswith(("[OK", "[DRY-RUN")):
                    ok_any = True
        if ok_any:
            filled.append(title)
        elif title in RETAIL_TAB_ICDS or "boaktear" in title.lower():
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

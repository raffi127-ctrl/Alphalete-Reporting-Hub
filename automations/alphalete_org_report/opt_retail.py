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
    _read_tab_csv,
    download_crosstab as _download_crosstab,
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


# Per-owner office churn rates. Custom view 'RETAILPULL' filters the
# CHURNRATES dashboard to the Retail-relevant owners; Megan confirmed
# 2026-05-22 the saved view shows all retail owners (not pre-filtered
# to Boaktear). The Owner (+/-) Rep table has one row per Owner & Office
# with 0-30 / 30 / 60 / 90 Day Churn %; we use 0-30, 60, 90 (skip 30).
RETAIL_CHURN_URL = (
    "https://us-east-1.online.tableau.com/t/sci/views/"
    "DropshipV_2/CHURNRATES/"
    "244b4740-4d16-4ee8-94e4-d88941315395/RETAILPULL.csv"
)
RETAIL_CHURN_FILENAME = "opt_retail_churn.csv"

# SARAPLUSSALESSUMMARY and ABPCONVERSIONS dashboards each have a
# per-owner worksheet that's NOT addressable via the HTTP .csv endpoint
# (the endpoint always exports the first / 'primary' worksheet, which
# in both cases is the National Summary single-row aggregate). Verified
# 2026-05-22: every plausible URL slug for the per-owner sheet returned
# 404 from the HTTP endpoint.
#
# So both go through the UI Crosstab download path - same code NDS uses
# for 'Sheet 7 (5)' Direct Deposit and the Rep Breakdown chart. Slower
# (~30s each via Playwright) but it's the only way to pull worksheets
# nested inside a multi-worksheet dashboard.
#
# Each tuple: (page URL to load, Crosstab dialog worksheet name, filename)
RETAIL_SARA_PLUS_OFFICE_VIEW = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DropshipV_2/SARAPLUSSALESSUMMARY/"
    "4e5c4964-3f91-4d93-b362-f8768b771e67/RETAILPULL?:iid=2",
    "Sara Plus Sales Summary (2)",
    "opt_retail_sara_plus_office.csv",
)

RETAIL_ABP_VIEW = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DropshipV_2/ABPCONVERSIONS/"
    "2ff5a739-24cf-461e-9b92-7da888196e21/RETAILPULL?:iid=1",
    "ABP National Average (2)",
    "opt_retail_abp.csv",
)


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


def _office_row_filter(rows: List[List[str]], header: List[str],
                       owner_col: int) -> List[Tuple[str, List[str]]]:
    """Yield (norm_owner, row) for rows that represent OFFICE-level totals
    (one per Owner & Office), filtering out per-rep sub-rows.

    Tableau's Owner (+/-) Rep tables emit one office row per owner +
    multiple per-rep rows beneath it. The office row has the owner name
    set, and EITHER (a) no Rep value, or (b) Rep == 'Total' / blank, or
    (c) is the first row with that owner. We use the 'first row per
    owner' heuristic since the Rep column's exact contents differ between
    views (CHURNRATES vs SARAPLUSSALESSUMMARY vs ABPCONVERSIONS).

    If the CSV is already one-row-per-owner (no per-rep sub-rows), this
    just yields every row.
    """
    seen: Dict[str, bool] = {}
    out: List[Tuple[str, List[str]]] = []
    rep_i = tableau_http.col_idx(header, "Rep")
    for r in rows:
        if len(r) <= owner_col:
            continue
        owner = tableau_http._norm_owner(r[owner_col])
        if not owner or owner in seen:
            continue
        # If there's a Rep column, skip rows where Rep names a specific
        # person — those are sub-rows under the office. An empty Rep,
        # 'Total', or 'Office/Organization Average' marker is the
        # office aggregate (varies by view).
        if rep_i is not None and rep_i < len(r):
            rep_val = (r[rep_i] or "").strip().lower()
            if rep_val and rep_val not in {"total", "office/organization average"}:
                continue
        seen[owner] = True
        out.append((owner, r))
    return out


def _col_starts_with(header: List[str], prefix: str) -> Optional[int]:
    """First column whose normalized name starts with `prefix`. Tolerates
    Tableau's '(copy 2)' artifact on duplicated columns - e.g. the actual
    CHURNRATES/RETAILPULL header is 'Owner & Office  (copy 2)', not the
    canonical 'Owner & Office'."""
    p = " ".join(prefix.lower().split())
    for i, h in enumerate(header):
        if " ".join((h or "").lower().split()).startswith(p):
            return i
    return None


def parse_churn_rates(path: Path) -> Dict[str, Dict[str, str]]:
    """Parse CHURNRATES/RETAILPULL CSV -> {owner_norm: {bucket: pct_str}}.

    Long format: one row per (Day Range Pivot, Owner). Columns
    (Megan, 2026-05-22):
      Day Range Pivot | Owner & Office  (copy 2) | 30 Day Churn |
      30-60 Color Churn (copy) | Activated Wireless Lines |
      Churn Rate | Disconnect count (copy) | Min. Calculation1

    Day Range Pivot is the bucket label ('0-30 Day Churn', '60 Day Churn',
    etc.); Churn Rate is the percentage we want. The bare '30 Day Churn'
    bucket isn't on the sheet, so we filter to just 0-30 / 60 / 90.
    """
    rows = tableau_http.parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    range_i = tableau_http.col_idx(header, "Day Range Pivot")
    owner_i = _col_starts_with(header, "Owner & Office")
    rate_i = tableau_http.col_idx(header, "Churn Rate")
    if range_i is None or owner_i is None or rate_i is None:
        return {}
    wanted = {"0-30 Day Churn", "60 Day Churn", "90 Day Churn"}
    out: Dict[str, Dict[str, str]] = {}
    for r in rows[1:]:
        if max(range_i, owner_i, rate_i) >= len(r):
            continue
        bucket = (r[range_i] or "").strip()
        if bucket not in wanted:
            continue
        owner = tableau_http._norm_owner(r[owner_i])
        if not owner:
            continue
        val = (r[rate_i] or "").strip()
        if val:
            out.setdefault(owner, {})[bucket] = val
    return out


def parse_sara_plus_office_totals(path: Path) -> Dict[str, Dict[str, int]]:
    """Parse SARAPLUSSALESSUMMARY default view -> {owner_norm: {metric: int}}.

    Returns the office-level totals needed to compute Next Up % and
    Extra/Premium %: 'Next Up', 'New/Port Lines', 'Premium/Elite', 'Extra'.
    """
    rows = tableau_http.parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    owner_i = tableau_http.col_idx(header, "Owner & Office")
    if owner_i is None:
        return {}
    # Try a few label variants — Tableau may shorten 'Premium/Elite' to
    # 'Premium' or split into 'Premium/...' depending on which worksheet
    # the .csv endpoint serves. Pick the first column whose label starts
    # with the wanted prefix.
    def _col_starts(prefix: str) -> Optional[int]:
        p = prefix.lower().rstrip()
        for i, h in enumerate(header):
            if (h or "").strip().lower().startswith(p):
                return i
        return None
    metric_cols = {
        "Next Up":        tableau_http.col_idx(header, "Next Up"),
        "New/Port Lines": tableau_http.col_idx(header, "New/Port Lines"),
        "Premium/Elite": (tableau_http.col_idx(header, "Premium/Elite")
                          or _col_starts("Premium")),
        "Extra":          tableau_http.col_idx(header, "Extra"),
    }
    out: Dict[str, Dict[str, int]] = {}
    for owner, r in _office_row_filter(rows[1:], header, owner_i):
        bucket: Dict[str, int] = {}
        for label, col in metric_cols.items():
            if col is None or col >= len(r):
                continue
            try:
                bucket[label] = int(float((r[col] or "0").replace(",", "")))
            except ValueError:
                continue
        if bucket:
            out[owner] = bucket
    return out


def parse_abp_conversions(path: Path) -> Dict[str, str]:
    """Parse ABPCONVERSIONS default view -> {owner_norm: 'ABP %' string}.

    The sheet's 'ABP %' row gets the NEW&PORT ABP %, not the upgrade
    column (Megan 2026-05-22). The CSV's column labels for grouped
    headers are usually flattened by Tableau as 'new & port: ABP %' or
    'ABP % (new & port)' or just 'ABP %' twice — try a few variants
    in priority order; first match wins.
    """
    rows = tableau_http.parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    owner_i = tableau_http.col_idx(header, "Owner & Office")
    if owner_i is None:
        return {}
    # Candidates in priority order. The default-view CSV column names
    # aren't documented; this list trades off being permissive without
    # accidentally picking the UPGRADE column.
    abp_col: Optional[int] = None
    for label in (
        "new & port: ABP %",
        "ABP % (new & port)",
        "new & port ABP %",
        "new and port ABP %",
        "ABP % new & port",
        "ABP %",                # plain — only used if no qualifier columns
    ):
        c = tableau_http.col_idx(header, label)
        if c is not None:
            abp_col = c
            break
    if abp_col is None:
        return {}
    out: Dict[str, str] = {}
    for owner, r in _office_row_filter(rows[1:], header, owner_i):
        if abp_col < len(r):
            v = (r[abp_col] or "").strip()
            if v:
                out[owner] = v
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


# Sheet rows we fill from the office-metrics pull. Labels match what
# the sheet actually has on the Akib tab today; some include a typo
# ('Extra/Preium %') Megan hasn't fixed yet. We pass both spellings so
# we still write if Megan corrects the typo later.
_OFFICE_METRIC_ROW_LABELS = {
    "0-30 Day Churn":   ["0-30 Day Churn"],
    "60 Day Churn":     ["60 Day Churn"],
    "90 Day Churn":     ["90 Day Churn"],            # case-insensitive match handles 'day' vs 'Day'
    "Next Up %":        ["Next Up %"],               # likewise 'Next up %'
    "Extra/Premium %":  ["Extra/Premium %", "Extra/Preium %"],
    "ABP %":            ["ABP %"],
}


def _find_first_label_match(grid: List[List[str]], candidates: List[str],
                             start: int, end: int) -> Optional[int]:
    """Try each label spelling in order; first hit wins. Lets us tolerate
    the 'Extra/Preium %' typo on Boaktear's tab without losing the canonical
    label match if Megan corrects it."""
    for label in candidates:
        row_0 = _find_label_row_in_range(grid, label, start, end)
        if row_0 is not None:
            return row_0
    return None


def _format_pct(value: float) -> str:
    """Format a fraction (0.40) or percentage-int (40) into the sheet's
    'XX.XX%' style. Tableau CSV exports give percentages as either a
    decimal (0.047) or a pre-formatted string ('4.7%'); accept both."""
    return f"{value:.2%}"


def fill_office_metrics(ws: gspread.Worksheet,
                        churn: Dict[str, Dict[str, str]],
                        sara_office: Dict[str, Dict[str, int]],
                        abp: Dict[str, str],
                        tab_icds: List[str],
                        week_col_label: str,
                        icds_to_write: Optional[List[str]] = None,
                        dry_run: bool = False,
                        logfn=print) -> List[str]:
    """Fill the 6 office-level OPT metrics into each ICD's section of a
    Retail tab: 0-30 / 60 / 90 Day Churn (from CHURNRATES/RETAILPULL),
    Next Up % + Extra/Premium % (computed from SARAPLUSSALESSUMMARY office
    totals), and ABP % (from ABPCONVERSIONS).

    Multi-ICD tabs (Boaktear's Akib+MJ) get separate sections per ICD
    so 'ABP %' in MJ's block doesn't shadow Akib's. If `icds_to_write`
    is set, only those ICD section(s) are filled — the preview-on-Akib
    flow passes `['boaktear chowdhury']` so MJ stays untouched until
    Megan signs off ([[feedback_preview_marcellus]]).
    """
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-retail-opt] {ws.title}: empty tab"]
    week_col = _find_week_col(grid, week_col_label)
    if week_col is None:
        return [f"[skip-retail-opt] {ws.title}: no column for week {week_col_label}"]

    ranges = _find_icd_section_ranges(grid, tab_icds)
    if not ranges:
        return [f"[skip-retail-opt] {ws.title}: no ICD sections found"]

    scope = {i.lower() for i in icds_to_write} if icds_to_write else None
    updates: List[Dict] = []
    for icd_norm, (start, end) in ranges.items():
        if scope is not None and icd_norm not in scope:
            log.append(f"  [scope-skip] {icd_norm!r} (preview limited to {scope})")
            continue
        # Look up this ICD's office data in each pull. Owner names in the
        # CSVs are normalized via _norm_owner; the section header in col A
        # ('Akib', 'MJ', 'BOAKTEAR CHOWDHURY [motiv8…]') may not exactly
        # match the CSV. Fall back to last-name match like fill_per_icd_*.
        def _lookup(d):
            if icd_norm in d:
                return d[icd_norm]
            last = icd_norm.split()[-1]
            for k in d:
                if k.split()[-1] == last:
                    return d[k]
            return None
        c_row = _lookup(churn) or {}
        s_row = _lookup(sara_office) or {}
        abp_val = _lookup(abp)

        # 1) Churn rates — write the Tableau % string verbatim if present.
        for sheet_label in ("0-30 Day Churn", "60 Day Churn", "90 Day Churn"):
            row_0 = _find_first_label_match(grid, _OFFICE_METRIC_ROW_LABELS[sheet_label],
                                            start, end)
            if row_0 is None:
                log.append(f"  [miss-row] {icd_norm!r} -> no '{sheet_label}' row")
                continue
            val = c_row.get(sheet_label)
            if not val:
                log.append(f"  [miss-data] {icd_norm!r} -> no churn data for {sheet_label}")
                continue
            a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
            updates.append({"range": a1, "values": [[val]]})
            log.append(f"  {a1} {icd_norm!r} {sheet_label} <- {val}")

        # 2) Next Up % = office Next Up / office New/Port Lines.
        next_up = s_row.get("Next Up")
        new_port = s_row.get("New/Port Lines")
        if next_up is not None and new_port and new_port > 0:
            row_0 = _find_first_label_match(grid, _OFFICE_METRIC_ROW_LABELS["Next Up %"],
                                            start, end)
            if row_0 is not None:
                pct = _format_pct(next_up / new_port)
                a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
                updates.append({"range": a1, "values": [[pct]]})
                log.append(f"  {a1} {icd_norm!r} Next Up % <- {pct} ({next_up}/{new_port})")
            else:
                log.append(f"  [miss-row] {icd_norm!r} -> no 'Next Up %' row")
        else:
            log.append(f"  [miss-data] {icd_norm!r} -> missing Next Up or New/Port Lines")

        # 3) Extra/Premium % = (office Premium/Elite + office Extra) / office New/Port Lines.
        premium = s_row.get("Premium/Elite")
        extra = s_row.get("Extra")
        if (premium is not None and extra is not None
                and new_port and new_port > 0):
            row_0 = _find_first_label_match(grid, _OFFICE_METRIC_ROW_LABELS["Extra/Premium %"],
                                            start, end)
            if row_0 is not None:
                pct = _format_pct((premium + extra) / new_port)
                a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
                updates.append({"range": a1, "values": [[pct]]})
                log.append(f"  {a1} {icd_norm!r} Extra/Premium % <- {pct} "
                           f"(({premium}+{extra})/{new_port})")
            else:
                log.append(f"  [miss-row] {icd_norm!r} -> no 'Extra/Premium %' row")
        else:
            log.append(f"  [miss-data] {icd_norm!r} -> missing Premium/Elite or Extra")

        # 4) ABP % — write the Tableau % string verbatim.
        if abp_val:
            row_0 = _find_first_label_match(grid, _OFFICE_METRIC_ROW_LABELS["ABP %"],
                                            start, end)
            if row_0 is not None:
                a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
                updates.append({"range": a1, "values": [[abp_val]]})
                log.append(f"  {a1} {icd_norm!r} ABP % <- {abp_val}")
            else:
                log.append(f"  [miss-row] {icd_norm!r} -> no 'ABP %' row")
        else:
            log.append(f"  [miss-data] {icd_norm!r} -> no ABP % data")

    if dry_run:
        return [f"[DRY-RUN retail-opt] {ws.title}: would write {len(updates)} cells"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        return [f"[OK retail-opt] {ws.title}: wrote {len(updates)} cells"] + log
    return [f"[skip-retail-opt] {ws.title}: nothing to write"]


def _http_download(session, url: str, filename: str, logfn,
                   errors: List[str]) -> Optional[Path]:
    """Download a Tableau view CSV to OUTPUT_DIR/<filename>. Returns the
    path on success, None on failure (and appends to `errors`)."""
    out_path = OUTPUT_DIR / filename
    try:
        logfn(f"OPT Retail: HTTP downloading {filename}...")
        r = session.get(url, allow_redirects=True, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} ({len(r.content)} bytes)")
        out_path.write_bytes(r.content)
        return out_path
    except Exception as e:
        msg = f"{filename}: {type(e).__name__}: {str(e)[:120]}"
        logfn(f"OPT Retail: HTTP error {msg}")
        errors.append(msg)
        return None


# Akib-section-only preview scope. Megan signs off on the Akib fill, then
# we drop this list in the rollout commit so MJ + Ronald also get filled.
# [[feedback_preview_marcellus]]: every new multi-tab automation previews
# on one section before going wide.
_PREVIEW_ICDS_AKIB_ONLY = ["boaktear chowdhury"]


def run_retail_costco(dry_run: bool = False, logfn=print) -> dict:
    """Pull every Retail Tableau source + fill Boaktear's Retail tab:
      - Costco section (per-store wireless lines)
      - Akib's office metrics (churn 0-30/60/90, Next Up %, Extra/Premium %, ABP %)
    Returns {filled: [...], skipped: [...], errors: [...]}.

    Per [[feedback_no_cross_report_data_reuse]] every source CSV is
    downloaded fresh by this run — never reads an artifact produced
    by another Hub card.
    """
    errors: List[str] = []
    session = tableau_http._grab_session()

    # ---- Step 1: pull every CSV this run needs ----
    # HTTP-direct pulls: Costco by club + Churn rates. Their views are
    # single-worksheet OR the .csv endpoint serves the right worksheet
    # for them - fast (~1s each).
    by_club_path = _http_download(session, RETAIL_BY_CLUB_URL,
                                   RETAIL_BY_CLUB_FILENAME, logfn, errors)
    if by_club_path is None:
        # The Costco fill is the existing/blocking output — abort if its
        # source failed. (The new office-metric fills could continue but
        # leaving the run partial mid-rollout is more confusing.)
        return {"filled": [], "skipped": [], "errors": errors}
    churn_path = _http_download(session, RETAIL_CHURN_URL,
                                 RETAIL_CHURN_FILENAME, logfn, errors)

    # UI Crosstab pulls: SARA per-owner + ABP per-owner. These worksheets
    # live inside a multi-worksheet dashboard and HTTP can't address them
    # individually - Playwright drives the Download → Crosstab dialog.
    sara_office_path: Optional[Path] = None
    sara_url, sara_sheet, sara_fname = RETAIL_SARA_PLUS_OFFICE_VIEW
    try:
        logfn(f"OPT Retail: UI Crosstab → {sara_sheet!r} → {sara_fname}...")
        sara_office_path = _download_crosstab(
            sara_url, sara_sheet, OUTPUT_DIR / sara_fname, verbose=False)
    except Exception as e:
        msg = f"{sara_fname}: {type(e).__name__}: {str(e)[:120]}"
        logfn(f"OPT Retail: Crosstab error {msg}")
        errors.append(msg)

    abp_path: Optional[Path] = None
    abp_url, abp_sheet, abp_fname = RETAIL_ABP_VIEW
    try:
        logfn(f"OPT Retail: UI Crosstab → {abp_sheet!r} → {abp_fname}...")
        abp_path = _download_crosstab(
            abp_url, abp_sheet, OUTPUT_DIR / abp_fname, verbose=False)
    except Exception as e:
        msg = f"{abp_fname}: {type(e).__name__}: {str(e)[:120]}"
        logfn(f"OPT Retail: Crosstab error {msg}")
        errors.append(msg)

    # ---- Step 2: parse every CSV ----
    by_club = parse_retail_by_club(by_club_path)
    logfn(f"OPT Retail: parsed {len(by_club)} Costco store(s): "
          f"{sorted(by_club.items())}")

    churn = parse_churn_rates(churn_path) if churn_path else {}
    logfn(f"OPT Retail: parsed churn rates for {len(churn)} office(s): "
          f"{sorted(churn.keys())}")

    sara_office = parse_sara_plus_office_totals(sara_office_path) if sara_office_path else {}
    logfn(f"OPT Retail: parsed Sara Plus office totals for {len(sara_office)} office(s): "
          f"{sorted(sara_office.keys())}")

    abp = parse_abp_conversions(abp_path) if abp_path else {}
    logfn(f"OPT Retail: parsed ABP % for {len(abp)} office(s): "
          f"{sorted(abp.keys())}")

    # Per-ICD office totals for Internet/Total New Lines still come from
    # the NDS Sara Plus By Day pull. ANTI-PATTERN per
    # [[feedback_no_cross_report_data_reuse]] — track in
    # [[project_alphalete_org_report]] 'ANTI-PATTERN to fix'; separate
    # follow-up commit will move it to a Retail-owned pull.
    sara_byday = tableau_http.parse_sara_plus_byday(
        OUTPUT_DIR / "opt_nds_sara_plus_byday.csv")
    logfn(f"OPT Retail: parsed {len(sara_byday)} ICDs from Sara Plus By Day")

    # ---- Step 3: walk the Retail tabs ----
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
            # New office-metric fill (churn + Next Up % + Extra/Premium %
            # + ABP %). PREVIEW: scoped to the Akib section only so Megan
            # can sign off before rolling MJ + Ronald in commit 2.
            for ln in fill_office_metrics(
                    ws, churn, sara_office, abp,
                    RETAIL_TAB_ICDS[title], week_col_label,
                    icds_to_write=_PREVIEW_ICDS_AKIB_ONLY,
                    dry_run=dry_run, logfn=logfn):
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

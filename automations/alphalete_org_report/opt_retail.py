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
)
from automations.shared.tableau_patchright import (
    tableau_session,
    download_crosstab_patchright,
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
    # 'Weekproduction' custom view bakes the date range picker to ONE
    # WEEK (Megan 2026-05-22). The default 'RETAILPULL' custom view
    # ran a wider date window, inflating Next Up, Total New Lines,
    # Active Headcount, etc. across multiple weeks — verified wrong
    # against the sheet's actual week values. This view must be
    # configured as a *dynamic* date filter (auto-advances) for the
    # report to stay correct week-over-week.
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DropshipV_2/SARAPLUSSALESSUMMARY/"
    "53654748-be66-4049-84d8-1a4a0464ba6d/Weekproduction?:iid=1",
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

# Per-owner activation rates per sales-date bucket. Sheet row
# 'Activation /Approval %' maps to the '60+ Days' bucket (Megan
# 2026-05-22; circled 91% on Boaktear's row matches the sheet's
# DZ value 91.00%). NDS already pulls the same workbook view via
# the HTTP CSV path; Retail pulls its own copy
# ([[feedback_no_cross_report_data_reuse]]).
RETAIL_ACTIVATION_URL = (
    "https://us-east-1.online.tableau.com/t/sci/views/"
    "DropshipV_2/ACTIVATIONRATES.csv"
)
RETAIL_ACTIVATION_FILENAME = "opt_retail_activation.csv"

# Money Lost from TMP — Megan 2026-05-22 mapped this to the
# 'Missed EC Bonus' row x 'Grand Total to ICD' column in the
# ECBONUSAWARENESS dashboard's DOWNLINEVIEW custom view. Sheet's
# DZ85 = $0.00 for Boaktear, matching the Tableau screenshot.
# This is a multi-worksheet dashboard (PROGRAM SUMMARY / DD BY REP /
# DD BY OWNER (ORG) / EC BONUS AWARENESS / DD DETAIL / etc), so we
# go through the UI Crosstab path - the worksheet name to pick is
# TBD until we run the dialog (the Crosstab dialog lists every
# worksheet by name; we pick the EC BONUS AWARENESS one).
RETAIL_MONEY_LOST_VIEW = (
    # :iid=1 leaves 'Consultant ORG Title' (our target) UNSELECTED at
    # load so the click registers as a fresh selection — same toggle-off
    # trap that SARA hits. 'ICD EC Bonus' only contains the self-ICD
    # row; 'Consultant ORG Title' has the full downline org table with
    # one row per (downline ICD, measure). (Megan 2026-05-22.)
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DirectDepositICDVIEWVersion2_0/ECBONUSAWARENESS/"
    "538e62a7-3c2a-45cd-9a91-6784fbc4c7d8/DOWNLINEVIEW?:iid=2",
    "Consultant ORG Title",
    "opt_retail_money_lost.csv",
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
    """Parse 'Sara Plus Sales Summary (2)' Crosstab CSV (UTF-16 tab-delim)
    -> {owner_norm: {metric: int, '_active_reps': int}}.

    Layout (verified 2026-05-22 against Megan's manual download):
      Owner & Office | Rep | rep.Rep Number | ATV | DTV | Internet | AIA |
      New/Port Lines | ATT Protection Plan Total Attachment | Next Up |
      Premium/Elite | Extra

    Each owner has multiple rows - one per rep + a 'Total' row with the
    office aggregate. We use the Total row for office-level metrics
    (Next Up, New/Port Lines, Premium/Elite, Extra) and count the
    non-Total rows with any metric > 0 for Active Headcount on Tableau
    (= number of reps with a sale of any kind, per Megan 2026-05-22).
    """
    rows = _read_tab_csv(path)
    if not rows or len(rows) < 2:
        return {}
    header = rows[0]
    owner_i = _col_starts_with(header, "Owner & Office")
    rep_i = _col_starts_with(header, "Rep")
    if owner_i is None or rep_i is None:
        return {}
    metric_cols = {
        "Next Up":        tableau_http.col_idx(header, "Next Up"),
        "New/Port Lines": tableau_http.col_idx(header, "New/Port Lines"),
        "Premium/Elite":  tableau_http.col_idx(header, "Premium/Elite"),
        "Extra":          tableau_http.col_idx(header, "Extra"),
    }
    # All numeric metric columns - used to detect "rep had any sale"
    # for Active Headcount. Skips the rep-number / owner / rep-name cols.
    numeric_cols = [i for i, h in enumerate(header)
                    if i not in (owner_i, rep_i)
                    and (h or "").strip().lower() != "rep.rep number"]
    out: Dict[str, Dict[str, int]] = {}
    # Tableau's XLSX export blanks the owner cell on continuation rows
    # (only the first row of each group has the owner name); the CSV
    # export repeats it. Forward-fill so both formats parse identically.
    current_owner: Optional[str] = None
    for r in rows[1:]:
        if max(owner_i, rep_i, *(c for c in metric_cols.values() if c is not None)) >= len(r):
            continue
        raw_owner = (r[owner_i] or "").strip()
        if raw_owner:
            current_owner = _norm_owner(raw_owner)
        if not current_owner:
            continue
        owner = current_owner
        rep_val = (r[rep_i] or "").strip()
        bucket = out.setdefault(owner, {"_active_reps": 0})
        if rep_val.lower() == "total":
            # Office-aggregate row - fill the Next Up / New/Port Lines / etc.
            for label, col in metric_cols.items():
                if col is None or col >= len(r):
                    continue
                try:
                    bucket[label] = int(float((r[col] or "0").replace(",", "")))
                except ValueError:
                    continue
        else:
            # Per-rep row - count toward Active Headcount if ANY numeric
            # value > 0 (Megan 2026-05-22 spec). All-zero rows don't count.
            had_sale = False
            for c in numeric_cols:
                if c >= len(r):
                    continue
                try:
                    if int(float((r[c] or "0").replace(",", ""))) > 0:
                        had_sale = True
                        break
                except ValueError:
                    continue
            if had_sale:
                bucket["_active_reps"] += 1
    # Drop owners that ended up with no Total row (shouldn't happen but defensive)
    return {k: v for k, v in out.items()
            if any(label in v for label in metric_cols)}


def parse_money_lost_from_tmp(path: Path) -> Dict[str, str]:
    """Parse EC BONUS AWARENESS / DOWNLINEVIEW Crosstab -> {owner_norm: dollar_str}.

    The 'Money Lost from TMP' sheet metric = the 'Missed EC Bonus' row's
    'Grand Total to ICD' value, per downline owner (Megan 2026-05-22;
    screenshot showed Boaktear's row at $0.00 matching DZ85).

    The Crosstab CSV's exact column layout is unknown until we have a
    file - parser is defensive about column names. Looks for:
      - An owner column ('ICD.Full Name' or 'Owner & Office' or
        anything containing 'name' / 'owner')
      - A row-label column that contains 'Missed EC Bonus' for the
        right row OR a metric-name pivot column
      - A 'Grand Total to ICD' (or 'Grand Total' / 'Total $ to ICD') column
    Returns {} when the file structure doesn't match - caller logs the
    empty parse so we can iterate the parser on a real file.
    """
    rows = _read_tab_csv(path)
    if not rows or len(rows) < 2:
        return {}
    header = rows[0]
    # Owner column candidates (in order of preference)
    owner_i: Optional[int] = None
    for label in ("ICD.Full Name", "ICD Full Name", "Owner & Office", "Full Name"):
        owner_i = tableau_http.col_idx(header, label)
        if owner_i is not None:
            break
    if owner_i is None:
        owner_i = _col_starts_with(header, "ICD")  # last resort
    # Grand Total column
    total_i: Optional[int] = None
    for label in ("Grand Total to ICD", "Grand Total", "Total $ to ICD",
                  "Total to ICD"):
        total_i = tableau_http.col_idx(header, label)
        if total_i is not None:
            break
    # Row-label column (the row says 'Missed EC Bonus' for the right row)
    label_i: Optional[int] = None
    for h_label in ("Measure Names", "Metric", "Row Label", "Bonus Type"):
        label_i = tableau_http.col_idx(header, h_label)
        if label_i is not None:
            break
    if owner_i is None or total_i is None:
        return {}
    out: Dict[str, str] = {}
    for r in rows[1:]:
        if max(owner_i, total_i) >= len(r):
            continue
        # If there's a label col, filter to 'Missed EC Bonus' rows only.
        if label_i is not None and label_i < len(r):
            lbl = (r[label_i] or "").strip().lower()
            if "missed" not in lbl or "bonus" not in lbl:
                continue
        owner = _norm_owner(r[owner_i])
        val = (r[total_i] or "").strip()
        if owner and val:
            out[owner] = val
    return out


def parse_abp_conversions(path: Path) -> Dict[str, str]:
    """Parse ABPCONVERSIONS 'ABP National Average (2)' UI Crosstab CSV
    (UTF-16, tab-delimited) -> {owner_norm: ABP_%_str}.

    Header is TWO rows because of Tableau's grouped columns:
      Row 1:  [blank]  [blank]  'new & port'  'new & port'  'upgrade'  'upgrade'
      Row 2:  'Owner & Office '  'Date Range'  'ABP %'  'Wireless Lines'  'ABP %'  'Wireless Lines'

    We need the 'new & port' x 'ABP %' column (Megan 2026-05-22; upgrade
    column ignored). The other ABP % column is the upgrade group.
    """
    rows = _read_tab_csv(path)
    if not rows or len(rows) < 3:
        return {}
    group_row = rows[0]
    measure_row = rows[1]
    owner_col: Optional[int] = None
    for i, h in enumerate(measure_row):
        if "owner" in (h or "").lower() and "office" in (h or "").lower():
            owner_col = i
            break
    abp_col: Optional[int] = None
    for i in range(min(len(group_row), len(measure_row))):
        g = (group_row[i] or "").strip().lower()
        m = (measure_row[i] or "").strip().lower()
        if "new" in g and "port" in g and m == "abp %":
            abp_col = i
            break
    if owner_col is None or abp_col is None:
        return {}
    out: Dict[str, str] = {}
    for r in rows[2:]:
        if max(owner_col, abp_col) >= len(r):
            continue
        owner = _norm_owner(r[owner_col])
        val = (r[abp_col] or "").strip()
        if owner and val:
            out[owner] = val
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
    "0-30 Day Churn":             ["0-30 Day Churn"],
    "60 Day Churn":               ["60 Day Churn"],
    "90 Day Churn":               ["90 Day Churn"],            # case-insensitive match handles 'day' vs 'Day'
    "Next Up %":                  ["Next Up %"],               # likewise 'Next up %'
    "Extra/Premium %":            ["Extra/Premium %", "Extra/Preium %"],
    "ABP %":                      ["ABP %"],
    "Active Headcount on Tableau": ["Active Headcount on Tableau"],
    # Sheet label has a SPACE before the slash ('Activation /Approval %').
    # Pass both spellings in case Megan corrects it later.
    "Activation /Approval %":     ["Activation /Approval %", "Activation/Approval %"],
    "Money Lost from TMP":        ["Money Lost from TMP"],
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
                        activation: Dict[str, str],
                        money_lost: Dict[str, str],
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
        activation_val = _lookup(activation)
        money_lost_val = _lookup(money_lost)

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

        # 5) Active Headcount on Tableau = count of reps with any sale > 0
        # (Megan 2026-05-22). The parse_sara_plus_office_totals counter
        # is stored under '_active_reps' for each owner.
        active_reps = s_row.get("_active_reps")
        if active_reps is not None and active_reps > 0:
            row_0 = _find_first_label_match(
                grid, _OFFICE_METRIC_ROW_LABELS["Active Headcount on Tableau"],
                start, end)
            if row_0 is not None:
                a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
                updates.append({"range": a1, "values": [[str(active_reps)]]})
                log.append(f"  {a1} {icd_norm!r} Active Headcount on Tableau <- {active_reps}")
            else:
                log.append(f"  [miss-row] {icd_norm!r} -> no 'Active Headcount on Tableau' row")

        # 6) Activation /Approval % = 60+ Days bucket from ACTIVATIONRATES.
        # Megan 2026-05-22: sheet's 'Activation /Approval %' row maps to
        # the 60+ Days column on the per-owner Activation Rates table.
        if activation_val:
            row_0 = _find_first_label_match(
                grid, _OFFICE_METRIC_ROW_LABELS["Activation /Approval %"],
                start, end)
            if row_0 is not None:
                a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
                updates.append({"range": a1, "values": [[activation_val]]})
                log.append(f"  {a1} {icd_norm!r} Activation /Approval % <- {activation_val}")
            else:
                log.append(f"  [miss-row] {icd_norm!r} -> no 'Activation /Approval %' row")
        else:
            log.append(f"  [miss-data] {icd_norm!r} -> no Activation % data")

        # 7) Money Lost from TMP = Missed EC Bonus x Grand Total to ICD,
        # from ECBONUSAWARENESS / DOWNLINEVIEW (Megan 2026-05-22). Format
        # comes in as a dollar string ('$0.00', '$7,515.86' etc); write
        # verbatim - the sheet's cell is text/$-formatted already.
        if money_lost_val:
            row_0 = _find_first_label_match(
                grid, _OFFICE_METRIC_ROW_LABELS["Money Lost from TMP"],
                start, end)
            if row_0 is not None:
                a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
                updates.append({"range": a1, "values": [[money_lost_val]]})
                log.append(f"  {a1} {icd_norm!r} Money Lost from TMP <- {money_lost_val}")
            else:
                log.append(f"  [miss-row] {icd_norm!r} -> no 'Money Lost from TMP' row")
        else:
            log.append(f"  [miss-data] {icd_norm!r} -> no Money Lost from TMP data")

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
    activation_path = _http_download(session, RETAIL_ACTIVATION_URL,
                                      RETAIL_ACTIVATION_FILENAME, logfn, errors)

    # UI Crosstab pulls: SARA per-owner + ABP per-owner + Money Lost. These
    # worksheets live inside multi-worksheet dashboards and HTTP can't
    # address them individually. SARA and Money Lost both hit the CDP
    # silent-no-op bug — their thumbnail click registers visually but
    # Tableau refuses to enter the selected state, leaving Download
    # disabled. Patchright (stealth Playwright) launches a non-CDP Chrome
    # that Tableau accepts; uses Order Log's persistent profile so the
    # ownerville login is reused across runs. (Megan confirmed 2026-05-22:
    # Download enables in a regular browser, fails in CDP-attached one.)
    #
    # FALLBACK: if patchright errors (browser launch failure, expired
    # session) and an existing file at the target path is fresh enough,
    # use it. Keeps runs usable even if the new path regresses.
    # Per-view retry budget. SARA's Crosstab dialog is flaky under
    # patchright — succeeds ~1 in 3 first attempts with a silent
    # "Download disabled" failure mode the rest. Retry with an
    # about:blank reset between attempts to clear any leftover dialog
    # state. ABP and Money Lost are deterministic per session (ABP
    # always works first try; Money Lost always silently no-ops — its
    # fallback path is a separate HTML scrape, TODO).
    crosstab_views = [
        ("sara", RETAIL_SARA_PLUS_OFFICE_VIEW, 3),
        ("abp", RETAIL_ABP_VIEW, 1),
        ("money_lost", RETAIL_MONEY_LOST_VIEW, 1),
    ]
    crosstab_paths: Dict[str, Optional[Path]] = {k: None for k, _, _ in crosstab_views}

    def _fallback_existing(filename: str) -> Optional[Path]:
        target = OUTPUT_DIR / filename
        if target.exists() and target.stat().st_size > 500:
            logfn(f"OPT Retail: using existing {filename} "
                  f"({target.stat().st_size:,} bytes) as fallback")
            return target
        return None

    try:
        with tableau_session(verbose=False) as page:
            for key, (url, sheet_name, filename), max_attempts in crosstab_views:
                target = OUTPUT_DIR / filename
                last_err: Optional[Exception] = None
                for attempt in range(1, max_attempts + 1):
                    label = (f"attempt {attempt}/{max_attempts} "
                             if max_attempts > 1 else "")
                    logfn(f"OPT Retail: patchright Crosstab {label}→ "
                          f"{sheet_name!r} → {filename}...")
                    try:
                        crosstab_paths[key] = download_crosstab_patchright(
                            url, sheet_name, target, verbose=False, page=page)
                        last_err = None
                        break
                    except Exception as e:
                        last_err = e
                        if attempt < max_attempts:
                            logfn(f"OPT Retail:   {type(e).__name__}, "
                                  "resetting page + retrying...")
                            try:
                                page.goto("about:blank",
                                          wait_until="domcontentloaded",
                                          timeout=10_000)
                                page.wait_for_timeout(3_000)
                            except Exception:
                                pass
                if last_err is not None:
                    msg = f"{filename}: {type(last_err).__name__}: {str(last_err)[:120]}"
                    logfn(f"OPT Retail: Crosstab error {msg}")
                    errors.append(msg)
                    crosstab_paths[key] = _fallback_existing(filename)
    except Exception as e:
        logfn(f"OPT Retail: patchright session failed: "
              f"{type(e).__name__}: {str(e)[:160]}")
        errors.append(f"patchright session: {type(e).__name__}: {str(e)[:120]}")
        for key, (_, _, filename), _max in crosstab_views:
            crosstab_paths[key] = _fallback_existing(filename)

    sara_office_path = crosstab_paths["sara"]
    abp_path = crosstab_paths["abp"]
    money_lost_path = crosstab_paths["money_lost"]

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

    activation = (tableau_http.parse_activation(activation_path, bucket="60+ Days")
                  if activation_path else {})
    logfn(f"OPT Retail: parsed Activation % (60+ Days) for "
          f"{len(activation)} office(s): {sorted(activation.keys())}")

    money_lost = parse_money_lost_from_tmp(money_lost_path) if money_lost_path else {}
    logfn(f"OPT Retail: parsed Money Lost from TMP for {len(money_lost)} office(s): "
          f"{sorted(money_lost.keys())}")

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
            for ln in fill_office_metrics(
                    ws, churn, sara_office, abp, activation, money_lost,
                    RETAIL_TAB_ICDS[title], week_col_label,
                    icds_to_write=None,
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

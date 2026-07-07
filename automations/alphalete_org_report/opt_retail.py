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

from automations.shared import sheet_flags as _sheet_flags

from automations.recruiting_report import fill as rfill
from automations.alphalete_org_report import tableau_http
from automations.alphalete_org_report.opt_nds import (
    ALPHALETE_ORG_SHEET_ID,
    OUTPUT_DIR,
    ORG_DD_URL,
    ORG_DD_SHEET,
    parse_direct_deposit,
    _current_target_week_col_label,
    _find_row_by_label,
    _find_week_col,
    _norm_owner,
    _read_tab_csv,
)
from automations.shared.tableau_patchright import (
    tableau_session,
    download_crosstab_patchright,
    scrape_view_data_patchright,
    requests_session_from_page,
)


# Each Retail tab's combined-ICD setup. Multi-ICD tabs (like Boaktear's
# Akib + MJ tab) need a list so we can scope row-label lookups to each
# ICD's section. Sara Plus By Day data is keyed on the ICD's full name —
# match it case-insensitively against the section-header text in col A.
RETAIL_TAB_ICDS: Dict[str, List[str]] = {
    "Boaktear Chowdhury (Akib/MJ) - Retail": ["amjad malhas", "boaktear chowdhury"],
    "Ronald Dawson - Retail":                ["ronald dawson"],
}


# HTTP-direct view URL. The CLUBBREAKDOWN-MJAKIB custom view (Megan set
# up 2026-05-27) pre-filters to MJ + Akib at the data-source level and
# breaks each Costco location out per-owner. Rows are long-format:
#   Location | Measure Names | Owner & Office (loc) | Measure Values
# We sum 'New/Port Lines' per Location across both owners' rows.
# Replaces the old AkibMJSummary view which returned 0 for WK Total
# on Mon/Tue runs (the new week had barely started).
_RETAIL_BY_CLUB_BASE_URL = (
    "https://us-east-1.online.tableau.com/t/sci/views/"
    "DropshipV_2/LOCATIONSALESSUMMARY/"
    "31c10a73-b383-4238-b3c6-2745d07c1ff5/CLUBBREAKDOWN-MJAKIB.csv"
)
RETAIL_BY_CLUB_FILENAME = "opt_retail_by_club.csv"


def _by_club_view_url(week_end_label: str) -> str:
    """Build the AkibMJSummary CSV URL with Min/Max Date params for the
    target week. Without these the saved view's date filter wins, and on
    a Mon/Tue run that means 'this week so far' = 0 sales (the new week
    has just started) — every Costco store fills 0 even though the 4-WK
    Avg shows real activity. (Megan 2026-05-26 zero-fill report.) Same
    pattern as _sara_view_data_url / _abp_view_url."""
    from datetime import datetime, timedelta
    end = datetime.strptime(week_end_label, "%m/%d/%y")
    start = end - timedelta(days=6)
    return (
        f"{_RETAIL_BY_CLUB_BASE_URL}?"
        f"Min%20Date={start.strftime('%Y-%m-%d')}"
        f"&Max%20Date={end.strftime('%Y-%m-%d')}"
    )


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
# SARA Plus office data. Constructed per-run via _sara_view_data_url()
# because the Min/Max Date URL params need the target week's dates.
# We download via View Data scrape (not Crosstab — the Crosstab dialog
# silently no-ops the (2) thumbnail click even in patchright) and use
# the BARE dashboard URL with date params (NOT a custom view path — saved
# custom views like 'Weekproduction' lock their saved date and ignore
# URL params; the bare URL respects them).
RETAIL_SARA_PLUS_OFFICE_FILENAME = "opt_retail_sara_plus_office.csv"
_RETAIL_SARA_BASE_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DropshipV_2/SARAPLUSSALESSUMMARY"
)


def _sara_view_data_url(week_end_label: str) -> str:
    """Build the SARA Plus URL with Min/Max Date filters for the target
    week. `week_end_label` is the sheet's week-ending Sunday in "M/D/YY"
    format (e.g. '5/17/26'). Week is Mon-Sun: Min Date = Sun minus 6 days."""
    from datetime import datetime, timedelta
    end = datetime.strptime(week_end_label, "%m/%d/%y")
    start = end - timedelta(days=6)
    return (
        f"{_RETAIL_SARA_BASE_URL}?:iid=1"
        f"&Min%20Date={start.strftime('%Y-%m-%d')}"
        f"&Max%20Date={end.strftime('%Y-%m-%d')}"
    )

RETAIL_ABP_SHEET = "ABP National Average (2)"
RETAIL_ABP_FILENAME = "opt_retail_abp.csv"
_RETAIL_ABP_BASE_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DropshipV_2/ABPCONVERSIONS"
)


def _abp_view_url(week_end_label: str) -> str:
    """Build the ABP URL with explicit Min/Max Date params for the target
    week. RETAILPULL custom view's saved dates were stale (showed last
    week's values) — switching to bare URL + URL params, same pattern
    as SARA. (Megan verified ABP values off 2026-05-23.)"""
    from datetime import datetime, timedelta
    end = datetime.strptime(week_end_label, "%m/%d/%y")
    start = end - timedelta(days=6)
    return (
        f"{_RETAIL_ABP_BASE_URL}?:iid=1"
        f"&Min%20Date={start.strftime('%Y-%m-%d')}"
        f"&Max%20Date={end.strftime('%Y-%m-%d')}"
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

# Money Lost from TMP = the 'Missed EC Bonus' measure per downline ICD, from
# the EC BONUS AWARENESS dashboard (Megan 2026-05-22).
#   The old DOWNLINEVIEW custom view returned only Rafael's own row — its
# 'Downline or Captain' filter wasn't saved as Downline, and the view IGNORES
# a URL filter param (probed 2026-06-08). Eve rebuilt it as AUTOMATION-MoneyLost
# with Downline saved. The full downline (48 ICDs) lives on the 'ORG EC Bonus'
# worksheet, which downloads cleanly via the Crosstab dialog BY NAME — the old
# View Data + activate_xy scrape only ever reached Rafael's 'ICD EC Bonus'
# table. parse_money_lost_crosstab reads the 'Missed EC Bonus' measure row.
RETAIL_MONEY_LOST_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DirectDepositICDVIEWVersion2_0/ECBONUSAWARENESS/"
    "dac7cf77-5d4c-4156-ab84-c2f2cce14478/AUTOMATION-MoneyLost?:iid=2"
)
RETAIL_MONEY_LOST_SHEET = "ORG EC Bonus"
RETAIL_MONEY_LOST_FILENAME = "opt_retail_money_lost.csv"
RETAIL_DD_FILENAME = "opt_retail_direct_deposit.csv"


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
    """Parse CLUBBREAKDOWN-MJAKIB and return {(kind, number): new_port_lines}
    summed across BOTH owners (MJ + Akib) per Costco store.

    CSV is long-format, one row per (Location, Measure, Owner):
      Location | Measure Names | Owner & Office (loc) | Measure Values
    We filter to 'New/Port Lines' rows for Costco locations and sum
    Measure Values across the two owners. ('Costco BC #655' shows up for
    both owners; without summing we'd undercount.)"""
    rows = tableau_http.parse_csv(path)
    if not rows:
        return {}
    header = rows[0]
    loc_i = tableau_http.col_idx(header, "Location")
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
            continue   # skip aggregate rows
        if (r[meas_i] or "").strip() != "New/Port Lines":
            continue
        key = _normalize_store_label(loc)
        if key is None:
            continue
        try:
            val = int(float((r[val_i] or "0").replace(",", "")))
        except (ValueError, AttributeError):
            continue
        out[key] = out.get(key, 0) + val   # SUM across MJ + Akib
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


def parse_sara_view_data(path: Path) -> Dict[str, Dict[str, int]]:
    """Parse SARA Plus office View Data scrape (long format from
    `scrape_view_data_patchright`) → {owner_norm: {metric: int, '_active_reps': int}}.

    Layout: Owner & Office | Rep | rep.Rep Number | Measure Names | Measure Values
    One row per (rep, measure). Aggregates per office by summing each
    target measure across reps. Active Headcount = COUNT OF DISTINCT
    REPS that appear in the office's data for the week, regardless of
    whether any specific measure is > 0 (Megan 2026-05-23 spec — a rep
    that shows up on the dashboard counts as headcount even if their
    week's measures are all 0)."""
    rows = _read_tab_csv(path)
    if not rows or len(rows) < 2:
        return {}
    header = rows[0]
    owner_i = _col_starts_with(header, "Owner & Office")
    rep_i = _col_starts_with(header, "Rep")
    meas_i = tableau_http.col_idx(header, "Measure Names")
    val_i = tableau_http.col_idx(header, "Measure Values")
    if None in (owner_i, rep_i, meas_i, val_i):
        return {}
    # Pull all retail-relevant measures so the SARA office data can
    # source Internet + Total New Lines too (instead of the by-day file
    # which carries NDS's date filter and is wrong for retail weeks).
    target_measures = {"Next Up", "New/Port Lines", "Premium/Elite",
                       "Extra", "Internet", "DTV"}
    # Personal Production = the rep whose name matches the ICD/owner name
    # (Megan 2026-05-23). Track per-rep measures so we can pull that rep's
    # row out per office. Keyed by lowercased rep name.
    personal_measures = {"Internet", "New/Port Lines", "DTV"}
    sums: Dict[str, Dict[str, int]] = {}
    per_rep: Dict[str, Dict[str, Dict[str, int]]] = {}
    reps_seen: Dict[str, set] = {}
    for r in rows[1:]:
        if max(owner_i, rep_i, meas_i, val_i) >= len(r):
            continue
        owner = _norm_owner(r[owner_i])
        rep = (r[rep_i] or "").strip()
        measure = (r[meas_i] or "").strip()
        raw_val = (r[val_i] or "").strip().replace(",", "")
        if not owner or not rep:
            continue
        try:
            num = int(float(raw_val))
        except ValueError:
            continue
        bucket = sums.setdefault(owner, {})
        if measure in target_measures:
            bucket[measure] = bucket.get(measure, 0) + num
        if measure in personal_measures:
            per_rep.setdefault(owner, {}).setdefault(
                rep.lower(), {})[measure] = num
        reps_seen.setdefault(owner, set()).add(rep)
    out: Dict[str, Dict[str, int]] = {}
    for owner, metrics in sums.items():
        metrics["_active_reps"] = len(reps_seen.get(owner, set()))
        metrics["_per_rep"] = per_rep.get(owner, {})
        out[owner] = metrics
    return out


def _personal_production_text(per_rep: Dict[str, Dict[str, int]],
                              icd_norm: str) -> Optional[str]:
    """For the rep with the same name as the ICD, format their personal
    production as "<INT> INT, <NL> NL, <DTV> DTV" — measures with a 0
    count are omitted (matches the sheet's historical "2 NI, 11 NL"
    style of dropping zero columns). Returns None if no matching rep."""
    rep_data = per_rep.get(icd_norm)
    if not rep_data:
        return None
    int_n = rep_data.get("Internet", 0)
    nl_n = rep_data.get("New/Port Lines", 0)
    dtv_n = rep_data.get("DTV", 0)
    parts = []
    if int_n:
        parts.append(f"{int_n} INT")
    if nl_n:
        parts.append(f"{nl_n} NL")
    if dtv_n:
        parts.append(f"{dtv_n} DTV")
    return ", ".join(parts) if parts else "0"


def parse_money_lost_crosstab(path: Path) -> Dict[str, str]:
    """Parse the AUTOMATION-MoneyLost 'ORG EC Bonus' Crosstab → {icd_norm:
    dollar_str}, for all downline ICDs.

    Each ICD spans FOUR measure rows; layout:
      ICD.Corporation Name | ICD.Full Name | <measure name> | Grand Total to ICD | <campaign cols...>
    The measure-name column has a BLANK header (it sits just left of 'Grand
    Total to ICD'). Money Lost = the 'Missed EC Bonus' row's 'Grand Total to
    ICD' value, written verbatim (e.g. '$0.00', '($560.00)'). Verified
    2026-06-08: 48 downline ICDs (the old DOWNLINEVIEW View Data scrape only
    ever reached Rafael's own row)."""
    rows = _read_tab_csv(path)
    if not rows or len(rows) < 2:
        return {}
    header = rows[0]
    name_i = tableau_http.col_idx(header, "ICD.Full Name")
    total_i = tableau_http.col_idx(header, "Grand Total to ICD")
    if name_i is None or total_i is None or total_i == 0:
        return {}
    meas_i = total_i - 1   # blank-header measure column, just left of the total
    out: Dict[str, str] = {}
    for r in rows[1:]:
        if max(name_i, meas_i, total_i) >= len(r):
            continue
        if (r[meas_i] or "").strip().lower() != "missed ec bonus":
            continue
        owner = _norm_owner(r[name_i])
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


# Re-enabled 2026-05-27 after Megan set up the CLUBBREAKDOWN-MJAKIB
# custom view on DropshipV_2/LOCATIONSALESSUMMARY. New view pre-filters
# to MJ + Akib, exposes per-Costco-store New/Port Lines (which is the
# metric on the AKIB & MJ Costco section), and respects Min Date /
# Max Date URL params for week targeting.
_COSTCO_FILL_ENABLED = True


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
    if not _COSTCO_FILL_ENABLED:
        # See the comment at _COSTCO_FILL_ENABLED for the re-enable conditions.
        return [f"[skip-retail-costco] {ws.title}: Costco per-store fill "
                f"DISABLED — Tableau dashboard doesn't expose per-store WK "
                f"totals for the requested week. Manual values left intact."]
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
                                sara_office: Dict[str, Dict[str, int]],
                                tab_icds: List[str],
                                week_col_label: str,
                                dry_run: bool = False,
                                logfn=print) -> List[str]:
    """Fill per-ICD office-total metrics (Internet, Total New Lines) into
    each ICD's section of the tab. Sourced from SARA Plus office View
    Data — same source that fills the % metrics — so the date range
    matches (was previously sourced from the NDS shared by-day file
    which carried NDS's date filter, producing wrong totals for retail
    weeks; Megan 2026-05-23)."""
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
        data = sara_office.get(icd_norm, {})
        if not data:
            log.append(f"  [miss-icd] {icd_norm!r}: no Sara Plus office data")
            continue

        # Metric → (sheet label, source measure name in SARA office data)
        for sheet_label, src_measure in [
            ("Internet",        "Internet"),
            ("Total New Lines", "New/Port Lines"),
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
    "Personal Production":        ["Personal Production"],
    "Direct Deposit":             ["Direct Deposit"],
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
                        direct_deposit: Dict[str, str],
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
        direct_deposit_val = _lookup(direct_deposit)

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

        # 7) Personal Production = the rep with the same name as the ICD
        # (e.g. for ICD Boaktear Chowdhury, the rep named 'BOAKTEAR
        # CHOWDHURY'). Format: "<INT> INT, <NL> NL, <DTV> DTV" with zeros
        # omitted (Megan 2026-05-23).
        personal = _personal_production_text(s_row.get("_per_rep", {}), icd_norm)
        if personal:
            row_0 = _find_first_label_match(
                grid, _OFFICE_METRIC_ROW_LABELS["Personal Production"],
                start, end)
            if row_0 is not None:
                a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
                updates.append({"range": a1, "values": [[personal]]})
                log.append(f"  {a1} {icd_norm!r} Personal Production <- {personal}")
            else:
                log.append(f"  [miss-row] {icd_norm!r} -> no 'Personal Production' row")
        else:
            log.append(f"  [miss-data] {icd_norm!r} -> no same-name rep in SARA")

        # 8) Money Lost from TMP = Missed EC Bonus x Grand Total to ICD,
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

        # 9) Direct Deposit — Tableau org-wide DD view, per ICD owner
        # (Megan 2026-05-25: DD = Tableau for every campaign). Dollar string.
        if direct_deposit_val:
            row_0 = _find_first_label_match(
                grid, _OFFICE_METRIC_ROW_LABELS["Direct Deposit"], start, end)
            if row_0 is not None:
                a1 = gspread.utils.rowcol_to_a1(row_0 + 1, week_col + 1)
                updates.append({"range": a1, "values": [[direct_deposit_val]]})
                log.append(f"  {a1} {icd_norm!r} Direct Deposit <- {direct_deposit_val}")
            else:
                log.append(f"  [miss-row] {icd_norm!r} -> no 'Direct Deposit' row")
        else:
            log.append(f"  [miss-data] {icd_norm!r} -> no Direct Deposit data")

    if dry_run:
        return [f"[DRY-RUN retail-opt] {ws.title}: would write {len(updates)} cells"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        _red = _sheet_flags.weird_ranges(updates)   # fill-but-flag weird %s
        if _red:
            _sheet_flags.apply_red_font(ws, _red, retry=rfill._retry)
        return [f"[OK retail-opt] {ws.title}: wrote {len(updates)} cells"
                + (f" ({len(_red)} flagged)" if _red else "")] + log
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

    # ONE unattended patchright session powers BOTH the HTTP-direct CSV pulls
    # (Costco by-club, churn, activation — fast ~1s each) AND the View Data /
    # Crosstab UI scrapes. requests_session_from_page lends the authenticated
    # Tableau cookies to a plain requests.Session, so the .csv endpoints work
    # off the same login — no CDP / Report Chrome dependency anywhere in this
    # run (Megan 2026-05-24: full patchright cutover so Retail runs unattended).
    week_col_label = _current_target_week_col_label()
    logfn(f"OPT Retail: target week column = {week_col_label!r}")

    by_club_path: Optional[Path] = None
    churn_path: Optional[Path] = None
    activation_path: Optional[Path] = None
    sara_office_path: Optional[Path] = None
    abp_path: Optional[Path] = None
    money_lost_path: Optional[Path] = None
    dd_path: Optional[Path] = None

    # Linear-scroll tuning for View Data scrapes — default scraper's
    # alternating incremental+jump strategy skips middle rows on SARA's
    # 3-owner grid.
    _VIEWDATA_SCRAPE_KWARGS = dict(jump_every=None, scroll_step=0.35,
                                    scroll_wait_ms=1800, stale_max=30)

    page = None  # bound by the `with` below; referenced in _try_with_retry

    def _fallback_existing(filename: str) -> Optional[Path]:
        target = OUTPUT_DIR / filename
        if target.exists() and target.stat().st_size > 500:
            logfn(f"OPT Retail: using existing {filename} "
                  f"({target.stat().st_size:,} bytes) as fallback")
            return target
        return None

    def _try_with_retry(label: str, filename: str, max_attempts: int, op):
        """Run `op()` (download/scrape) up to max_attempts times, with an
        about:blank reset between attempts. Returns the result path, or
        the existing-file fallback, or None."""
        target = OUTPUT_DIR / filename
        last_err: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            tag = (f"attempt {attempt}/{max_attempts} " if max_attempts > 1 else "")
            logfn(f"OPT Retail: {label} {tag}→ {filename}...")
            try:
                return op()
            except Exception as e:
                last_err = e
                if attempt < max_attempts:
                    # Progressive backoff (6s, 12s, …) not a flat 3s: the
                    # scrape/crosstab timeouts are LOAD-correlated — on the 4am
                    # batch the mini is running several browser reports at once,
                    # so the Tableau viz can't render inside the 40s toolbar
                    # wait. A longer settle between tries lets the render catch
                    # up before we re-hit it. (Megan 2026-07-06: SARA timed out
                    # on both tries under 6am load and dropped the step.)
                    backoff = min(6_000 * attempt, 18_000)
                    logfn(f"OPT Retail:   {type(e).__name__}, "
                          f"retrying in {backoff // 1000}s...")
                    try:
                        page.goto("about:blank",
                                  wait_until="domcontentloaded",
                                  timeout=10_000)
                        page.wait_for_timeout(backoff)
                    except Exception:
                        pass
        msg = f"{filename}: {type(last_err).__name__}: {str(last_err)[:120]}"
        logfn(f"OPT Retail: error {msg}")
        errors.append(msg)
        return _fallback_existing(filename)

    try:
        with tableau_session(verbose=False) as page:
            # ---- Step 1: HTTP-direct CSV pulls off the patchright session's
            # Tableau cookies. These views are single-worksheet OR their .csv
            # endpoint serves the right worksheet — fast (~1s each).
            session = requests_session_from_page(page)
            by_club_path = _http_download(session,
                                          _by_club_view_url(week_col_label),
                                          RETAIL_BY_CLUB_FILENAME, logfn, errors)
            # The Costco fill is the blocking output — only do the rest of the
            # run (churn/activation + the slow UI scrapes) if its source came
            # through. (A partial run mid-rollout is more confusing than none.)
            if by_club_path is not None:
                churn_path = _http_download(session, RETAIL_CHURN_URL,
                                            RETAIL_CHURN_FILENAME, logfn, errors)
                activation_path = _http_download(session, RETAIL_ACTIVATION_URL,
                                                 RETAIL_ACTIVATION_FILENAME,
                                                 logfn, errors)

                # ---- Step 2: UI scrapes (same Chrome launch). Three paths:
                #   - SARA: View Data scrape with dynamic Min/Max Date URL
                #     params (the bare dashboard URL respects them; custom
                #     views lock their own dates and ignore URL params).
                #   - ABP: Crosstab (its dialog isn't broken).
                #   - Money Lost: View Data scrape with activate_xy clicking
                #     the lower 'Rafael Hidalgo ORGANIZATION' table to enable
                #     Download → Data.
                sara_target = OUTPUT_DIR / RETAIL_SARA_PLUS_OFFICE_FILENAME
                sara_office_path = _try_with_retry(
                    "patchright View Data", RETAIL_SARA_PLUS_OFFICE_FILENAME, 3,
                    lambda: scrape_view_data_patchright(
                        _sara_view_data_url(week_col_label), sara_target,
                        verbose=False, page=page,
                        scrape_kwargs=_VIEWDATA_SCRAPE_KWARGS))

                abp_target = OUTPUT_DIR / RETAIL_ABP_FILENAME
                abp_path = _try_with_retry(
                    "patchright Crosstab", RETAIL_ABP_FILENAME, 3,
                    lambda: download_crosstab_patchright(
                        _abp_view_url(week_col_label),
                        RETAIL_ABP_SHEET, abp_target,
                        verbose=False, page=page))

                money_target = OUTPUT_DIR / RETAIL_MONEY_LOST_FILENAME
                money_lost_path = _try_with_retry(
                    "patchright Crosstab", RETAIL_MONEY_LOST_FILENAME, 3,
                    lambda: download_crosstab_patchright(
                        RETAIL_MONEY_LOST_URL, RETAIL_MONEY_LOST_SHEET,
                        money_target, verbose=False, page=page))

                # Direct Deposit — org-wide DD view (same source every campaign
                # uses; Megan 2026-05-25). Crosstab path like NDS.
                dd_target = OUTPUT_DIR / RETAIL_DD_FILENAME
                dd_path = _try_with_retry(
                    "patchright Crosstab", RETAIL_DD_FILENAME, 3,
                    lambda: download_crosstab_patchright(
                        ORG_DD_URL, ORG_DD_SHEET, dd_target,
                        verbose=False, page=page))
    except Exception as e:
        logfn(f"OPT Retail: patchright session failed: "
              f"{type(e).__name__}: {str(e)[:160]}")
        errors.append(f"patchright session: {type(e).__name__}: {str(e)[:120]}")
        sara_office_path = sara_office_path or _fallback_existing(
            RETAIL_SARA_PLUS_OFFICE_FILENAME)
        abp_path = abp_path or _fallback_existing(RETAIL_ABP_FILENAME)
        money_lost_path = money_lost_path or _fallback_existing(
            RETAIL_MONEY_LOST_FILENAME)
        dd_path = dd_path or _fallback_existing(RETAIL_DD_FILENAME)

    # Costco by-club is the blocking output — abort if its source failed
    # (or the whole patchright session failed to open).
    if by_club_path is None:
        return {"filled": [], "skipped": [], "errors": errors}

    # ---- Step 2: parse every CSV ----
    by_club = parse_retail_by_club(by_club_path)
    logfn(f"OPT Retail: parsed {len(by_club)} Costco store(s): "
          f"{sorted(by_club.items())}")

    churn = parse_churn_rates(churn_path) if churn_path else {}
    logfn(f"OPT Retail: parsed churn rates for {len(churn)} office(s): "
          f"{sorted(churn.keys())}")

    sara_office = parse_sara_view_data(sara_office_path) if sara_office_path else {}
    logfn(f"OPT Retail: parsed Sara Plus office totals for {len(sara_office)} office(s): "
          f"{sorted(sara_office.keys())}")

    abp = parse_abp_conversions(abp_path) if abp_path else {}
    logfn(f"OPT Retail: parsed ABP % for {len(abp)} office(s): "
          f"{sorted(abp.keys())}")

    activation = (tableau_http.parse_activation(activation_path, bucket="60+ Days")
                  if activation_path else {})
    logfn(f"OPT Retail: parsed Activation % (60+ Days) for "
          f"{len(activation)} office(s): {sorted(activation.keys())}")

    money_lost = parse_money_lost_crosstab(money_lost_path) if money_lost_path else {}
    logfn(f"OPT Retail: parsed Money Lost from TMP for {len(money_lost)} office(s): "
          f"{sorted(money_lost.keys())}")

    direct_deposit = ({k: f"${v:,.2f}" for k, v in
                       parse_direct_deposit(dd_path).items()} if dd_path else {})
    logfn(f"OPT Retail: parsed Direct Deposit for {len(direct_deposit)} owner(s)")

    # ---- Step 3: walk the Retail tabs ----
    client = rfill._client()
    sh = rfill.open_by_key(ALPHALETE_ORG_SHEET_ID, client)

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
                    ws, sara_office, RETAIL_TAB_ICDS[title],
                    week_col_label, dry_run, logfn):
                logfn(f"OPT Retail: {ln}")
                if ln.startswith(("[OK", "[DRY-RUN")):
                    ok_any = True
            for ln in fill_office_metrics(
                    ws, churn, sara_office, abp, activation, money_lost,
                    direct_deposit, RETAIL_TAB_ICDS[title], week_col_label,
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

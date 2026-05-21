"""NDS OPT phase for the Alphalete Org 1on1s - Focus Reports sheet.

Downloads the seven NDS Tableau crosstabs, parses them, and writes per-rep
OPT metrics to each NDS tab on the Alphalete Org sheet. Mirrors the shape
of automations/recruiting_report/opt_phase.py (Raf's pipeline) but points
at a different Tableau workbook because the NDS reps aren't in Raf's
'AUTOMATION PULL ICD' view.

Source map (resources/opt-section/alphalete-org-campaign-sources.md):
  - NDSDailyTracker / TT-LineN/P Detail → Active Selling Heads + Scorecard
    Ranking (per-rep). Reads "Rep Count" + "Ranking" columns.
  - NDSDailyTracker / Rep Summary → National AVG for sales (org total
    of New/Port per Rep; SAME value on every NDS tab).
  - SARAPLUSSALESSUMMARY iid=1 / 'Sara Plus Sales Summary' (2) → per-rep
    Personal Production + New Lines. The "(2)" worksheet was unavailable
    overnight (only Z_Last Refresh thumb visible); Megan to verify view
    state. Org totals (iid=1 main sheet) DO download — ATV / Internet /
    New/Port Lines / Next Up.
  - NDSWeeklyMetricsRep / THISWEEK → 0-30 Day Cancel Rate 4wk avg
    ('Cancel Fraud Review %', office total).
  - CHURNRATES / THISWEEK → 0-30 / 60 / 90 Day Churn (per-rep, look for
    rows where col-2 = 'Green' for the headline rate).
  - ACTIVATIONRATES → Activation % by Week (per-rep, '60+ Days' column).
  - LeadPenetrationOverview / THISWEEK → Total Leads (sum of 'Lead Count'
    rows assigned to each ICD).
  - DirectDeposit / PROGRAMSUMMARY / DOWNLINEVIEW → Direct Deposit
    ('Grand Total to ICD', per-ICD; shared with every other Alphalete
    Org program).

Computed metrics (no separate download):
  - AVG Apps Per Active Headcount = New Lines / Active Selling Heads
  - Next Up % = (office Next Up count) / (office New/Port Lines count)
  - Extra/Premium % = (office Premium/Elite + Extra) / (office New/Port Lines)

Rep Breakdown chart at the bottom of each NDS tab — separate module
(production_breakdown style), wireless-only, comes from
ProductSalesSummaryRep / REPEXPANDED / 'Sales By ICD (Weekly View)'.

Week scoping: Megan confirmed (2026-05-20) that Tableau's THISWEEK custom
view on Monday morning resolves to the just-completed week's totals.
Today's data (mid-week) reflects 5/18-5/24 partial; Monday-morning runs
will reflect the full 5/18-5/24 week.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gspread

from automations.recruiting_report import fill as rfill
from automations.recruiting_report.opt_phase import download_crosstab

WORKSPACE = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = WORKSPACE / "output"

ALPHALETE_ORG_SHEET_ID = "1C6BLttOSZhs_dREySac19XkxnMl-Ab_sYacNSl2l6AQ"

# Tableau views — one entry per (URL, worksheet, output filename).
# The runner iterates these once per week; failed downloads are logged
# but don't block the others (preserves Megan's incremental-fill rule).
NDS_VIEWS: List[Tuple[str, str, str]] = [
    # (url, crosstab_worksheet_name, output_filename)
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1",
        "TT-LineN/P Detail",
        "opt_nds_tt_detail.csv",
    ),
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1",
        "Rep Summary",
        "opt_nds_rep_summary.csv",
    ),
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/SARAPLUSSALESSUMMARY?:iid=1",
        "Sara Plus Sales Summary",
        "opt_nds_sara_plus.csv",
    ),
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/SARAPLUSSALESSUMMARY?:iid=1",
        "Sara Plus Sales Summary (2)",
        "opt_nds_sara_plus_2.csv",
    ),
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/NDSWeeklyMetricsRep/2a63e621-b4cb-423f-9a46-75e56abca9a3/THISWEEK?:iid=1",
        "Weekly Metrics (Rep)",
        "opt_nds_weekly_metrics.csv",
    ),
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/c289786d-e0d4-4de7-825a-264c21e133c1/THISWEEK?:iid=1",
        "Churn Rates (ICD)",
        "opt_nds_churn.csv",
    ),
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/ACTIVATIONRATES?:iid=1",
        "Activation Rates (ICD)",
        "opt_nds_activation.csv",
    ),
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/LeadPenetrationOverview/a15a85ac-e0c8-423d-ba85-6be048203b0b/THISWEEK?:iid=1",
        # Megan: "Lead Count (sum across all rows assigned to ICD)". The
        # exact worksheet name needs to be verified — Lead Penetration By Zip
        # is a guess pending Megan confirming the right thumbnail.
        "Lead Penetration By Zip",
        "opt_nds_lead_penetration.csv",
    ),
    (
        "https://us-east-1.online.tableau.com/#/site/sci/views/DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY/15c897de-6162-469b-9ef7-1735d235f2a8/DOWNLINEVIEW?:iid=1",
        # 'Consultant ORG Title' gave 64 bytes (just the logged-in user's
        # name) — that's not it. 'Sheet 7 (3)' or 'Self Office Display'
        # is more likely. Megan to confirm overnight blocker.
        "Sheet 7 (3)",
        "opt_nds_direct_deposit.csv",
    ),
]

# The Rep Breakdown chart at the bottom of each tab — its OWN download
# (separate from the metric crosstabs above).
NDS_REP_BREAKDOWN_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
    "b86d7862-bfc7-4966-a0a4-7803432a6444/REPEXPANDED?:iid=2"
)
NDS_REP_BREAKDOWN_SHEET = "Sales By ICD (Weekly View)"
NDS_REP_BREAKDOWN_PATH = OUTPUT_DIR / "opt_nds_product_sales_rep.csv"


# Map our sheet row labels (col B) → metric keys used in fill_nds_tab.
# Format follows Raf's opt_phase convention: lookup by label string, never
# by hardcoded row index ([[feedback_no_hardcoded_columns]]).
NDS_METRIC_LABELS = {
    "Active Selling Heads":              "active_selling_heads",
    "New Lines":                          "new_lines",
    "AVG Apps Per Active Headcount":     "avg_apps_per_hc",
    "National AVG for sales":            "national_avg_sales",
    "Scorecard Ranking":                 "scorecard_ranking",
    "Personal Production":               "personal_production",
    "0-30 Day Cancel Rate  4wk avg":     "cancel_rate_30",
    "Activation % by Week":              "activation_pct",
    "0-30 Day Churn":                    "churn_30",
    "60 Day Churn":                      "churn_60",
    "90 Day Churn":                      "churn_90",
    "Total Leads":                       "total_leads",
    "Next Up %":                          "next_up_pct",
    "Extra/Premium %":                   "extra_premium_pct",
    "Direct Deposit":                    "direct_deposit",
}


# ------------------------------------------------------------ parsers


def _read_tab_csv(path: Path) -> List[List[str]]:
    """Read a Tableau crosstab CSV (UTF-16, tab-delimited). Returns []
    if the file is missing or empty."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc) as f:
                rows = list(csv.reader(f, delimiter="\t"))
            if rows and any(len(r) > 1 for r in rows):
                return rows
        except UnicodeDecodeError:
            continue
    return []


def _norm_owner(s: str) -> str:
    """Normalize a Tableau owner name to its canonical form for matching.
    Tableau formats names as 'ALEX GUZMAN BENITEZ\n[Tampa, FL]' — we want
    just 'alex guzman benitez'."""
    s = (s or "").strip()
    # Strip trailing "[city, state]" if present (may be after a \n)
    s = re.split(r"[\[\n]", s, maxsplit=1)[0].strip()
    return " ".join(s.lower().split())


def parse_tt_detail(path: Path) -> Dict[str, Dict[str, str]]:
    """Parse TT-LineN/P Detail: {normalized owner: {Rep Count: ..., Ranking: ...}}."""
    rows = _read_tab_csv(path)
    if not rows:
        return {}
    header = rows[0]
    # Find column indices by header label (no hardcoded positions).
    def col(label: str) -> Optional[int]:
        for i, h in enumerate(header):
            if (h or "").strip().lower() == label.lower():
                return i
        return None
    rank_i = col("Ranking")
    rc_i = col("Rep Count")
    out: Dict[str, Dict[str, str]] = {}
    for r in rows[2:]:  # skip header + Total row
        owner = _norm_owner(r[0] if r else "")
        if not owner:
            continue
        rec = {}
        if rank_i is not None and rank_i < len(r):
            rec["ranking"] = r[rank_i]
        if rc_i is not None and rc_i < len(r):
            rec["rep_count"] = r[rc_i]
        if rec:
            out[owner] = rec
    return out


def parse_rep_summary_total(path: Path) -> Dict[str, str]:
    """Parse the Total row from Rep Summary — gives the org-wide averages
    that go in 'National AVG for sales'. Returns {column: value}."""
    rows = _read_tab_csv(path)
    if not rows:
        return {}
    header = rows[0]
    # Total row is the LAST row with first col == 'Total'
    total_row = next((r for r in reversed(rows)
                      if r and (r[0] or "").strip().lower() == "total"), None)
    if not total_row:
        return {}
    out: Dict[str, str] = {}
    for i, h in enumerate(header):
        if i < len(total_row) and h:
            out[h.strip()] = total_row[i]
    return out


def parse_sara_plus_total(path: Path) -> Dict[str, str]:
    """Parse the (single-row) totals from Sara Plus Sales Summary iid=1.
    Returns {column: value} — includes Next Up, New/Port Lines, etc."""
    rows = _read_tab_csv(path)
    if not rows or len(rows) < 2:
        return {}
    header = rows[0]
    data = rows[1]
    return {(h or "").strip(): (data[i] if i < len(data) else "")
            for i, h in enumerate(header)}


def parse_churn_icd(path: Path) -> Dict[str, Dict[str, str]]:
    """Parse Churn Rates (ICD): {normalized owner: {churn_30/60/90: pct}}.
    Headline rates come from the 'Green' status rows (per-rep, NOT
    Office/Organization Average). Each rep has FOUR rows of metric type —
    we want the 'Churn Rate' one only."""
    rows = _read_tab_csv(path)
    if not rows:
        return {}
    # Header: cols 4-7 are 0-30 / 30 / 60 / 90 Day Churn
    header = rows[0]
    c_30 = c_60 = c_90 = None
    for i, h in enumerate(header):
        h_clean = (h or "").strip().lower()
        if h_clean == "0-30 day churn":
            c_30 = i
        elif h_clean == "60 day churn":
            c_60 = i
        elif h_clean == "90 day churn":
            c_90 = i
    out: Dict[str, Dict[str, str]] = {}
    for r in rows[1:]:
        if len(r) < 3:
            continue
        owner = _norm_owner(r[0])
        status = (r[1] or "").strip()
        metric = (r[2] or "").strip().lower()
        if not owner or "office/organization" in owner:
            continue
        if metric != "churn rate":
            continue
        # Take Green status row (the headline rate); fall back to first
        # row seen for this owner if no Green.
        rec = out.setdefault(owner, {})
        is_green = status.lower() == "green"
        for key, col in (("churn_30", c_30), ("churn_60", c_60), ("churn_90", c_90)):
            if col is None or col >= len(r):
                continue
            val = (r[col] or "").strip()
            if not val:
                continue
            if key not in rec or is_green:
                rec[key] = val
    return out


# ------------------------------------------------------------ fill helpers


def _find_row_by_label(grid: List[List[str]], label: str,
                       label_col: int = 1) -> Optional[int]:
    """Find a row whose col-B (default) matches `label` (case-insensitive,
    whitespace-normalized). Returns 0-indexed row or None.

    Matching is intentionally loose — exact, OR all words from the label
    appear in the cell (in any order). Handles legacy tab variants like
    'Churn 0 -30 Day' vs 'Churn 0-30 Day' vs '0-30 Day Churn' without
    needing a per-tab patch."""
    target_words = set(label.lower().split())
    target_compact = label.lower().replace(" ", "").replace("-", "")
    for ri, r in enumerate(grid):
        cell = r[label_col] if len(r) > label_col else ""
        cell_norm = " ".join((cell or "").lower().split())
        # Exact match
        if cell_norm == " ".join(label.lower().split()):
            return ri
        # All target words present (handles word-order swap)
        cell_words = set(cell_norm.replace("-", " ").split())
        if target_words and target_words.issubset(cell_words):
            return ri
        # Compact-string fallback (whitespace + dashes stripped)
        cell_compact = cell_norm.replace(" ", "").replace("-", "")
        if target_compact and target_compact == cell_compact:
            return ri
    return None


def _find_week_col(grid: List[List[str]], week_label: str) -> Optional[int]:
    """Find the column whose header (row 0) equals `week_label` (e.g.
    '5/24/26'). Returns 0-indexed col or None."""
    if not grid:
        return None
    for ci, h in enumerate(grid[0]):
        if (h or "").strip() == week_label:
            return ci
    return None


def _current_target_week_col_label(today: Optional[dt.date] = None) -> str:
    """Sheet column label = Sunday at the END of the week containing
    yesterday. Works for both Monday morning runs (Eve's normal cadence)
    and mid-week test runs.

    Examples:
      - Mon 5/25 → yesterday 5/24 (Sun) → target Sunday = 5/24 ✓ ('5/24/26')
      - Thu 5/21 → yesterday 5/20 (Wed) → target Sunday = 5/24 ('5/24/26')
      - Sun 5/24 → yesterday 5/23 (Sat) → target Sunday = 5/24 ('5/24/26')
      - Tue 5/26 → yesterday 5/25 (Mon) → target Sunday = 5/31 ('5/31/26')

    Why "yesterday" not "today": on Monday morning the Tableau data still
    reflects last week (data lag). Using yesterday as the anchor makes
    Monday and the rest of the week target the same column when the
    Tableau data is for the same week."""
    today = today or dt.date.today()
    anchor = today - dt.timedelta(days=1)
    days_forward = (6 - anchor.weekday()) % 7   # 6 = Sunday
    target = anchor + dt.timedelta(days=days_forward)
    return f"{target.month}/{target.day}/{target.year % 100}"


def fill_nds_tab(ws: gspread.Worksheet, owner_norm: str,
                 tt: Dict[str, Dict[str, str]],
                 rep_summary_total: Dict[str, str],
                 sara_totals: Dict[str, str],
                 churn: Dict[str, Dict[str, str]],
                 week_col_label: str,
                 dry_run: bool = False,
                 logfn=print) -> List[str]:
    """Write all available metrics for this rep into the target week column.
    Skips metrics whose source data isn't available."""
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip] {ws.title}: empty tab"]

    week_col = _find_week_col(grid, week_col_label)
    if week_col is None:
        return [f"[skip] {ws.title}: no column for week {week_col_label}"]

    # Gather values
    rep = tt.get(owner_norm, {})
    crow = churn.get(owner_norm, {})

    values: Dict[str, str] = {}
    if "rep_count" in rep:
        values["Active Selling Heads"] = rep["rep_count"]
    if "ranking" in rep:
        values["Scorecard Ranking"] = rep["ranking"]
    if rep_summary_total.get("New/Port per Rep"):
        values["National AVG for sales"] = rep_summary_total["New/Port per Rep"]
    if "churn_30" in crow:
        values["0-30 Day Churn"] = crow["churn_30"]
    if "churn_60" in crow:
        values["60 Day Churn"] = crow["churn_60"]
    if "churn_90" in crow:
        values["90 Day Churn"] = crow["churn_90"]
    # Next Up % computed from sara_totals — office-level shared
    next_up = sara_totals.get("Next Up")
    new_port = sara_totals.get("New/Port Lines")
    try:
        if next_up and new_port and float(new_port) > 0:
            values["Next Up %"] = f"{float(next_up) / float(new_port):.2%}"
    except (ValueError, ZeroDivisionError):
        pass

    if not values:
        return [f"[skip] {ws.title}: no metrics available for {owner_norm}"]

    # Build batch update — only writes cells where we found a row
    updates = []
    for label, val in values.items():
        row = _find_row_by_label(grid, label)
        if row is None:
            log.append(f"  [miss] {ws.title}: no row for {label!r}")
            continue
        a1 = gspread.utils.rowcol_to_a1(row + 1, week_col + 1)
        updates.append({"range": a1, "values": [[val]]})
        log.append(f"  {a1} ({label}) ← {val!r}")

    if dry_run:
        return [f"[DRY-RUN] {ws.title}: would write {len(updates)} cells"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        return [f"[OK] {ws.title}: wrote {len(updates)} cells"] + log
    return [f"[skip] {ws.title}: nothing to write"]


# ------------------------------------------------------------ entry point


def run_nds_opt(dry_run: bool = False, only_rep: Optional[str] = None,
                skip_download: bool = False, logfn=print) -> dict:
    """Download all NDS Tableau views, parse, and fill each NDS tab on
    Alphalete Org. Returns {filled: [...], skipped: [...], errors: [...]}."""
    # Step 1: download (or skip if --skip-download)
    download_errors: List[str] = []
    if not skip_download:
        for url, sheet, fname in NDS_VIEWS:
            out = OUTPUT_DIR / fname
            try:
                logfn(f"OPT NDS: downloading {fname}…")
                download_crosstab(url, sheet, out, verbose=False)
            except Exception as e:
                msg = f"{fname}: {type(e).__name__}: {str(e)[:120]}"
                logfn(f"OPT NDS: ✗ {msg}")
                download_errors.append(msg)
    else:
        logfn("OPT NDS: --skip-download — reusing cached crosstabs")

    # Step 2: parse what we have
    tt = parse_tt_detail(OUTPUT_DIR / "opt_nds_tt_detail.csv")
    rep_summary = parse_rep_summary_total(OUTPUT_DIR / "opt_nds_rep_summary.csv")
    sara_totals = parse_sara_plus_total(OUTPUT_DIR / "opt_nds_sara_plus.csv")
    churn = parse_churn_icd(OUTPUT_DIR / "opt_nds_churn.csv")
    logfn(f"OPT NDS: parsed {len(tt)} reps from TT-Detail, "
          f"{len(churn)} reps from Churn, "
          f"national avg={'✓' if rep_summary.get('New/Port per Rep') else '✗'}, "
          f"sara totals={'✓' if sara_totals.get('New/Port Lines') else '✗'}")

    # Step 3: open sheet + walk NDS-suffixed tabs
    client = rfill._client()
    sh = client.open_by_key(ALPHALETE_ORG_SHEET_ID)
    # Skip hidden tabs (same convention as recruiting + financial)
    resp = sh.client.request(
        "get",
        f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
        params={"fields": "sheets(properties(title,hidden))"},
    )
    hidden = {s["properties"]["title"] for s in resp.json().get("sheets", [])
              if s["properties"].get("hidden")}

    week_col_label = _current_target_week_col_label()
    logfn(f"OPT NDS: target week column = {week_col_label!r}")

    filled: List[str] = []
    skipped: List[str] = []
    for ws in rfill._retry(sh.worksheets):
        title = ws.title
        if not title.endswith(" - NDS") or title in hidden or title.startswith("x"):
            continue
        rep_name = title[: -len(" - NDS")].strip()
        owner_norm = _norm_owner(rep_name)
        if only_rep and only_rep.lower() not in rep_name.lower():
            continue
        # Owner aliases: try the tab name + a couple fallbacks. Tableau
        # spellings often differ slightly from sheet tab names (e.g. tab
        # 'Maxamed Aden' vs Tableau 'MAXAMAD ADEN'). We try:
        #   1. Direct match against the normalized tab name
        #   2. Same last-name + same-first-letter-of-first-name match
        #      (catches 'Maxamed' ↔ 'Maxamad', 'Selena' ↔ 'Selena Powers')
        #   3. Same last-name only (last-resort)
        candidates = [owner_norm]
        tw = owner_norm.split()
        for k in tt:
            kw = k.split()
            if not kw or not tw:
                continue
            if kw[-1] == tw[-1] and kw[0][:1] == tw[0][:1]:
                if k not in candidates:
                    candidates.append(k)
        # Final fallback: same last name only
        for k in tt:
            kw = k.split()
            if kw and tw and kw[-1] == tw[-1] and k not in candidates:
                candidates.append(k)
        match = next((c for c in candidates if c in tt), None) or owner_norm

        lines = fill_nds_tab(ws, match, tt, rep_summary, sara_totals,
                             churn, week_col_label, dry_run, logfn)
        for ln in lines:
            logfn(f"OPT NDS: {ln}")
        if lines and lines[0].startswith(("[OK]", "[DRY-RUN]")):
            filled.append(title)
        else:
            skipped.append(title)

    return {"filled": filled, "skipped": skipped, "errors": download_errors}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="Only this rep (substring match).")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse cached crosstabs instead of re-pulling.")
    args = ap.parse_args()
    result = run_nds_opt(dry_run=args.dry_run, only_rep=args.only,
                         skip_download=args.skip_download)
    print(f"\nFilled: {len(result['filled'])} tab(s); "
          f"Skipped: {len(result['skipped'])}; "
          f"Download errors: {len(result['errors'])}")
    for err in result["errors"]:
        print(f"  ✗ {err}")

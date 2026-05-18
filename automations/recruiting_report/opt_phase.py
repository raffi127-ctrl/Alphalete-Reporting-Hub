"""OPT phase — Tableau "ICD Summary" crosstabs → Focus Report OPT section.

Pulls two AUTOMATION PULL crosstabs from Tableau and writes the OPT-section
metrics into each ICD tab. No manual CSV downloads — the run drives Tableau's
own Download → Crosstab.

Sources:
  - ATT view (D2D 1-PAGER V4): headcount, sale types, ranking, % wireless,
    1 GIG%, and the national sales-per-rep average.
  - INT view (D2D 1-PAGER V2, Internet Only): new-internet per-rep average
    (per ICD + national).

What it writes, per ICD tab:
  OPT section ("OPT" anchor in column B):
    - scraped: Active Headcount, New Internets, Upgrades, DTV, New Lines,
      % of Wireless Rep Count, Scorecard Ranking, AVG New INT Per Active
      Headcount
    - computed (by label lookup, never hardcoded rows): Total Apps =
      sum of the four sale types; AVG Apps Per Active Headcount =
      Total Apps / Active Headcount
    - national (same value every tab): National AVG Apps, National New INT AVG
  Office Metrics section ("Office Metrics" anchor): 1 GIG%

Safety: only WRITES the cells above — never clears or deletes anything.

Run:
  .venv/bin/python -m automations.recruiting_report.opt_phase --only "Marcellus Butler" --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gspread
from playwright.sync_api import sync_playwright

from . import fetch_office, fill

WORKSPACE = Path(__file__).resolve().parent.parent.parent

# ATT crosstab — AUTOMATION PULL view of ATT TRACKER 2.1 - D2D / D2D 1-PAGER V4.
ATT_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/D2D1-PAGERV4/"
    "05356558-3732-4a96-af9d-99ee56f98138/AUTOMATIONPULL"
)
ATT_SHEET = "ICD Summary - ATT (V2)"
ATT_PATH = WORKSPACE / "output" / "opt_icd_summary_att.csv"

# INT crosstab — AUTOMATION PULL view of D2D 1-PAGER V2 (Internet Only).
INT_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/D2D1-PAGERV2InternetOnly/"
    "9a35d92c-65c1-4d12-ba6c-ebc381e1d00c/AUTOMATIONPULL"
)
INT_SHEET = "ICD Summary - ATT (V2) (2)"
INT_PATH = WORKSPACE / "output" / "opt_icd_summary_int.csv"

# Product Sales crosstab — AUTOMATION PULL view of PRODUCT SALES SUMMARY 4WK.
# Per-rep per-product per-day; used for each ICD's Personal Production.
PRODUCT_SALES_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
    "b2da26b8-8971-4a45-9e42-bd04af46f0fa/AUTOMATIONPULL"
)
PRODUCT_SALES_SHEET = "Sales By ICD (Weekly View)"
PRODUCT_SALES_PATH = WORKSPACE / "output" / "opt_personal_production.csv"

# Metrics crosstab — the Metrics view (Office-Metrics-section rates).
METRICS_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/Metrics/"
    "14b823c9-0ce7-4757-ba1b-4eb7a54a656f/AUTOMATIONPULL-METRICS"
)
METRICS_SHEET = "Metrics Call Last week data (Internet)"
METRICS_PATH = WORKSPACE / "output" / "opt_metrics.csv"

# Churn crosstab — AUTOMATION PULL custom view of CHURN (New Internet).
CHURN_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/CHURN/"
    "874bceda-72bf-4571-976b-9d998abacdbf/AUTOMATIONPULL-NICHURNVIEW"
)
CHURN_SHEET = "ICD Churn"
CHURN_PATH = WORKSPACE / "output" / "opt_churn.csv"
# Tableau product type -> short label, in the order they appear in the cell.
PRODUCT_LABELS = [
    ("NEW INTERNET", "NI"),
    ("VIDEO", "DTV"),
    ("WIRELESS", "NL"),
    ("UPGRADE INTERNET", "UG"),
]

# --- metric mapping (Sheet row label -> Tableau crosstab column header) ---
# OPT section — scraped straight from the ATT crosstab.
OPT_SCRAPED: Dict[str, str] = {
    "Active Headcount on Tableau": "Rep Count",
    "New Internets":               "New Internet",
    "Upgrades":                    "Upgrd Internet",
    "DTV":                         "Video Sales",
    "New Lines":                   "Wrlss Lines New/Port",
    "% of Wireless Rep Count":     "% Wireless rep count",
    "Scorecard Ranking":           "Ranking",
}
# OPT section — computed. Total Apps = sum of these four sale-type rows.
TOTAL_APPS_COMPONENTS = ["New Internets", "Upgrades", "DTV", "New Lines"]
# OPT section — national totals (Grand Total row), same value on every tab.
OPT_NATIONAL: Dict[str, str] = {"National AVG Apps": "Sales Per Rep Avg"}
# OPT section — scraped from the INT crosstab.
INT_SCRAPED: Dict[str, str] = {
    "AVG New INT Per Active Headcount": "New Int Sales Per Rep Avg",
}
INT_NATIONAL: Dict[str, str] = {
    "National New INT AVG": "New Int Sales Per Rep Avg",
}
# Office Metrics section — scraped from the ATT crosstab.
METRIC_GOALS_SCRAPED: Dict[str, str] = {"1 GIG%": "New Internet 1Gig+ Mix%"}
# Office Metrics section — scraped from the Metrics crosstab.
METRICS_SCRAPED: Dict[str, str] = {
    "6+ days out scheduled":   "% of sales scheduled 6+ days out (4 wks)",
    "0-30 Day Cancel Rate":    "0-30 day New Internet cancel rate",
    "30-60 activation rate %": "30-60 day New Internet activation rate",
}
# Office Metrics section — scraped from the CHURN crosstab (% values).
CHURN_SCRAPED: Dict[str, str] = {
    "0-30 Day Churn": "0-30 Day Churn",
    "30 Day Churn":   "30 Day Churn",
    "60 day Churn":   "60 Day Churn",
    "90 day Churn":   "90 Day Churn",
}

# Column-B section anchors that bound a section (normalized).
SECTION_ANCHORS = {"we sunday", "opt", "office metrics", "wireless metrics",
                   "extra data"}


def _norm(s) -> str:
    """Normalize a label / header / name for matching: lowercase, trim, drop
    apostrophes + periods, collapse whitespace, drop spaces around / - %."""
    s = str(s or "").strip().lower()
    s = s.replace("'", "").replace("’", "").replace(".", "")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([/\-%])\s*", r"\1", s)
    return s


# Some ICD tabs label an OPT row slightly differently — try these alternates.
ALT_LABELS: Dict[str, List[str]] = {
    "% of Wireless Rep Count": ["% of Wireless Attachment", "% Wireless Rep Count",
                                "% Wireless Attachment"],
    "National AVG Apps": ["National AVG for sales"],
}


def _to_num(s) -> Optional[float]:
    """Parse a crosstab cell to a number. Strips %, commas. None if blank."""
    t = str(s or "").strip().replace(",", "").replace("%", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------- download

def _find_tableau_page(browser):
    """Return an SSO'd Tableau tab in the connected Chrome, or None."""
    for ctx in browser.contexts:
        for pg in ctx.pages:
            u = (pg.url or "").lower()
            if "online.tableau.com" in u and "/login" not in u and "/idp/" not in u:
                return pg
    return None


def download_crosstab(view_url: str, crosstab_sheet: str, out_path: Path,
                      verbose: bool = True) -> Path:
    """Drive Tableau's Download → Crosstab on `view_url` and save the
    `crosstab_sheet` sheet as a CSV. Returns out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(fetch_office.CDP_URL)
        page = _find_tableau_page(browser)
        if page is None:
            raise RuntimeError(
                "No Tableau tab open in Report Chrome. Launch Report Chrome, "
                "log into ownerville, open Tableau — then run again."
            )
        page.goto(view_url, wait_until="domcontentloaded")

        viz = page.frame_locator('iframe[title="Data Visualization"]')
        dl_btn = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
        dl_btn.wait_for(state="visible", timeout=35_000)
        # Let Tableau hydrate the data behind the viz before exporting.
        page.wait_for_timeout(10_000)

        if verbose:
            print(f"Download → Crosstab → {crosstab_sheet!r} → CSV…", flush=True)
        dl_btn.click()
        page.wait_for_timeout(1800)
        viz.locator('[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]').click()
        page.wait_for_timeout(3500)

        thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
        idx = None
        for i in range(thumbs.count()):
            if thumbs.nth(i).inner_text().strip() == crosstab_sheet:
                idx = i
                break
        if idx is None:
            raise RuntimeError(
                f"Couldn't find the {crosstab_sheet!r} sheet in the Crosstab "
                "dialog — the AUTOMATION PULL view may have changed."
            )
        thumbs.nth(idx).click()
        page.wait_for_timeout(1200)
        viz.locator('[data-tb-test-id="crosstab-options-dialog-radio-csv-Label"]').click()
        page.wait_for_timeout(500)
        with page.expect_download(timeout=90_000) as dl_info:
            viz.locator('[data-tb-test-id="export-crosstab-export-Button"]').click()
        dl_info.value.save_as(str(out_path))
    if verbose:
        print(f"saved crosstab: {out_path} ({out_path.stat().st_size:,} bytes)", flush=True)
    return out_path


# ------------------------------------------------------------------- parse

def parse_icd_summary(path: Path) -> Tuple[Dict[str, dict], dict]:
    """Parse the UTF-16, tab-delimited crosstab.

    Returns (by_owner, national):
      by_owner  — {normalized owner name: {"owner": raw, "values": {norm header: cell}}}
      national  — {norm header: cell} from the 'Grand Total' row
    """
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    if not rows:
        raise RuntimeError("crosstab file is empty")
    headers = [_norm(h) for h in rows[0]]
    # The ICD-name column is usually col 0, but some views (Metrics) put it
    # later — find it by header instead of assuming.
    owner_col = next((i for i, h in enumerate(headers)
                      if "icd owner name" in h), 0)

    by_owner: Dict[str, dict] = {}
    national: dict = {}
    for r in rows[1:]:
        owner = (r[owner_col] if len(r) > owner_col else "").strip()
        if not owner:
            continue
        rec = {headers[i]: r[i].strip() for i in range(min(len(headers), len(r)))}
        if owner.lower() in ("grand total", "total"):
            national = rec
        else:
            by_owner[_norm(owner)] = {"owner": owner, "values": rec}
    return by_owner, national


def parse_personal_production(path: Path) -> Dict[str, dict]:
    """Parse the per-rep PRODUCT SALES crosstab into each rep's own weekly
    sales. Columns: Owner Name, Rep, Product Type, then 7 day columns.

    Returns {normalized rep name: {"owner": raw rep, "values": {PRODUCT TYPE:
    week total}}} — same shape as parse_icd_summary so _match_owner works."""
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) < 4:
            continue
        rep = (r[1] or "").strip()
        ptype = (r[2] or "").strip().upper()
        if not rep or rep.lower() == "total" or ptype.lower() in ("total", ""):
            continue
        week_total = 0
        for cell in r[3:]:
            n = _to_num(cell)
            if n:
                week_total += int(n)
        if week_total:
            entry = out.setdefault(_norm(rep), {"owner": rep, "values": {}})
            entry["values"][ptype] = entry["values"].get(ptype, 0) + week_total
    return out


def _format_personal_production(products: Dict[str, int]) -> str:
    """Render a rep's product counts as e.g. '2 NI / 1 DTV / 3 NL'."""
    parts = [f"{products[ptype]} {label}"
             for ptype, label in PRODUCT_LABELS if products.get(ptype)]
    return " / ".join(parts)


def parse_churn(path: Path) -> Dict[str, dict]:
    """Parse the CHURN 'ICD Churn' crosstab. Each ICD spans several measure
    rows AND several colour blocks (Green/Red/Yellow) — each block fills only
    some of the 0-30 / 30 / 60 / 90 day columns. Keep only the 'Churn Rate
    (Unit vs Order)' rows and MERGE their non-empty cells, so an ICD ends up
    with all four churn values.

    Returns {normalized ICD name: {"owner": raw, "values": {norm header: cell}}}."""
    raw = Path(path).read_text(encoding="utf-16")
    rows = [ln.split("\t") for ln in raw.splitlines() if ln.strip()]
    if not rows:
        raise RuntimeError("churn crosstab file is empty")
    headers = [_norm(h) for h in rows[0]]
    owner_col = next((i for i, h in enumerate(headers)
                      if "icd owner name" in h), 0)
    out: Dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) <= owner_col:
            continue
        owner = r[owner_col].strip()
        if not owner or owner.lower() in ("grand total", "total"):
            continue
        # Keep only churn-rate rows; merge their non-empty cells per ICD.
        if not any("churn rate" in _norm(c) for c in r):
            continue
        entry = out.setdefault(_norm(owner), {"owner": owner, "values": {}})
        for i in range(min(len(headers), len(r))):
            cell = r[i].strip()
            if cell:
                entry["values"][headers[i]] = cell
    return out


def _match_owner(tab_name: str, by_owner: dict, aliases_map: dict) -> Optional[dict]:
    """Find the crosstab row for a Sheet tab. Tries, in order: the tab name,
    its parenthetical (a tab named 'X (Y)' also tries Y and X), every alias
    for it, then a subset match (one name has an extra middle name, same
    surname). All comparisons ignore case, apostrophes, and extra spacing."""
    candidates = [tab_name]
    m = re.match(r"^(.*?)\s*\((.+?)\)\s*$", tab_name or "")
    if m:
        candidates += [m.group(1).strip(), m.group(2).strip()]
    norm_tab = _norm(tab_name)
    for canonical, aliases in (aliases_map or {}).items():
        group = [canonical] + list(aliases)
        if norm_tab in {_norm(g) for g in group}:
            candidates.extend(group)
    for cand in candidates:
        hit = by_owner.get(_norm(cand))
        if hit:
            return hit
    # Subset fallback: same surname (last word) AND one name's word set is a
    # subset of the other — catches a middle name present on only one side.
    tw = norm_tab.split()
    if len(tw) >= 2:
        for key, hit in by_owner.items():
            kw = key.split()
            if kw and kw[-1] == tw[-1] and (set(tw) <= set(kw) or set(kw) <= set(tw)):
                return hit
    return None


# -------------------------------------------------------------------- fill

def _section_label_rows(col_b: List[str], is_anchor) -> Dict[str, int]:
    """{normalized label: 1-indexed row} for the section whose header matches
    is_anchor() in column B — scoped from the anchor to the next section
    anchor. Handles tabs (e.g. Raf's) with an extra section: the section is
    found by its anchor, never by a hardcoded row number."""
    start = None
    for j, v in enumerate(col_b):
        if is_anchor(_norm(v)):
            start = j
            break
    if start is None:
        return {}
    out: Dict[str, int] = {}
    for j in range(start + 1, len(col_b)):
        nv = _norm(col_b[j])
        if not nv:
            continue
        if nv in SECTION_ANCHORS or "office performance tracker" in nv:
            break
        out.setdefault(nv, j + 1)
    return out


def _is_opt_anchor(nv: str) -> bool:
    return nv == "opt" or "office performance tracker" in nv


def _is_office_metrics_anchor(nv: str) -> bool:
    return nv == "office metrics"


def fill_opt_for_tab(
    sh: gspread.Spreadsheet, tab_name: str,
    att_by_owner: dict, att_national: dict,
    int_by_owner: dict, int_national: dict,
    metrics_by_owner: dict, churn_by_owner: dict, personal_prod: dict,
    aliases_map: dict, week_sunday: dt.date, dry_run: bool,
) -> List[str]:
    """Write the OPT + Office-Metrics values for one ICD tab from the ATT and
    INT crosstabs. Returns log lines. Only writes mapped cells — never clears."""
    try:
        ws = fill._retry(sh.worksheet, tab_name)
    except Exception as e:
        return [f"[SKIP] {tab_name}: tab not found ({e})"]

    att_row = _match_owner(tab_name, att_by_owner, aliases_map)
    int_row = _match_owner(tab_name, int_by_owner, aliases_map)
    metrics_row = _match_owner(tab_name, metrics_by_owner, aliases_map)
    if not att_row and not int_row and not metrics_row:
        return [f"[SKIP] {tab_name}: no crosstab row (ATT / INT / Metrics)"]

    grid = fill._retry(ws.get_all_values)
    sunday_to_col = fill.find_sunday_columns(grid, header_row_idx=0)
    col = sunday_to_col.get(week_sunday)
    if not col:
        return [f"[SKIP] {tab_name}: no column for week {week_sunday.isoformat()}"]

    col_b = [r[1] if len(r) > 1 else "" for r in grid]
    opt_rows = _section_label_rows(col_b, _is_opt_anchor)
    om_rows = _section_label_rows(col_b, _is_office_metrics_anchor)
    if not opt_rows:
        return [f"[SKIP] {tab_name}: no OPT section anchor found in column B"]

    updates: List[Tuple[str, object]] = []
    missing: List[str] = []

    def _queue(label_rows: Dict[str, int], sheet_label: str, value) -> bool:
        for lbl in [sheet_label] + ALT_LABELS.get(sheet_label, []):
            r = label_rows.get(_norm(lbl))
            if r:
                updates.append((gspread.utils.rowcol_to_a1(r, col), value))
                return True
        missing.append(sheet_label)
        return False

    # --- ATT crosstab ---
    if att_row:
        av = att_row["values"]
        for sheet_label, csv_col in OPT_SCRAPED.items():
            cell = av.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(opt_rows, sheet_label, cell)
        # computed: Total Apps + AVG Apps (component rows found by label)
        parts = [_to_num(av.get(_norm(OPT_SCRAPED[c]), ""))
                 for c in TOTAL_APPS_COMPONENTS]
        total_apps = None
        if all(p is not None for p in parts):
            total_apps = int(sum(parts))
            _queue(opt_rows, "Total Apps", total_apps)
        headcount = _to_num(av.get(_norm(OPT_SCRAPED["Active Headcount on Tableau"]), ""))
        if total_apps is not None and headcount:
            _queue(opt_rows, "AVG Apps Per Active Headcount",
                   round(total_apps / headcount, 1))
        # Office Metrics — 1 GIG%
        for sheet_label, csv_col in METRIC_GOALS_SCRAPED.items():
            cell = av.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(om_rows, sheet_label, cell)
    # ATT national (same value on every tab)
    for sheet_label, csv_col in OPT_NATIONAL.items():
        cell = att_national.get(_norm(csv_col), "")
        if str(cell).strip() != "":
            _queue(opt_rows, sheet_label, cell)

    # --- INT crosstab ---
    if int_row:
        iv = int_row["values"]
        for sheet_label, csv_col in INT_SCRAPED.items():
            cell = iv.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(opt_rows, sheet_label, cell)
    for sheet_label, csv_col in INT_NATIONAL.items():
        cell = int_national.get(_norm(csv_col), "")
        if str(cell).strip() != "":
            _queue(opt_rows, sheet_label, cell)

    # --- Metrics view (Office Metrics section) ---
    if metrics_row:
        mv = metrics_row["values"]
        for sheet_label, csv_col in METRICS_SCRAPED.items():
            cell = mv.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(om_rows, sheet_label, cell)

    # --- CHURN view (Office Metrics section) ---
    churn_row = _match_owner(tab_name, churn_by_owner, aliases_map)
    if churn_row:
        cv = churn_row["values"]
        for sheet_label, csv_col in CHURN_SCRAPED.items():
            cell = cv.get(_norm(csv_col), "")
            if str(cell).strip() != "":
                _queue(om_rows, sheet_label, cell)

    # --- Personal Production (the ICD's own sales as a rep) ---
    # Always written — an ICD with no personal sales gets a literal 0.
    pp_row = _match_owner(tab_name, personal_prod, aliases_map)
    text = _format_personal_production(pp_row["values"]) if pp_row else ""
    _queue(opt_rows, "Personal Production", text or "0")

    if not updates:
        return [f"[SKIP] {tab_name}: nothing to write"]

    if dry_run:
        log = [f"[DRY-RUN] {tab_name} (col {col}, week {week_sunday}): "
               f"would write {len(updates)} cells"]
        for a1, v in updates:
            log.append(f"    {a1} <- {v}")
    else:
        fill._retry(ws.batch_update, [
            {"range": a1, "values": [[v]]} for a1, v in updates
        ], value_input_option="USER_ENTERED")
        log = [f"[OK] {tab_name}: wrote {len(updates)} cells (col {col})"]
    if missing:
        log.append(f"    [note] labels not found on tab: {', '.join(missing)}")
    return log


def _week_url(base_url: str, we_sunday: dt.date) -> str:
    """Append Tableau's 'Sale Date Week Ending (mon-sun)' filter param so the
    view loads the target week."""
    from urllib.parse import quote
    return (f"{base_url}?{quote('Sale Date Week Ending (mon-sun)')}"
            f"={quote(str(we_sunday))}")


def _most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    """The most recent Sunday on or before today — the week that just ended."""
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def run_opt_phase(we_sunday: Optional[dt.date] = None, only: Optional[str] = None,
                  dry_run: bool = False, skip_download: bool = False,
                  logfn=print) -> dict:
    """Download the ATT + INT ICD Summary crosstabs from Tableau and fill the
    OPT section on the target ICD tabs. Entry point the weekly report's run.py
    calls. Returns {"filled": [...], "skipped": [...]}."""
    if we_sunday is None:
        we_sunday = _most_recent_sunday()
    if skip_download:
        for pth, lbl in [(ATT_PATH, "ATT"), (INT_PATH, "INT"),
                         (PRODUCT_SALES_PATH, "Product Sales"),
                         (METRICS_PATH, "Metrics"), (CHURN_PATH, "Churn")]:
            if not pth.exists():
                raise RuntimeError(f"--skip-download but no {lbl} crosstab at {pth}")
        logfn("OPT: reusing previously-downloaded crosstabs")
    else:
        download_crosstab(ATT_VIEW_URL, ATT_SHEET, ATT_PATH, verbose=False)
        download_crosstab(INT_VIEW_URL, INT_SHEET, INT_PATH, verbose=False)
        download_crosstab(_week_url(PRODUCT_SALES_VIEW_URL, we_sunday),
                          PRODUCT_SALES_SHEET, PRODUCT_SALES_PATH, verbose=False)
        download_crosstab(METRICS_VIEW_URL, METRICS_SHEET, METRICS_PATH, verbose=False)
        download_crosstab(CHURN_VIEW_URL, CHURN_SHEET, CHURN_PATH, verbose=False)
        logfn("OPT: downloaded ATT + INT + Product Sales + Metrics + Churn crosstabs")

    att_by_owner, att_national = parse_icd_summary(ATT_PATH)
    int_by_owner, int_national = parse_icd_summary(INT_PATH)
    personal_prod = parse_personal_production(PRODUCT_SALES_PATH)
    metrics_by_owner, _ = parse_icd_summary(METRICS_PATH)
    churn_by_owner = parse_churn(CHURN_PATH)
    logfn(f"OPT: parsed {len(att_by_owner)} ATT, {len(int_by_owner)} INT, "
          f"{len(metrics_by_owner)} Metrics, {len(churn_by_owner)} Churn, "
          f"{len(personal_prod)} reps for Personal Production"
          + ("" if att_national and int_national
             else " — WARNING: a national total row is missing"))

    try:
        from automations.focus_office_att import aliases as _al
        aliases_map = _al.load_aliases()
    except Exception:
        aliases_map = {}

    sh = fill.open_sheet()
    targets = [only] if only else [c["sheet_tab"]
                                   for c in fill.load_mapping()["confirmed"]]
    filled: List[str] = []
    skipped: List[str] = []
    for tab_name in targets:
        lines = fill_opt_for_tab(sh, tab_name, att_by_owner, att_national,
                                 int_by_owner, int_national, metrics_by_owner,
                                 churn_by_owner, personal_prod,
                                 aliases_map, we_sunday, dry_run)
        for ln in lines:
            logfn("OPT: " + ln)
        if any(ln.startswith("[OK]") or ln.startswith("[DRY-RUN]") for ln in lines):
            filled.append(tab_name)
        else:
            skipped.append(tab_name)
    return {"filled": filled, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Only this ICD tab (by tab name).")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD. Default: most recent Sunday.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write to the Sheet — just print what would change.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the last downloaded crosstabs instead of re-pulling.")
    args = ap.parse_args()

    week = dt.date.fromisoformat(args.week) if args.week else _most_recent_sunday()
    print(f"OPT phase — target week (WE Sunday): {week.isoformat()}  dry_run={args.dry_run}")
    try:
        result = run_opt_phase(week, only=args.only, dry_run=args.dry_run,
                               skip_download=args.skip_download)
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1
    print(f"done — {len(result['filled'])} filled, {len(result['skipped'])} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())

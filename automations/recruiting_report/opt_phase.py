"""OPT phase — Tableau "ICD Summary" → Focus Report OPT section.

Pulls the 'ICD Summary - ATT (V2)' crosstab from the AUTOMATION PULL view
(ATT TRACKER 2.1 - D2D / D2D 1-PAGER V4) in Tableau and writes the OPT-section
metrics into each ICD tab. No manual CSV downloads — the run drives Tableau's
own Download → Crosstab.

What it writes, per ICD tab:
  OPT section ("OPT" anchor in column B):
    - scraped straight from the crosstab: Active Headcount on Tableau,
      New Internets, Upgrades, DTV, New Lines, % of Wireless Rep Count,
      Scorecard Ranking
    - computed (by label lookup, never hardcoded rows): Total Apps =
      sum of the four sale types; AVG Apps Per Active Headcount =
      Total Apps / Active Headcount
    - national (same value every tab): National AVG Apps
  Office Metrics section ("Office Metrics" anchor): 1 GIG%

Safety: only WRITES the cells above — never clears or deletes anything.

Run:
  .venv/bin/python -m automations.recruiting_report.opt_phase --only "Marcellus Butler" --dry-run
  .venv/bin/python -m automations.recruiting_report.opt_phase --only "Marcellus Butler"
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
DOWNLOAD_PATH = WORKSPACE / "output" / "opt_icd_summary_att.csv"

# AUTOMATION PULL custom view of ATT TRACKER 2.1 - D2D / D2D 1-PAGER V4.
TABLEAU_AUTOMATION_PULL_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/D2D1-PAGERV4/"
    "05356558-3732-4a96-af9d-99ee56f98138/AUTOMATIONPULL"
)
# The crosstab sheet (in Download → Crosstab) that holds one row per ICD,
# current week. The "(LW)" sibling is last week.
CROSSTAB_SHEET = "ICD Summary - ATT (V2)"

# --- metric mapping (Sheet row label -> Tableau crosstab column header) ---
# OPT section — scraped straight from the crosstab.
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
# Office Metrics section — scraped straight.
METRIC_GOALS_SCRAPED: Dict[str, str] = {"1 GIG%": "New Internet 1Gig+ Mix%"}

# Column-B section anchors that bound a section (normalized).
SECTION_ANCHORS = {"we sunday", "opt", "office metrics", "wireless metrics",
                   "extra data"}


def _norm(s) -> str:
    """Normalize a label / header / name for matching: lowercase, trim,
    collapse internal whitespace, drop spaces around / - %."""
    s = str(s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([/\-%])\s*", r"\1", s)
    return s


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


def download_icd_summary(out_path: Path = DOWNLOAD_PATH, verbose: bool = True) -> Path:
    """Drive Tableau's Download → Crosstab on the AUTOMATION PULL view and
    save the 'ICD Summary - ATT (V2)' sheet as a CSV. Returns out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(fetch_office.CDP_URL)
        page = _find_tableau_page(browser)
        if page is None:
            raise RuntimeError(
                "No Tableau tab open in Report Chrome. Launch Report Chrome, "
                "open Tableau, and log in — then run again."
            )
        if "AUTOMATIONPULL" not in (page.url or "").upper():
            if verbose:
                print(f"navigating Tableau tab to AUTOMATION PULL", flush=True)
            page.goto(TABLEAU_AUTOMATION_PULL_URL, wait_until="domcontentloaded")

        viz = page.frame_locator('iframe[title="Data Visualization"]')
        dl_btn = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
        dl_btn.wait_for(state="visible", timeout=30_000)
        # Let Tableau hydrate the data behind the viz before exporting.
        page.wait_for_timeout(10_000)

        if verbose:
            print("Download → Crosstab → 'ICD Summary - ATT (V2)' → CSV…", flush=True)
        dl_btn.click()
        page.wait_for_timeout(1800)
        viz.locator('[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]').click()
        page.wait_for_timeout(3500)

        thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
        idx = None
        for i in range(thumbs.count()):
            if thumbs.nth(i).inner_text().strip() == CROSSTAB_SHEET:
                idx = i
                break
        if idx is None:
            raise RuntimeError(
                f"Couldn't find the '{CROSSTAB_SHEET}' sheet in the Crosstab "
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

    by_owner: Dict[str, dict] = {}
    national: dict = {}
    for r in rows[1:]:
        owner = (r[0] if r else "").strip()
        if not owner:
            continue
        rec = {headers[i]: r[i].strip() for i in range(min(len(headers), len(r)))}
        if owner.lower() == "grand total":
            national = rec
        else:
            by_owner[_norm(owner)] = {"owner": owner, "values": rec}
    return by_owner, national


def _match_owner(tab_name: str, by_owner: dict, aliases_map: dict) -> Optional[dict]:
    """Find the crosstab row for a Sheet tab — tries the tab name plus every
    alias for it (shared 'ICD Aliases' list), case/space-insensitive."""
    candidates = [tab_name]
    norm_tab = _norm(tab_name)
    for canonical, aliases in (aliases_map or {}).items():
        group = [canonical] + list(aliases)
        if norm_tab in {_norm(g) for g in group}:
            candidates.extend(group)
    for cand in candidates:
        hit = by_owner.get(_norm(cand))
        if hit:
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
    sh: gspread.Spreadsheet, tab_name: str, by_owner: dict, national: dict,
    aliases_map: dict, week_sunday: dt.date, dry_run: bool,
) -> List[str]:
    """Write the OPT + Office-Metrics values for one ICD tab. Returns log
    lines. Only ever writes the mapped cells — never clears anything."""
    log: List[str] = []
    try:
        ws = fill._retry(sh.worksheet, tab_name)
    except Exception as e:
        return [f"[SKIP] {tab_name}: tab not found ({e})"]

    row = _match_owner(tab_name, by_owner, aliases_map)
    if not row:
        return [f"[SKIP] {tab_name}: no crosstab row for this ICD"]
    vals = row["values"]

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
        r = label_rows.get(_norm(sheet_label))
        if not r:
            missing.append(sheet_label)
            return False
        updates.append((gspread.utils.rowcol_to_a1(r, col), value))
        return True

    # OPT — scraped
    for sheet_label, csv_col in OPT_SCRAPED.items():
        cell = vals.get(_norm(csv_col), "")
        if str(cell).strip() != "":
            _queue(opt_rows, sheet_label, cell)
    # OPT — national (same value everywhere)
    for sheet_label, csv_col in OPT_NATIONAL.items():
        cell = national.get(_norm(csv_col), "")
        if str(cell).strip() != "":
            _queue(opt_rows, sheet_label, cell)
    # OPT — computed: Total Apps + AVG Apps (component rows found by label)
    parts = [_to_num(vals.get(_norm(OPT_SCRAPED[c]), "")) for c in TOTAL_APPS_COMPONENTS]
    total_apps = None
    if all(p is not None for p in parts):
        total_apps = int(sum(parts))
        _queue(opt_rows, "Total Apps", total_apps)
    headcount = _to_num(vals.get(_norm(OPT_SCRAPED["Active Headcount on Tableau"]), ""))
    if total_apps is not None and headcount:
        _queue(opt_rows, "AVG Apps Per Active Headcount", round(total_apps / headcount, 1))
    # Office Metrics — scraped (1 GIG%)
    for sheet_label, csv_col in METRIC_GOALS_SCRAPED.items():
        cell = vals.get(_norm(csv_col), "")
        if str(cell).strip() != "":
            if not _queue(om_rows, sheet_label, cell) and not om_rows:
                missing[-1] = f"{sheet_label} (no Office Metrics section)"

    if not updates:
        return log + [f"[SKIP] {tab_name}: nothing to write"]

    if dry_run:
        log.append(f"[DRY-RUN] {tab_name} (col {col}, week {week_sunday}): "
                   f"would write {len(updates)} cells")
        for a1, v in updates:
            log.append(f"    {a1} <- {v}")
    else:
        fill._retry(ws.batch_update, [
            {"range": a1, "values": [[v]]} for a1, v in updates
        ], value_input_option="USER_ENTERED")
        log.append(f"[OK] {tab_name}: wrote {len(updates)} cells (col {col})")
    if missing:
        log.append(f"    [note] labels not found on tab: {', '.join(missing)}")
    return log


def _current_week_sunday(today: Optional[dt.date] = None) -> dt.date:
    """The Sunday that ends the current Mon-Sun week."""
    today = today or dt.date.today()
    return today + dt.timedelta(days=(6 - today.weekday()) % 7)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Only this ICD tab (by tab name).")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD. Default: this week.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write to the Sheet — just print what would change.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the last downloaded crosstab instead of re-pulling.")
    args = ap.parse_args()

    week = dt.date.fromisoformat(args.week) if args.week else _current_week_sunday()
    print(f"OPT phase — target week (WE Sunday): {week.isoformat()}  dry_run={args.dry_run}")

    if args.skip_download:
        if not DOWNLOAD_PATH.exists():
            print(f"FAIL: --skip-download but no file at {DOWNLOAD_PATH}")
            return 1
        print(f"reusing {DOWNLOAD_PATH}")
    else:
        download_icd_summary(DOWNLOAD_PATH)

    by_owner, national = parse_icd_summary(DOWNLOAD_PATH)
    print(f"parsed crosstab: {len(by_owner)} ICDs, "
          f"national row {'found' if national else 'MISSING'}")

    try:
        from automations.focus_office_att import aliases as _al
        aliases_map = _al.load_aliases()
    except Exception:
        aliases_map = {}

    sh = fill.open_sheet()

    if args.only:
        targets = [args.only]
    else:
        targets = [c["sheet_tab"] for c in fill.load_mapping()["confirmed"]]

    for tab_name in targets:
        for line in fill_opt_for_tab(sh, tab_name, by_owner, national,
                                     aliases_map, week, args.dry_run):
            print(line)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

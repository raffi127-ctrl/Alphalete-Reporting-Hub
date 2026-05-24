"""JE (Just Energy) OPT fill for the Alphalete Org sheet.

Per-campaign OPT pull for the JE tabs (one rep for now: Cinthya Reyes).
Mirrors the Retail Costco pattern — per-store sales summed across the
week's days, plus office totals. Sources + mapping documented in
resources/opt-section/alphalete-org-campaign-sources.md.

Fills (this module):
  - Per-store sales (Sams ####, Walmart ###, Test Location): sum of the
    store's daily columns for the target week, from
    JEAllRetailersSalesSummarybyLocation / 'All RTL Sales Summary by Store'
    filtered to the ICD + Sales Week Ending (both honored as URL params).
  - Total Sales      = sum of all stores (= the Grand Total row)
  - Total Store Count = # stores with production > 0
  - AVG Sales per Store = sheet FORMULA (=Total Sales / Total Store Count),
    cells looked up by label (never hardcoded) per Megan 2026-05-24.

Manual / formula / future (NOT written here):
  - AVG Sales per Leader = Total Sales / Leaders (Leaders is manual) — formula
  - Conversion + Personal Production — from 6WkConversionTracker (follow-up)
  - Direct Deposit — Program Summary email (manual)

New store numbers appear week to week — inserted dynamically like Retail
Costco. A listed store with no production is written 0.
"""

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gspread

from automations.recruiting_report import fill as rfill
from automations.alphalete_org_report.opt_nds import (
    ALPHALETE_ORG_SHEET_ID,
    OUTPUT_DIR,
    _read_tab_csv,
    _norm_owner,
    _find_week_col,
    _find_row_by_label,
    _current_target_week_col_label,
    _current_target_week_end,
)
from automations.shared.tableau_patchright import (
    tableau_session,
    download_crosstab_patchright,
)


JE_SALES_BASE = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "JustEnergyRTL-SalesStaffingProductivityWorkbook/"
    "JEAllRetailersSalesSummarybyLocation"
)
JE_SALES_SHEET = "All RTL Sales Summary by Store"
JE_SALES_FILENAME = "opt_je_sales_by_store.csv"

# Direct Deposit — DirectDepositICDVIEWVersion2_0 / PROGRAMSUMMARY /
# DOWNLINEVIEW, worksheet 'Sheet 7 (3)' (the downline grid). Per Megan
# 2026-05-24, DD = 'Grand Total to ICD' for the ICD's row — but Tableau
# leaves that computed column blank in the export, so we sum the per-
# campaign dollar columns in the row instead (for a JE-only ICD that's
# just the 'Just Energy' column; for the rare multi-campaign ICD it's the
# true grand total). Same Direct Deposit workbook family as NDS.
JE_DD_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "DirectDepositICDVIEWVersion2_0/PROGRAMSUMMARY/"
    "15c897de-6162-469b-9ef7-1735d235f2a8/DOWNLINEVIEW?:iid=1"
)
JE_DD_SHEET = "Sheet 7 (3)"
JE_DD_FILENAME = "opt_je_direct_deposit.csv"


def _je_sales_url(icd_name: str, week_end: dt.date) -> str:
    """Sales-by-store URL filtered to the ICD + target week. Both
    'ICD Name' and 'Sales Week Ending' are honored as URL params
    (verified 2026-05-24); date format is ISO."""
    from urllib.parse import quote
    return (
        f"{JE_SALES_BASE}?:iid=1"
        f"&ICD%20Name={quote(icd_name)}"
        f"&Sales%20Week%20Ending={week_end.isoformat()}"
    )


# Store-label normalizer. Tableau uses "Sam's Club #6265" / "Walmart #471";
# the sheet uses "Sams 6265" / "Walmart 471" / "Test Location". Reduce both
# to a comparable key.
_STORE_NUM_RE = re.compile(r"#?\s*(\d{3,5})")


def _normalize_je_store(label: str) -> Optional[str]:
    """Reduce a store label (sheet or Tableau) to a normalized key like
    'sams 6265' / 'walmart 471' / 'test location'. Returns None if the
    label isn't a store row."""
    if not label:
        return None
    low = label.strip().lower()
    if "test location" in low:
        return "test location"
    # 'sam'/'sams' + the 'sasm' typo present on the sheet (Sasm 8217).
    if low.startswith(("sam", "sasm")):
        m = _STORE_NUM_RE.search(low)
        return f"sams {m.group(1)}" if m else None
    if low.startswith("walmart"):
        m = _STORE_NUM_RE.search(low)
        return f"walmart {m.group(1)}" if m else None
    return None


def parse_je_sales_by_store(path: Path) -> Dict[str, int]:
    """Parse 'All RTL Sales Summary by Store' Crosstab → {store_key: week_total}.

    Layout: a multi-row header (a Date row + a label row), then store rows.
    Columns: Location (group) | State | Store City | Blank | sales colors |
    <one column per day of the week>. A store can span multiple rows (main
    sales row + an 'orange' staffed-no-sales row + occasional 'Cases' row);
    we sum every numeric daily cell across all of a store's rows. The
    'Grand Total' row is skipped (we re-derive Total Sales from the stores).
    """
    rows = _read_tab_csv(path)
    if not rows:
        return {}
    # Find the row whose first cell is 'Location  (group)' — that's the
    # column-label row; the day columns are the ones after 'sales colors'.
    label_row_i = None
    for i, r in enumerate(rows[:6]):
        if r and "location" in (r[0] or "").strip().lower():
            label_row_i = i
            break
    if label_row_i is None:
        return {}
    header = rows[label_row_i]
    # Day columns = everything after the 'sales colors' column.
    sc_i = next((j for j, h in enumerate(header)
                 if "sales colors" in (h or "").strip().lower()), None)
    if sc_i is None:
        return {}
    day_cols = list(range(sc_i + 1, len(header)))

    out: Dict[str, int] = {}
    for r in rows[label_row_i + 1:]:
        if not r:
            continue
        loc = (r[0] or "").strip()
        if loc.lower().startswith("grand total") or loc.lower() == "total":
            continue
        key = _normalize_je_store(loc)
        if key is None:
            continue
        total = 0
        for c in day_cols:
            if c >= len(r):
                continue
            cell = (r[c] or "").strip().replace(",", "")
            if not cell:
                continue
            try:
                total += int(float(cell))
            except ValueError:
                continue
        out[key] = out.get(key, 0) + total
    return out


JE_CONV_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "6WkConversionTracker/6WeekTrackerbyRep?:iid=1"
)
JE_CONV_SHEET = "6 Week Tracker by ICD & Rep"
JE_CONV_FILENAME = "opt_je_conversion.csv"


def _parse_pct(s: str) -> Optional[float]:
    s = (s or "").strip().replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_dollars(s: str) -> Optional[float]:
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_je_conversion(path: Path, icd_norm: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse '6 Week Tracker by ICD & Rep' → (office_avg_conversion,
    icd_own_total_sales).

    Layout: row0 groups (Conversion % ×N, Total Sales ×N, Total Installs ×N),
    row1 = Owner | Rep | <week dates per group>, then one row per rep.
    - Conversion (office avg) = simple mean of every rep's Conversion %
      across all shown weeks (Megan 2026-05-24: 'general avg', eyeball-OK —
      the tracker's week window isn't URL-controllable so we use whatever
      recent weeks it shows).
    - Personal Production = the ICD's OWN row (Rep == ICD name) Total Sales
      for the latest shown week.
    """
    rows = _read_tab_csv(path)
    if len(rows) < 3:
        return None, None
    groups = rows[0]
    conv_cols = [i for i, g in enumerate(groups)
                 if "conversion" in (g or "").strip().lower()]
    sales_cols = [i for i, g in enumerate(groups)
                  if (g or "").strip().lower() == "total sales"]
    conv_vals: List[float] = []
    own_sales: Optional[str] = None
    for r in rows[2:]:
        if len(r) < 2:
            continue
        for c in conv_cols:
            v = _parse_pct(r[c]) if c < len(r) else None
            if v is not None:
                conv_vals.append(v)
        if _norm_owner(r[1]) == icd_norm:
            vals = [r[c].strip() for c in sales_cols
                    if c < len(r) and (r[c] or "").strip()]
            if vals:
                own_sales = vals[-1]   # latest shown week
    office_avg = f"{round(sum(conv_vals) / len(conv_vals))}%" if conv_vals else None
    return office_avg, own_sales


def parse_je_direct_deposit(path: Path, icd_norm: str) -> Optional[str]:
    """Parse PROGRAMSUMMARY/DOWNLINEVIEW 'Sheet 7 (3)' → the ICD's
    Grand Total to ICD as a '$X,XXX.XX' string. Tableau leaves the
    'Grand Total to ICD' column blank in the export, so we sum the
    per-campaign dollar columns in the ICD's row."""
    rows = _read_tab_csv(path)
    if len(rows) < 2:
        return None
    header = rows[0]
    name_i = next((i for i, h in enumerate(header)
                   if "icd owner name" in (h or "").strip().lower()), None)
    if name_i is None:
        return None
    # Dollar columns = everything after 'Grand Total to ICD' (the campaign
    # breakdown); fall back to any cell that parses as dollars.
    gt_i = next((i for i, h in enumerate(header)
                 if "grand total to icd" in (h or "").strip().lower()), None)
    for r in rows[1:]:
        if name_i >= len(r) or _norm_owner(r[name_i]) != icd_norm:
            continue
        start = (gt_i + 1) if gt_i is not None else 0
        total = 0.0
        for c in range(start, len(r)):
            d = _parse_dollars(r[c])
            if d is not None:
                total += d
        return f"${total:,.2f}"
    return None


def fill_je_tab(ws: gspread.Worksheet, by_store: Dict[str, int],
                week_col_label: str, dry_run: bool = False,
                logfn=print,
                conversion: Optional[str] = None,
                personal_production: Optional[str] = None,
                direct_deposit: Optional[str] = None) -> List[str]:
    """Fill the JE per-store rows + Total Sales + Total Store Count +
    AVG Sales per Store (formula) into the target week column.

    Per-store: sum from `by_store` (0 if a listed store had no production).
    New store with production but no row yet → inserted below the last
    store row (like Retail Costco). Total Sales = sum of all stores;
    Total Store Count = # stores with production > 0. AVG Sales per Store
    is written as a sheet formula referencing the Total Sales + Total
    Store Count cells (looked up by label)."""
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-je] {ws.title}: empty tab"]
    week_col = _find_week_col(grid, week_col_label)
    if week_col is None:
        return [f"[skip-je] {ws.title}: no column for week {week_col_label}"]

    # Existing store rows (row_0idx, key, label)
    existing: List[tuple] = []
    for ri, row in enumerate(grid):
        label = (row[1] if len(row) > 1 else "").strip()
        key = _normalize_je_store(label)
        if key is not None:
            existing.append((ri, key, label))
    existing_keys = {k for _, k, _ in existing}

    # New stores with production not yet on the sheet → insert rows.
    new_stores = sorted(
        ((k, v) for k, v in by_store.items() if v > 0 and k not in existing_keys),
        key=lambda kv: kv[0],
    )
    if new_stores and existing and not dry_run:
        insert_at_0 = max(r for r, _, _ in existing) + 1
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
            "insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "ROWS",
                          "startIndex": insert_at_0,
                          "endIndex": insert_at_0 + len(new_stores)},
                "inheritFromBefore": True,
            }}]})
        grid = rfill._retry(ws.get_all_values)
        week_col = _find_week_col(grid, week_col_label)
        # Write the new store labels into col B
        label_updates = []
        for offset, (k, _v) in enumerate(new_stores):
            disp = k.title().replace("Sams", "Sams")  # 'sams 6265' -> 'Sams 6265'
            label_updates.append({
                "range": gspread.utils.rowcol_to_a1(insert_at_0 + offset + 1, 2),
                "values": [[disp]]})
        rfill._retry(ws.batch_update, label_updates, value_input_option="USER_ENTERED")
        grid = rfill._retry(ws.get_all_values)
        # Rebuild existing list to include the new rows
        existing = []
        for ri, row in enumerate(grid):
            key = _normalize_je_store((row[1] if len(row) > 1 else "").strip())
            if key is not None:
                existing.append((ri, key, (row[1] or "").strip()))

    updates: List[Dict] = []
    written_keys = set()
    for ri, key, label in existing:
        val = by_store.get(key, 0)
        a1 = gspread.utils.rowcol_to_a1(ri + 1, week_col + 1)
        updates.append({"range": a1, "values": [[str(val)]]})
        written_keys.add(key)
        log.append(f"  {a1} {label!r} <- {val}")

    # Total Sales = sum of all stores; Total Store Count = # with >0.
    total_sales = sum(by_store.values())
    store_count = sum(1 for v in by_store.values() if v > 0)
    ts_row = _find_row_by_label(grid, "Total Sales")
    tsc_row = _find_row_by_label(grid, "Total Store Count")
    if ts_row is not None:
        a1 = gspread.utils.rowcol_to_a1(ts_row + 1, week_col + 1)
        updates.append({"range": a1, "values": [[str(total_sales)]]})
        log.append(f"  {a1} Total Sales <- {total_sales}")
    if tsc_row is not None:
        a1 = gspread.utils.rowcol_to_a1(tsc_row + 1, week_col + 1)
        updates.append({"range": a1, "values": [[str(store_count)]]})
        log.append(f"  {a1} Total Store Count <- {store_count}")
    # AVG Sales per Store = sheet formula (Total Sales / Store Count),
    # cells referenced by their looked-up positions (not hardcoded).
    aps_row = _find_row_by_label(grid, "AVG Sales per Store")
    if aps_row is not None and ts_row is not None and tsc_row is not None:
        col_a1 = gspread.utils.rowcol_to_a1(1, week_col + 1).rstrip("1")
        ts_ref = f"{col_a1}{ts_row + 1}"
        tsc_ref = f"{col_a1}{tsc_row + 1}"
        formula = f"=IFERROR({ts_ref}/{tsc_ref},0)"
        a1 = gspread.utils.rowcol_to_a1(aps_row + 1, week_col + 1)
        updates.append({"range": a1, "values": [[formula]]})
        log.append(f"  {a1} AVG Sales per Store <- {formula}")

    # Conversion / Personal Production / Direct Deposit (from the other
    # views). Each written only if we got a value.
    for label, val in (("Conversion", conversion),
                       ("Personal Production", personal_production),
                       ("Direct Deposit", direct_deposit)):
        if val is None:
            continue
        row = _find_row_by_label(grid, label)
        if row is None:
            log.append(f"  [miss-row] no '{label}' row")
            continue
        a1 = gspread.utils.rowcol_to_a1(row + 1, week_col + 1)
        updates.append({"range": a1, "values": [[str(val)]]})
        log.append(f"  {a1} {label} <- {val}")

    if dry_run:
        return [f"[DRY-RUN je] {ws.title}: would write {len(updates)} cells"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        return [f"[OK je] {ws.title}: wrote {len(updates)} cells"] + log
    return [f"[skip-je] {ws.title}: nothing to write"]


def run_je_opt(dry_run: bool = False, only_rep: Optional[str] = None,
               logfn=print) -> dict:
    """Pull JE sales-by-store for each ' - JE' tab + fill it. Conversion +
    Personal Production are a follow-up (separate tracker)."""
    errors: List[str] = []
    week_end = _current_target_week_end()
    week_col_label = _current_target_week_col_label()
    logfn(f"OPT JE: target week = {week_col_label!r} (ending {week_end})")

    client = rfill._client()
    sh = client.open_by_key(ALPHALETE_ORG_SHEET_ID)
    resp = sh.client.request(
        "get", f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
        params={"fields": "sheets(properties(title,hidden))"})
    hidden = {s["properties"]["title"] for s in resp.json().get("sheets", [])
              if s["properties"].get("hidden")}

    filled, skipped = [], []
    for ws in rfill._retry(sh.worksheets):
        title = ws.title
        if not title.endswith(" - JE") or title in hidden or title.startswith("x"):
            continue
        rep_name = title[: -len(" - JE")].strip()
        if only_rep and only_rep.lower() not in rep_name.lower():
            continue
        icd_name = rep_name   # Tableau ICD Name matches the tab's rep name
        icd_norm = _norm_owner(icd_name)

        sales_out = OUTPUT_DIR / JE_SALES_FILENAME
        conv_out = OUTPUT_DIR / JE_CONV_FILENAME
        dd_out = OUTPUT_DIR / JE_DD_FILENAME
        by_store: Dict[str, int] = {}
        conversion = personal_production = direct_deposit = None
        try:
            with tableau_session(verbose=False) as page:
                logfn(f"OPT JE: Crosstab → sales-by-store ({icd_name}, WE {week_end})...")
                download_crosstab_patchright(
                    _je_sales_url(icd_name, week_end), JE_SALES_SHEET,
                    sales_out, verbose=False, page=page)
                by_store = parse_je_sales_by_store(sales_out)

                try:
                    logfn(f"OPT JE: Crosstab → conversion tracker...")
                    download_crosstab_patchright(JE_CONV_URL, JE_CONV_SHEET,
                                                 conv_out, verbose=False, page=page)
                    conversion, personal_production = parse_je_conversion(
                        conv_out, icd_norm)
                except Exception as e:
                    logfn(f"OPT JE: ✗ conversion: {type(e).__name__}: {str(e)[:100]}")

                try:
                    logfn(f"OPT JE: Crosstab → direct deposit...")
                    download_crosstab_patchright(JE_DD_URL, JE_DD_SHEET,
                                                 dd_out, verbose=False, page=page)
                    direct_deposit = parse_je_direct_deposit(dd_out, icd_norm)
                except Exception as e:
                    logfn(f"OPT JE: ✗ direct deposit: {type(e).__name__}: {str(e)[:100]}")
        except Exception as e:
            msg = f"{title}: {type(e).__name__}: {str(e)[:120]}"
            logfn(f"OPT JE: ✗ {msg}")
            errors.append(msg)
            skipped.append(title)
            continue

        logfn(f"OPT JE: parsed {len(by_store)} store(s); conversion={conversion}; "
              f"PP={personal_production}; DD={direct_deposit}")
        for ln in fill_je_tab(ws, by_store, week_col_label, dry_run, logfn,
                              conversion=conversion,
                              personal_production=personal_production,
                              direct_deposit=direct_deposit):
            logfn(f"OPT JE: {ln}")
            if ln.startswith(("[OK", "[DRY-RUN")):
                filled.append(title)

    return {"filled": filled, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="Only this rep (substring match).")
    args = ap.parse_args()
    result = run_je_opt(dry_run=args.dry_run, only_rep=args.only)
    print(f"\nFilled: {len(result['filled'])}; Skipped: {len(result['skipped'])}; "
          f"Errors: {len(result['errors'])}")
    for e in result["errors"]:
        print(f"  ✗ {e}")

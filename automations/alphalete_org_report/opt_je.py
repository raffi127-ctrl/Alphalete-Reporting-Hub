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

Also filled: Conversion + Personal Production (6WkConversionTracker, over the
.csv endpoint) and Direct Deposit (PROGRAM SUMMARY / DOWNLINE VIEW).

Manual / formula / future (NOT written here):
  - AVG Sales per Leader = Total Sales / Leaders (Leaders is manual) — formula
  - Total Funds Available .. Profit/Loss — the financial_report upload flow

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
    match_dd_owner,
    _read_tab_csv,
    _norm_owner,
    _find_week_col,
    _find_row_by_label,
    _current_target_week_col_label,
    _current_target_week_end,
)
from automations.alphalete_org_report.tableau_http import (
    download_view_csv,
    parse_csv as parse_view_csv,
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

# Direct Deposit — PROGRAM SUMMARY / DOWNLINE VIEW, the source Eve pointed at
# 2026-07-28 ("Program summary - Downline Filter"). Replaces the org-wide
# DD BY OWNER (ORG) crosstab (opt_nds.ORG_DD_URL), whose 'Sheet 7 (5)' stopped
# appearing in the Crosstab dialog that day — the dialog offers only
# 'Consultant ORG Titl…', so every JE DD pull came back empty.
#
# Two wins over the old source:
#   - it PINS THE WEEK ('Processed Week' = that week's Monday), so DD
#     back-fills like the rest of the JE section instead of being
#     current-week-only;
#   - its per-ICD table is the same one a human reads off the dashboard.
# Verified 2026-07-28 against the DD Eve typed in by hand: Brandon
# 6550 / 3891 / 3360 for WE 07-26 / 07-19 / 07-12, and no row at all for
# WE 07-05 (which is why that cell is legitimately blank).
JE_DD_VIEWDATA_FILENAME = "opt_je_program_summary.tsv"

# Fractional (x, y) inside the viz iframe to click so 'Download -> Data'
# targets the ORGANIZATION (downline) table — the dashboard's TOP table is a
# 1-row owner summary, and scraping that is how this silently returned just
# 'Rafael Hidalgo'. Measured 2026-07-28: iframe box y=38 h=909 at a 1664x949
# window, downline header row at page y≈529 -> (529-38)/909 ≈ 0.539.
# Tried in order and the first scrape that returns a real grid wins, so a
# layout shift costs a retry instead of a silent 1-row result. 0.47 is
# opt_phase's current constant — it lands on the FILTER row here, so it is
# last, not first.
JE_DD_XY_CANDIDATES = ((0.033, 0.539), (0.033, 0.560), (0.05, 0.47))
JE_DD_MIN_ROWS = 5   # a real downline grid is ~76-86 rows; 1 = wrong worksheet


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

# Same tracker over Tableau's .csv endpoint (tableau_http). PREFERRED source
# as of 2026-07-28: the Crosstab dialog stopped listing the
# '6 Week Tracker by ICD & Rep' sheet ("saw 0 thumb(s)"), which left
# Conversion blank on every JE tab from WE 07-19 on. The .csv endpoint
# skips the dialog entirely AND honors 'Sales Weekending' as a filter, so
# it pins the exact week instead of averaging whatever window the
# dashboard happens to show. Long format:
#   Measure Names | Owner Name_ | Rep Name | Sales Weekending | Measure Values
# The UI crosstab stays as the fallback.
JE_CONV_WORKBOOK = "6WkConversionTracker"
JE_CONV_VIEW = "6WeekTrackerbyRep"
JE_CONV_HTTP_FILENAME = "opt_je_conversion_http.csv"


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


def download_je_direct_deposit(week_end: dt.date, page, logfn=print
                               ) -> Dict[str, float]:
    """Scrape PROGRAM SUMMARY / DOWNLINE VIEW for `week_end`'s week and return
    {normalized ICD owner: dollars}.

    The per-ICD table won't crosstab-export, so this goes through Tableau's
    Download -> Data window (opt_phase.scrape_view_data), clicking into the
    downline worksheet first. Sweeps JE_DD_XY_CANDIDATES and keeps the first
    result that looks like the real grid — a 1-row return means the click
    landed on the owner-summary table above it, which is a silent wrong
    answer, not an error. Returns {} if no candidate produces a grid.
    """
    from automations.recruiting_report.opt_phase import (
        _program_summary_url, parse_program_summary, scrape_view_data)

    url = _program_summary_url(week_end)
    out = OUTPUT_DIR / JE_DD_VIEWDATA_FILENAME
    for xy in JE_DD_XY_CANDIDATES:
        try:
            fields, records = scrape_view_data(url, verbose=False, page=page,
                                               activate_xy=xy)
        except Exception as e:
            logfn(f"OPT JE: DD scrape at {xy} failed: "
                  f"{type(e).__name__}: {str(e)[:80]}")
            continue
        if len(records) < JE_DD_MIN_ROWS:
            logfn(f"OPT JE: DD scrape at {xy} returned {len(records)} row(s) "
                  f"— wrong worksheet, trying the next click point")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(["\t".join(fields)]
                                 + ["\t".join(r) for r in records]),
                       encoding="utf-8")
        ps = parse_program_summary(out)
        logfn(f"OPT JE: DD — {len(records)} rows, {len(ps)} ICD owners "
              f"(click {xy})")
        return {k: v["total"] for k, v in ps.items()}
    logfn("OPT JE: ✗ direct deposit: no click point produced the downline grid")
    return {}


def parse_je_conversion_http(path: Path, icd_norm: str
                             ) -> Tuple[Optional[str], Optional[str]]:
    """Parse the tracker's .csv export (long format, already filtered to one
    'Sales Weekending' by the URL param) → (office_avg_conversion,
    icd_own_total_sales), both scoped to this ICD.

    Rows: Measure Names | Owner Name_ | Rep Name | Sales Weekending |
    Measure Values. Conversion values come back as fractions ('0.8'); a
    '%'-suffixed value is taken as already-scaled. Returns (None, None)
    when the ICD has no row for the week — the caller then leaves the cell
    alone rather than writing another week's number.
    """
    rows = parse_view_csv(path)
    if len(rows) < 2:
        return None, None
    hdr = [(c or "").strip().lower() for c in rows[0]]
    try:
        i_meas, i_owner, i_rep, i_val = (hdr.index("measure names"),
                                         hdr.index("owner name_"),
                                         hdr.index("rep name"),
                                         hdr.index("measure values"))
    except ValueError:
        return None, None

    conv_vals: List[float] = []
    own_sales: Optional[str] = None
    for r in rows[1:]:
        if len(r) <= max(i_meas, i_owner, i_rep, i_val):
            continue
        if _norm_owner(r[i_owner]) != icd_norm:
            continue
        measure = (r[i_meas] or "").strip().lower()
        raw = (r[i_val] or "").strip()
        if measure.startswith("conversion"):
            if raw.endswith("%"):
                v = _parse_pct(raw)
            else:
                try:
                    v = float(raw) * 100
                except ValueError:
                    v = None
            if v is not None:
                conv_vals.append(v)
        elif measure == "total sales" and _norm_owner(r[i_rep]) == icd_norm:
            own_sales = raw
    office_avg = f"{round(sum(conv_vals) / len(conv_vals))}%" if conv_vals else None
    return office_avg, own_sales


def _parse_tracker_date(s: str) -> Optional[dt.date]:
    """'5/10/2026' (the tracker's week-ending header) → date."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_je_conversion(path: Path, icd_norm: str,
                        week_end: Optional[dt.date] = None
                        ) -> Tuple[Optional[str], Optional[str]]:
    """Parse '6 Week Tracker by ICD & Rep' → (office_avg_conversion,
    icd_own_total_sales).

    Layout: row0 groups (Conversion % ×N, Total Sales ×N, Total Installs ×N),
    row1 = Owner | Rep | <week-ending date per group column>, then one row
    per rep.

    Scoped BOTH ways (2026-07-28, when Brandon Stallkamp became the 2nd JE
    ICD — before that the office avg silently mixed every owner in the
    tracker):
      - by OWNER: only rows whose col-0 Owner Name matches this ICD count.
      - by WEEK: only the group column whose header date == `week_end`.
        Returns (None, None) when the tracker's rolling window no longer
        shows that week — better a blank cell than another week's number in
        a back-filled column. Pass week_end=None for the legacy behavior
        (average across every week shown).
    """
    rows = _read_tab_csv(path)
    if len(rows) < 3:
        return None, None
    groups = rows[0]
    headers = rows[1] if len(rows) > 1 else []

    def _cols(group_name: str) -> List[int]:
        out = [i for i, g in enumerate(groups)
               if (g or "").strip().lower().startswith(group_name)]
        if week_end is None:
            return out
        return [i for i in out
                if i < len(headers) and _parse_tracker_date(headers[i]) == week_end]

    conv_cols = _cols("conversion")
    sales_cols = _cols("total sales")
    if week_end is not None and not conv_cols and not sales_cols:
        return None, None

    conv_vals: List[float] = []
    own_sales: Optional[str] = None
    for r in rows[2:]:
        if len(r) < 2:
            continue
        if _norm_owner(r[0]) != icd_norm:
            continue
        for c in conv_cols:
            v = _parse_pct(r[c]) if c < len(r) else None
            if v is not None:
                conv_vals.append(v)
        if _norm_owner(r[1]) == icd_norm:
            vals = [r[c].strip() for c in sales_cols
                    if c < len(r) and (r[c] or "").strip()]
            if vals:
                own_sales = vals[-1]   # target week (or latest shown)
    office_avg = f"{round(sum(conv_vals) / len(conv_vals))}%" if conv_vals else None
    return office_avg, own_sales


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

    # New stores with production not yet on the sheet → give them a col-B row.
    new_stores = sorted(
        ((k, v) for k, v in by_store.items() if v > 0 and k not in existing_keys),
        key=lambda kv: kv[0],
    )
    if new_stores and not dry_run:
        if existing:
            # Established tab — the store block already exists, extend it.
            insert_at_0 = max(r for r, _, _ in existing) + 1
        else:
            # Brand-new tab (no store rows yet): the block starts right below
            # 'AVG Sales per Store', which is the last row of the totals
            # block on the JE template. Anchor by label, never by index.
            anchor = _find_row_by_label(grid, "AVG Sales per Store")
            if anchor is None:
                anchor = _find_row_by_label(grid, "Total Store Count")
            if anchor is None:
                return [f"[skip-je] {ws.title}: no 'AVG Sales per Store' row "
                        f"to anchor the store block"]
            insert_at_0 = anchor + 1
        # Reuse the blank rows already sitting under the anchor before
        # inserting new ones — the template ships a run of empty rows there,
        # and inserting on top of them would leave a gap. Never overwrite a
        # row that already has a col-B label.
        free = 0
        while (insert_at_0 + free < len(grid)
               and not (grid[insert_at_0 + free][1:2] or [""])[0].strip()):
            free += 1
        need = max(0, len(new_stores) - free)
        if need:
            rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
                "insertDimension": {
                    "range": {"sheetId": ws.id, "dimension": "ROWS",
                              "startIndex": insert_at_0 + free,
                              "endIndex": insert_at_0 + free + need},
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
               logfn=print, week: Optional[dt.date] = None) -> dict:
    """Pull JE sales-by-store for each ' - JE' tab + fill it.

    `week` back-fills a past WE Sunday instead of the current target week.
    JE is the one campaign where the WHOLE section back-fills — every source
    is week-pinnable:
      - sales-by-store  → 'Sales Week Ending' URL param
      - conversion      → 'Sales Weekending' on the .csv endpoint
      - direct deposit  → 'Processed Week' on PROGRAM SUMMARY / DOWNLINE VIEW
    (DD was current-week-only until 2026-07-28, when it moved off the
    org-wide DD BY OWNER crosstab — see JE_DD_XY_CANDIDATES above.)
    """
    errors: List[str] = []
    week_end = week or _current_target_week_end()
    week_col_label = f"{week_end.month}/{week_end.day}/{week_end.year % 100}"
    logfn(f"OPT JE: target week = {week_col_label!r} (ending {week_end})")

    client = rfill._client()
    sh = rfill.open_by_key(ALPHALETE_ORG_SHEET_ID, client)
    resp = sh.client.request(
        "get", f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
        params={"fields": "sheets(properties(title,hidden))"})
    hidden = {s["properties"]["title"] for s in resp.json().get("sheets", [])
              if s["properties"].get("hidden")}

    # Conversion tracker — ONE download for the whole run, BEFORE any
    # patchright session opens. tableau_http grabs its cookies with the
    # Playwright sync API, which raises "Sync API inside the asyncio loop"
    # if a tableau_session is already live. The .csv is week-filtered and
    # carries every owner, so each tab just parses its own rows out of it.
    conv_http_path: Optional[Path] = None
    try:
        logfn(f"OPT JE: HTTP → conversion tracker (WE {week_end})...")
        conv_http_path = download_view_csv(
            JE_CONV_WORKBOOK, JE_CONV_VIEW,
            OUTPUT_DIR / JE_CONV_HTTP_FILENAME,
            params={"Sales Weekending": week_end.isoformat()})
    except Exception as e:
        logfn(f"OPT JE: ✗ conversion (HTTP): {type(e).__name__}: {str(e)[:100]} "
              f"— falling back to the Crosstab dialog")

    # Direct Deposit — also ONE scrape per run, shared by every tab. It needs
    # a live patchright page, so it happens inside the first tab's session and
    # is cached here. None = not attempted yet.
    dd_by_owner: Optional[Dict[str, float]] = None

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
        by_store: Dict[str, int] = {}
        conversion = personal_production = direct_deposit = None
        try:
            with tableau_session(verbose=False) as page:
                logfn(f"OPT JE: Crosstab → sales-by-store ({icd_name}, WE {week_end})...")
                download_crosstab_patchright(
                    _je_sales_url(icd_name, week_end), JE_SALES_SHEET,
                    sales_out, verbose=False, page=page)
                by_store = parse_je_sales_by_store(sales_out)

                if conv_http_path is not None:
                    conversion, personal_production = parse_je_conversion_http(
                        conv_http_path, icd_norm)
                    if conversion is None:
                        logfn(f"OPT JE: conversion: {icd_name} has no row for "
                              f"WE {week_end} in the tracker")
                else:
                    try:
                        logfn(f"OPT JE: Crosstab → conversion tracker (fallback)...")
                        download_crosstab_patchright(JE_CONV_URL, JE_CONV_SHEET,
                                                     conv_out, verbose=False, page=page)
                        conversion, personal_production = parse_je_conversion(
                            conv_out, icd_norm, week_end)
                    except Exception as e2:
                        logfn(f"OPT JE: ✗ conversion: {type(e2).__name__}: {str(e2)[:100]}")

                if dd_by_owner is None:
                    logfn(f"OPT JE: View Data → direct deposit "
                          f"(PROGRAM SUMMARY / DOWNLINE, WE {week_end})...")
                    dd_by_owner = download_je_direct_deposit(week_end, page, logfn)
                dd_v = match_dd_owner(dd_by_owner, icd_name)
                direct_deposit = f"${dd_v:,.2f}" if dd_v is not None else None
                if direct_deposit is None and dd_by_owner:
                    logfn(f"OPT JE: DD — no row for {icd_name} in WE {week_end} "
                          f"(leaving the cell as-is)")
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
    ap.add_argument("--week", help="Back-fill this WE Sunday (YYYY-MM-DD) "
                                   "instead of the current target week.")
    args = ap.parse_args()
    week = dt.date.fromisoformat(args.week) if args.week else None
    result = run_je_opt(dry_run=args.dry_run, only_rep=args.only, week=week)
    print(f"\nFilled: {len(result['filled'])}; Skipped: {len(result['skipped'])}; "
          f"Errors: {len(result['errors'])}")
    for e in result["errors"]:
        print(f"  ✗ {e}")

"""Step 5: scrape Time Tracker for ONE owner across the current week
(Mon → today) and fill their Sheet tab.

Behavior:
  - For each weekday Mon..today: scrape Time Tracker for that date
  - Match each scraped rep to a row in the owner's Sheet tab (looked up
    via the "Rep Name" header — never assume col B / col A)
  - Add new rows for reps not yet in the Sheet
  - Never delete existing reps (terminated rep keeps prior days' data)
  - Only WRITE to currently-empty cells (idempotent — re-runs are safe)
  - After all writes: sort rep rows alphabetically + extend bold border

All column positions are resolved dynamically from row 1 (day labels)
and row 2 (metric headers) at runtime — see columns.py. If a header is
missing or renamed, the resolver prompts before any writes happen.

Prereq: session is already impersonating the target owner (run step1+2
first). Defaults to Cody Cannon → tab "Cody Cannon".

Run:
  .venv/bin/python -m automations.focus_office_att.step5_fill_one_owner
  .venv/bin/python -m automations.focus_office_att.step5_fill_one_owner --owner-tab "Cody Cannon"
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.apply_data_border import apply_bold_border
from automations.focus_office_att.autosize_rep_col import autosize_all_data_cols
from automations.focus_office_att.auto_collapse import update_collapse_states
from automations.focus_office_att.columns import resolve_layout, Layout

CDP_URL = "http://localhost:9222"
DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"
TIME_TRACKER_PAGE = "p=510"
DISPOSITION_PAGE = "p=89"

# Source-table column indices (Time Tracker)
SRC_NAME = 1
SRC_FIRST_KNOCK = 2
SRC_LAST_KNOCK = 3
SRC_GAPS = 5
SRC_TOTAL_GAPS = 6

# Source-table column indices (Disposition by Rep, 0-indexed). Columns
# match the ownerville Disposition page header order. The header probe
# is the source of truth — if these break, re-run probe and update.
DISP_NAME = 1
DISP_TALK_TO_NI = 5          # "Talk To - Not Interested"
DISP_PRES_NI = 6             # "Presentation – Not Interested"
DISP_COMEBACK = 7            # "Come Back"
DISP_SALE = 8                # "Sale"
DISP_TOTAL_LEADS_KNOCKED = 11

# Scraped-field → canonical-metric mapping. The actual column for each
# canonical metric is resolved at runtime from the Sheet headers — see
# columns.py — never hard-coded here.
TT_FIELD_TO_CANONICAL = {
    "first_knock": "First Knock",
    "last_knock":  "Last Knock Date",
    "gaps":        "# of gaps",
    "total_gaps":  "total gap time",
}
DISP_FIELD_TO_CANONICAL = {
    "total_leads_knocked": "Total Leads Knocked",
    "talk_tos":            "Talk To's",
    "presentations":       "Presentations",
}


def _a1(col: int, row: int) -> str:
    s, n = "", col
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return f"{s}{row}"


def _col_letter(col: int) -> str:
    s, n = "", col
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_gap_time(s) -> "Optional[float]":
    """Parse 'Xh Ym' / 'Xm' / 'Xh' / '0m' into fractional days (Sheets time
    value: 1.0 = 24 hours). Returns None for empty/unparseable input.

    Why fractional days: Sheets' built-in time number formats — including
    [h]"h" mm"m" — expect time values in this representation. Storing
    gap time this way lets =AVERAGE() work directly across day cells.
    """
    import re
    if s is None:
        return None
    text = str(s).strip().lower()
    if not text:
        return None
    h_match = re.search(r"(\d+)\s*h", text)
    m_match = re.search(r"(\d+)\s*m", text)
    if not h_match and not m_match:
        return None
    hours = int(h_match.group(1)) if h_match else 0
    mins  = int(m_match.group(1)) if m_match else 0
    total_minutes = hours * 60 + mins
    return total_minutes / 1440.0   # 1440 = 24 * 60


# ---- Time Tracker scraping ----
def _set_date_and_pagesize(page, target_mdy: str) -> None:
    """Set the date picker, swallow the navigation it triggers, then set Show 100."""
    try:
        page.evaluate(
            """(targetDate) => {
                const el = $('#datepicker');
                if (el.datepicker && typeof el.datepicker === 'function') {
                    try { el.datepicker('setDate', targetDate); } catch(e) {}
                }
                el.val(targetDate).trigger('change').trigger('blur');
            }""",
            target_mdy,
        )
    except Exception as e:
        if "context was destroyed" not in str(e).lower():
            raise
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    try:
        page.locator("select[name='timeTrackingTable_length']").select_option("100")
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


def _scrape_current_view(page) -> list[dict]:
    table = page.locator("table#timeTrackingTable")
    page.wait_for_function(
        "() => document.querySelectorAll('#timeTrackingTable tbody tr').length >= 1",
        timeout=10000,
    )
    out = []
    page_num = 1
    while page_num <= 20:
        for tr in table.locator("tbody tr").all():
            try:
                cells = tr.locator("td").all()
                if len(cells) < 7:
                    continue
                if cells[0].inner_text().strip().lower().startswith("no data"):
                    continue
                out.append({
                    "name": cells[SRC_NAME].inner_text().strip(),
                    "first_knock": cells[SRC_FIRST_KNOCK].inner_text().strip(),
                    "last_knock": cells[SRC_LAST_KNOCK].inner_text().strip(),
                    "gaps": cells[SRC_GAPS].inner_text().strip(),
                    "total_gaps": cells[SRC_TOTAL_GAPS].inner_text().strip().split("\n")[0],
                })
            except Exception:
                continue
        # Check pagination
        next_btn = page.locator("#timeTrackingTable_next").first
        if next_btn.count() == 0 or "disabled" in (next_btn.get_attribute("class") or ""):
            break
        next_btn.click()
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page_num += 1
    return out


# ---- Disposition by Rep scraping ----
def _navigate_to_disposition_for_date(page, rqst: str, target_mdy: str) -> None:
    """Navigate to Disposition by Rep for a single date.

    The page filters via URL query params (?startDate=MM/DD/YYYY
    &endDate=MM/DD/YYYY) — the on-page daterangepicker just sets local JS
    vars, while the actual table is fetched server-side based on the URL.
    Cleaner + more reliable than synthesizing daterangepicker events.
    """
    url = (
        f"https://v2.ownerville.com/index.cfm?p=89&rqst={rqst}"
        f"&startDate={target_mdy}&endDate={target_mdy}"
    )
    page.goto(url, wait_until="networkidle", timeout=25000)
    try:
        page.locator("select[name='table-dispositions_length']").select_option("100")
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


def _to_int(s: str) -> int:
    """Parse Disposition cell as int; empty/non-numeric → 0."""
    s = (s or "").strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _scrape_disposition_view(page) -> list[dict]:
    table = page.locator("table#table-dispositions")
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#table-dispositions tbody tr').length >= 1",
            timeout=10000,
        )
    except Exception:
        return []  # no rows for this day
    out = []
    page_num = 1
    while page_num <= 20:
        for tr in table.locator("tbody tr").all():
            try:
                cells = tr.locator("td").all()
                if len(cells) < 12:
                    continue
                first_text = cells[0].inner_text().strip().lower()
                if first_text.startswith("no data"):
                    continue
                tt_ni    = _to_int(cells[DISP_TALK_TO_NI].inner_text())
                pres_ni  = _to_int(cells[DISP_PRES_NI].inner_text())
                comeback = _to_int(cells[DISP_COMEBACK].inner_text())
                sale     = _to_int(cells[DISP_SALE].inner_text())
                tlk      = _to_int(cells[DISP_TOTAL_LEADS_KNOCKED].inner_text())
                out.append({
                    "name": cells[DISP_NAME].inner_text().strip(),
                    "total_leads_knocked": tlk,
                    "talk_tos":            tt_ni + pres_ni + comeback + sale,
                    "presentations":       pres_ni + sale,
                })
            except Exception:
                continue
        next_btn = page.locator("#table-dispositions_next").first
        if next_btn.count() == 0 or "disabled" in (next_btn.get_attribute("class") or ""):
            break
        next_btn.click()
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page_num += 1
    return out


def scrape_disposition_day(page, target_date: dt.date, rqst: str) -> list[dict]:
    """Scrape Disposition by Rep for a single date. Returns list of rep dicts."""
    _navigate_to_disposition_for_date(page, rqst, target_date.strftime("%m/%d/%Y"))
    return _scrape_disposition_view(page)


def scrape_day(page, target_date: dt.date) -> list[dict]:
    """Scrape Time Tracker for a single date. Returns list of rep dicts."""
    target_mdy = target_date.strftime("%m/%d/%Y")
    _set_date_and_pagesize(page, target_mdy)
    return _scrape_current_view(page)


# ---- Sheet write logic ----
def _merge_rep_records(*records: dict) -> dict:
    """Combine multiple per-source dicts for the same rep+date into one.
    Later sources do NOT overwrite earlier ones — fields are additive."""
    out: dict = {}
    for r in records:
        for k, v in r.items():
            if k not in out or out[k] in ("", None):
                out[k] = v
    return out


def fill_owner_tab(ws, scraped_by_date: dict, layout: Layout) -> dict:
    """Write scraped data into the owner's tab. scraped_by_date is
    {date: [rep_dict, ...]}, where rep_dict can carry any of the Time
    Tracker or Disposition fields. Returns a stats dict for logging.
    Uses `layout` to resolve column positions — never assumes anything."""
    rep_col = layout.rep_name_col

    # Build a {rep_name_lower: row} map from existing data. Strip the
    # Tableau-only marker emoji when keying so 'Joe Smith 🔹' (added by
    # Phase 3 last week) matches the 'Joe Smith' ownerville returns now.
    rep_col_values = ws.col_values(rep_col)
    name_to_row = {}
    for i, name in enumerate(rep_col_values, start=1):
        if i < 3 or not name.strip():
            continue
        key = strip_rep_mark(name).lower().strip()
        if key:
            name_to_row[key] = i

    # Determine right edge for the existing-data probe (rightmost resolved col).
    all_cols = [c for day_map in layout.day_cols.values() for c in day_map.values()] + [rep_col]
    last_data_col = max(all_cols) if all_cols else rep_col

    # Pull existing values for the entire data range so we can check
    # idempotency (don't overwrite cells that already have data).
    existing = {}  # (row, col) → value
    if name_to_row:
        last_existing_row = max(name_to_row.values())
        rng = f"A3:{_col_letter(last_data_col)}{last_existing_row}"
        try:
            grid = ws.get(rng)
            for r_offset, row_vals in enumerate(grid):
                row_idx = 3 + r_offset
                for c_offset, val in enumerate(row_vals):
                    if val.strip():
                        existing[(row_idx, c_offset + 1)] = val
        except Exception:
            pass

    cells_to_write = []  # list of (a1, value) — counted at return time
    new_reps = []
    new_rep_rows: list[int] = []   # rows that need formatting copied from row 3
    skipped_cells = 0

    for date, reps in scraped_by_date.items():
        weekday_idx = date.weekday()
        if weekday_idx not in layout.day_cols:
            continue
        wd_cols = layout.day_cols[weekday_idx]
        for rep in reps:
            rep_name = rep["name"].strip()
            if not rep_name:
                continue
            key = rep_name.lower()
            if key in name_to_row:
                row = name_to_row[key]
            else:
                # New rep — assign next available row. On an empty tab
                # (no existing reps), the FIRST rep belongs at row 3
                # (right under row 2 headers). After that, append below
                # the highest existing rep row.
                row = (max(name_to_row.values()) + 1) if name_to_row else 3
                name_to_row[key] = row
                new_reps.append(rep_name)
                new_rep_rows.append(row)
                cells_to_write.append((_a1(rep_col, row), rep_name))

            # Write each canonical field if present in the rep dict and
            # the destination cell is currently empty.
            field_map = {**TT_FIELD_TO_CANONICAL, **DISP_FIELD_TO_CANONICAL}
            for field, canonical in field_map.items():
                if field not in rep:
                    continue  # this source didn't produce that field
                col = wd_cols.get(canonical)
                if col is None:
                    continue  # metric skipped during layout resolution
                if (row, col) in existing:
                    skipped_cells += 1
                    continue
                value = rep[field]
                # Treat 0 from Disposition as a real value (write it).
                # Empty string / None / "" → skip (no data to write).
                if value is None or value == "":
                    continue
                # Total Gap Time: convert "Xh Ym" / "0m" text into fractional
                # days so the cell is a real time value (sortable, averageable).
                # Display formatting is handled separately via apply_gap_time_format().
                if field == "total_gaps":
                    parsed = parse_gap_time(value)
                    if parsed is None:
                        continue
                    value = parsed
                # Numbers go through as numbers; strings as strings. Sheets'
                # USER_ENTERED option parses string inputs (e.g. "2:30 PM" → time).
                out_value = value if isinstance(value, (int, float)) else str(value)
                cells_to_write.append((_a1(col, row), out_value))
                existing[(row, col)] = value

    # Batch-update all cells at once (much faster than cell-by-cell)
    if cells_to_write:
        data = [{"range": f"'{ws.title}'!{a1}", "values": [[v]]} for a1, v in cells_to_write]
        ws.spreadsheet.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})

    # Copy formatting from row 3 (known-good rep row) onto any newly-added
    # rep rows so they match the rest visually. Without this, new rows
    # keep whatever scratch formatting they had before (often inconsistent
    # with sibling rep rows: missing bg color, alignment, etc.).
    if new_rep_rows:
        requests = []
        for r in new_rep_rows:
            requests.append({
                "copyPaste": {
                    "source": {
                        "sheetId": ws.id,
                        "startRowIndex": 2, "endRowIndex": 3,
                        "startColumnIndex": 0, "endColumnIndex": last_data_col,
                    },
                    "destination": {
                        "sheetId": ws.id,
                        "startRowIndex": r - 1, "endRowIndex": r,
                        "startColumnIndex": 0, "endColumnIndex": last_data_col,
                    },
                    "pasteType": "PASTE_FORMAT",
                    "pasteOrientation": "NORMAL",
                },
            })
        ws.spreadsheet.batch_update({"requests": requests})

    return {
        "new_reps": new_reps,
        "skipped_cells": skipped_cells,
        "written_cells": len(cells_to_write),
    }


# Mapping from Weekly Total block header → canonical per-day metric name.
# The Weekly Total block (cols 2-12) uses SUM/AVG-prefixed headers so the
# aggregation type is visible in the Sheet itself. This dict bridges those
# Weekly headers to the matching per-day canonical metrics.
WEEKLY_TO_PERDAY = {
    "SUM Total Apps":      "Total Apps",
    "SUM Doors Knocked":   "Total Leads Knocked",
    "AVG 1st Knock":       "First Knock",
    "AVG Last Knock":      "Last Knock Date",
    "AVG # Of Gaps":       "# of gaps",
    "AVG Total Gap Time":  "total gap time",
    "SUM New INT":         "New INT",
    "SUM Upgrades":        "Upgrades",
    "SUM DTV":             "DTV",
    "SUM New Lines":       "New Lines",
}
WEEKLY_SUM_METRICS = {
    "SUM Total Apps", "SUM Doors Knocked",
    "SUM New INT", "SUM Upgrades", "SUM DTV", "SUM New Lines",
}
WEEKLY_SALE_METRICS = ["New INT", "Upgrades", "DTV", "New Lines"]  # used for Total Apps roll-up


def _find_weekly_cols(ws) -> dict:
    """Return {weekly_header: 1-based col} by scanning row 2 cols 1..12."""
    from automations.focus_office_att.columns import _normalize
    row2 = ws.row_values(2)
    out = {}
    for col_idx, text in enumerate(row2[:12], start=1):
        norm = _normalize(text)
        for key in WEEKLY_TO_PERDAY:
            if norm == _normalize(key):
                out[key] = col_idx
                break
    return out


def write_weekly_formulas(ws, layout: Layout) -> int:
    """Write SUM/AVERAGE formulas into every Weekly Total cell for every
    rep row. Idempotent — overwrites with the same formula every time, so
    re-runs are cheap and harmless.

    Returns the count of cells written.
    """
    weekly_cols = _find_weekly_cols(ws)
    if not weekly_cols:
        return 0

    rep_col_vals = ws.col_values(layout.rep_name_col)
    rep_rows = [i for i, v in enumerate(rep_col_vals, start=1) if i >= 3 and v.strip()]
    if not rep_rows:
        return 0

    data = []
    for r in rep_rows:
        for weekly_canonical, weekly_col in weekly_cols.items():
            if weekly_canonical == "SUM Total Apps":
                # Weekly Total Apps = SUM of the 7 per-day Total Apps cells
                # (each itself =SUM(NIN, Up, DTV, NL) for that day).
                cells = []
                for wd in sorted(layout.day_cols.keys()):
                    c = layout.day_cols[wd].get("Total Apps")
                    if c:
                        cells.append(f"{_col_letter(c)}{r}")
                if not cells:
                    continue
                formula = f"=SUM({','.join(cells)})"
            else:
                perday = WEEKLY_TO_PERDAY[weekly_canonical]
                cells = []
                for wd in sorted(layout.day_cols.keys()):
                    c = layout.day_cols[wd].get(perday)
                    if c:
                        cells.append(f"{_col_letter(c)}{r}")
                if not cells:
                    continue
                if weekly_canonical in WEEKLY_SUM_METRICS:
                    formula = f"=SUM({','.join(cells)})"
                else:
                    # AVERAGE over all-text source cells (rep had no data
                    # this week — every per-day cell is "x") errors out.
                    # IFERROR returns "x" so the weekly cell visually
                    # matches the per-day "no data" marker instead of
                    # rendering blank.
                    formula = f'=IFERROR(AVERAGE({",".join(cells)}),"x")'
            data.append({
                "range": f"'{ws.title}'!{_col_letter(weekly_col)}{r}",
                "values": [[formula]],
            })

    if data:
        ws.spreadsheet.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})
    return len(data)


def write_per_day_total_apps_formulas(ws, layout: Layout) -> int:
    """Write =SUM(New INT, Upgrades, DTV, New Lines) into each rep's
    per-day Total Apps cell — but ONLY for days that have already
    happened (Mon..today). Future days in the current week get their
    Total Apps cell CLEARED, so an un-worked Saturday doesn't show a
    misleading '0'. Idempotent. Returns the count of cells touched.
    """
    rep_vals = ws.col_values(layout.rep_name_col)
    rep_rows = [
        i for i, v in enumerate(rep_vals, start=1)
        if i >= 3 and v and v.strip() and not _is_summary_label(v)
    ]
    if not rep_rows:
        return 0

    today_wd = dt.date.today().weekday()  # 0=Mon .. 6=Sun
    SALE_METRICS = ("New INT", "Upgrades", "DTV", "New Lines")

    data = []
    for wd in sorted(layout.day_cols.keys()):
        ta_col = layout.day_cols[wd].get("Total Apps")
        if not ta_col:
            continue
        sale_cols = [c for c in (layout.day_cols[wd].get(m) for m in SALE_METRICS) if c]
        is_future = wd > today_wd
        for r in rep_rows:
            if is_future or not sale_cols:
                value = ""  # clear — day hasn't happened (or no sale cols)
            else:
                cells = ",".join(f"{_col_letter(c)}{r}" for c in sale_cols)
                value = f"=SUM({cells})"
            data.append({
                "range": f"'{ws.title}'!{_col_letter(ta_col)}{r}",
                "values": [[value]],
            })
    if data:
        ws.spreadsheet.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})
    return len(data)


# --------------------------------------------------------------------------
# Design helpers — every owner tab's look. Each is idempotent so the daily
# pipeline can re-apply them on every run (see design_cosmetic_ops).
# --------------------------------------------------------------------------
def write_count_column(ws) -> None:
    """Col A: '#' header + a per-row formula that numbers ONLY rep rows.
    The REGEXMATCH guard keeps the OFFICE TOTALS + summary rows un-numbered."""
    ws.update("A2", [["#"]], value_input_option="RAW")
    formula = ('=IF(AND($B{r}<>"",NOT(REGEXMATCH($B{r},'
               '"OFFICE TOTALS|TOTAL REPS|REPS ROLLED|% ON BOARD"))),ROW()-2,"")')
    ws.update("A3:A100", [[formula.format(r=r)] for r in range(3, 101)],
              value_input_option="USER_ENTERED")


def apply_number_formats(ws, layout: Layout) -> None:
    """Time-of-day format on First/Last Knock cols, [h]h mm m on gap-time
    cols, and a 1-decimal number on AVG # Of Gaps — weekly block + every
    per-day block. Col positions resolved from layout, never hardcoded."""
    TIME_FMT = {"type": "TIME", "pattern": "h:mm AM/PM"}
    GAP_FMT = {"type": "TIME", "pattern": '[h]"h" mm"m"'}
    AVG_GAPS_FMT = {"type": "NUMBER", "pattern": "0.0"}
    # Weekly summary cols (fixed): E/F = AVG knocks, G = AVG # Of Gaps, H = AVG Gap Time
    fmt_targets: list[tuple[int, dict]] = [
        (5, TIME_FMT), (6, TIME_FMT), (7, AVG_GAPS_FMT), (8, GAP_FMT),
    ]
    for wd, metric_map in layout.day_cols.items():
        for metric, fmt in (("First Knock", TIME_FMT),
                            ("Last Knock Date", TIME_FMT),
                            ("total gap time", GAP_FMT)):
            c = metric_map.get(metric)
            if c:
                fmt_targets.append((c, fmt))
    requests = []
    for col, fmt in fmt_targets:
        requests.append({
            "repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 2, "endRowIndex": 200,
                          "startColumnIndex": col - 1, "endColumnIndex": col},
                "cell": {"userEnteredFormat": {"numberFormat": fmt}},
                "fields": "userEnteredFormat.numberFormat",
            },
        })
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def apply_bold_center(ws) -> None:
    """Bold + horizontal-center + vertical-middle across the data grid."""
    ws.spreadsheet.batch_update({"requests": [{
        "repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 100,
                      "startColumnIndex": 0, "endColumnIndex": 96},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"bold": True},
            }},
            "fields": ("userEnteredFormat.horizontalAlignment,"
                       "userEnteredFormat.verticalAlignment,"
                       "userEnteredFormat.textFormat.bold"),
        },
    }]})


def apply_day_block_borders(ws, layout: Layout) -> None:
    """Thick black box around each day's 12-col block, spanning the header
    row through the last summary row so reps + OFFICE TOTALS + summary are
    all enclosed."""
    col_b = ws.col_values(2)
    last_row = max((i + 1 for i, v in enumerate(col_b) if v.strip()), default=2)
    THICK = {"style": "SOLID_THICK", "color": {"red": 0, "green": 0, "blue": 0}}
    requests = []
    for wd in sorted(layout.day_cols.keys()):
        ta = layout.day_cols[wd].get("Total Apps")
        if not ta:
            continue
        requests.append({
            "updateBorders": {
                "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": last_row,
                          "startColumnIndex": ta - 1, "endColumnIndex": ta + 11},
                "top": THICK, "bottom": THICK, "left": THICK, "right": THICK,
            },
        })
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def design_cosmetic_ops(ws, layout: Layout) -> list:
    """The single source of truth for an owner tab's full design. Returns
    an ordered list of (label, callable) — both Phase 2 (run_all_owners)
    and Phase 3 (step6) run this same list so a daily run reproduces the
    ENTIRE approved design, not a partial subset. Every op is idempotent."""
    return [
        # alphabetize FIRST — it writes the rep block back as values, so
        # the formula writers below must run after to restore formulas
        # for the new (sorted) row order.
        ("alphabetize_reps",             lambda: alphabetize_reps(ws, layout)),
        ("write_per_day_total_apps_formulas", lambda: write_per_day_total_apps_formulas(ws, layout)),
        ("write_weekly_formulas",        lambda: write_weekly_formulas(ws, layout)),
        ("apply_empty_cell_defaults",    lambda: apply_empty_cell_defaults(ws, layout)),
        ("mark_tableau_only_reps",       lambda: mark_tableau_only_reps(ws, layout)),
        ("write_count_column",           lambda: write_count_column(ws)),
        ("apply_number_formats",         lambda: apply_number_formats(ws, layout)),
        ("apply_gap_time_format",        lambda: apply_gap_time_format(ws, layout)),
        ("apply_bold_center",            lambda: apply_bold_center(ws)),
        ("reset_conditional_formatting", lambda: reset_conditional_formatting(ws)),
        ("write_office_totals_row",      lambda: write_office_totals_row(ws, layout)),
        ("write_office_summary_block",   lambda: write_office_summary_block(ws, layout)),
        ("apply_bold_border",            lambda: apply_bold_border(ws)),
        ("apply_day_block_borders",      lambda: apply_day_block_borders(ws, layout)),
        ("autosize_all_data_cols",       lambda: autosize_all_data_cols(ws)),
        ("update_collapse_states",       lambda: update_collapse_states(ws)),
    ]


def apply_gap_time_format(ws, layout: Layout) -> None:
    """Apply the [h]\"h\" mm\"m\" time format to every per-day Total Gap Time
    col + the Weekly Total Gap Time col. Idempotent — safe to re-run.

    Required because the cells store gap time as fractional days (numbers),
    which would otherwise display as raw decimals (e.g. 0.0986) instead of
    \"2h 22m\".
    """
    # Per-day gap cols (resolved via canonical metric name).
    gap_cols = []
    for wd_map in layout.day_cols.values():
        c = wd_map.get("total gap time")
        if c:
            gap_cols.append(c)

    # Weekly Total Gap Time col: search row 2 (cols 1-12, before any day block).
    row2 = ws.row_values(2)
    from automations.focus_office_att.columns import _normalize
    for col_idx, text in enumerate(row2[:12], start=1):
        if _normalize(text) == "total gap time":
            gap_cols.append(col_idx)
            break

    if not gap_cols:
        return

    requests = []
    for col in gap_cols:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 2, "endRowIndex": 200,
                    "startColumnIndex": col - 1, "endColumnIndex": col,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "TIME", "pattern": '[h]"h" mm"m"'}}},
                "fields": "userEnteredFormat.numberFormat",
            },
        })
    ws.spreadsheet.batch_update({"requests": requests})


def alphabetize_reps(ws, layout: Layout) -> None:
    """Sort rep rows alphabetically by Rep Name — read-sort-write in
    Python rather than the Sheets sortRange API.

    Why not sortRange: it 500s intermittently (then consistently) on
    these heavily-formatted tabs. Reading the rep block, sorting it
    ourselves, and writing it back is reliable.

    Scope:
      - Sorts cols B..CR only. Col A is left alone — its =ROW()-2
        numbering self-adjusts to the new row order.
      - Only rows with an actual rep name are sorted; the OFFICE TOTALS
        + summary rows below are never read or touched. Any blank gaps
        between reps are collapsed.
      - Reads UNFORMATTED so times/gap-times round-trip as serial
        numbers. The per-day Total Apps + weekly cells get written back
        as their evaluated VALUES here — design_cosmetic_ops runs this
        op BEFORE the formula writers, which then restore the formulas
        for the sorted order.
    """
    rep_col_values = ws.col_values(layout.rep_name_col)
    rep_row_idxs = [
        i for i, v in enumerate(rep_col_values, start=1)
        if i >= 3 and v.strip() and not _is_summary_label(v)
    ]
    if len(rep_row_idxs) < 2:
        return  # nothing to sort
    first, last = min(rep_row_idxs), max(rep_row_idxs)
    WIDTH = 95  # cols B..CR

    block = ws.get(f"B{first}:CR{last}", value_render_option="UNFORMATTED_VALUE")
    rows_with_names = []
    for row in block:
        padded = (list(row) + [""] * WIDTH)[:WIDTH]
        if str(padded[0] or "").strip():   # col B = rep name
            rows_with_names.append(padded)
    rows_with_names.sort(
        key=lambda r: strip_rep_mark(str(r[0] or "")).lower().strip()
    )
    # Write back contiguously from `first`; pad with blank rows so any
    # collapsed gaps get cleared.
    total_rows = last - first + 1
    out = rows_with_names[:total_rows]
    out += [[""] * WIDTH for _ in range(total_rows - len(out))]
    ws.update(f"B{first}:CR{last}", out, value_input_option="RAW")


_PRODUCTION_METRICS = {"new int", "upgrades", "dtv", "new lines"}
_ACTIVITY_METRICS = {
    "total leads knocked", "talk to's", "presentations",
    "first knock", "last knock date", "# of gaps", "total gap time",
}


def reset_conditional_formatting(ws) -> tuple[int, int]:
    """Wipe ALL existing conditional rules AND static cell backgrounds on
    this tab, then re-apply the canonical visual palette (pale gray /
    warm gold / light cream) via conditional rules.

    The static-background wipe is required because some tabs have direct
    cell coloring (not conditional rules) left over from older scripts
    or manual edits — clearing only conditional rules left those visible.
    After the wipe, the canonical conditional rules paint only the rows
    that have a rep name in col B; everything else stays clean white.

    Returns (removed_count, applied_count).
    """
    from automations.focus_office_att.recolor_template import (
        build_visual_rule_requests,
    )
    WHITE = {"red": 1.00, "green": 1.00, "blue": 1.00}
    sheet_id = ws.id
    meta = ws.spreadsheet.fetch_sheet_metadata(
        params={"fields": "sheets(properties.sheetId,conditionalFormats)"}
    )
    target = next(
        (s for s in meta.get("sheets", []) if s["properties"]["sheetId"] == sheet_id),
        None,
    )
    rules = (target or {}).get("conditionalFormats", []) if target else []
    n_existing = len(rules)

    delete_cf_requests = [
        {"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}}
        for _ in range(n_existing)
    ]
    # Wipe static backgrounds in rows 3-200, cols A-CV (100 cols ~= every
    # daily-block col), so conditional rules become the sole paint source.
    wipe_static_request = {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 2, "endRowIndex": 200,
                "startColumnIndex": 0, "endColumnIndex": 100,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": WHITE}},
            "fields": "userEnteredFormat.backgroundColor",
        },
    }
    add_requests = build_visual_rule_requests(sheet_id)

    all_requests = delete_cf_requests + [wipe_static_request] + add_requests
    if all_requests:
        ws.spreadsheet.batch_update({"requests": all_requests})
    return (n_existing, len(add_requests))


TABLEAU_ONLY_MARK = "🔹"

# Office summary labels (live in col B below the rep rows). Any function
# that iterates "reps" by col B values needs to filter these out — they
# look like rep names structurally but aren't reps.
OFFICE_SUMMARY_LABELS = {
    "OFFICE TOTALS",
    "TOTAL REPS IN FIELD",
    "TOTAL REPS SOLD",
    "REPS ROLLED 0",
    "% ON BOARD",
}


def _is_summary_label(v: str) -> bool:
    if not v:
        return False
    return v.strip().upper().rstrip(TABLEAU_ONLY_MARK).strip() in OFFICE_SUMMARY_LABELS


def strip_rep_mark(name: str) -> str:
    """Strip the Tableau-only marker from a rep name. Used everywhere
    that compares rep names — Phase 2's ownerville matching must ignore
    the marker so 'Joe Smith 🔹' (Tableau-only last week) matches the
    'Joe Smith' that ownerville returns this week.
    """
    if not name:
        return name
    s = name.rstrip()
    while s.endswith(TABLEAU_ONLY_MARK):
        s = s[: -len(TABLEAU_ONLY_MARK)].rstrip()
    return s


def mark_tableau_only_reps(ws, layout: Layout) -> int:
    """Append a subtle marker emoji (🔹) to the rep-name cell for any
    rep that had NO ownerville data this week (all past-day activity
    cells are 'x'). Such reps were added by Phase 3 because they had
    production in Tableau but didn't show up in ownerville's Time
    Tracker / Disposition.

    Run AFTER apply_empty_cell_defaults — depends on activity-empty cells
    already being filled with 'x' so we can detect 'all x' as the signal.

    Idempotent: a rep that's no longer Tableau-only (now has TT/Disp data
    too) gets the marker stripped back off the next run.

    Returns the count of reps now marked.
    """
    if not layout.day_cols:
        return 0

    rep_vals = ws.col_values(layout.rep_name_col)
    rep_rows = [
        i for i, v in enumerate(rep_vals, start=1)
        if i >= 3
        and v and v.strip()
        and not _is_summary_label(v)
    ]
    if not rep_rows:
        return 0
    first_rep_row, last_rep_row = rep_rows[0], rep_rows[-1]

    today_weekday = dt.date.today().weekday()
    past_weekdays = set(range(0, today_weekday + 1))

    # Activity-col addresses on past days only — match case-insensitively.
    activity_cols: list[int] = []
    for wd_idx, metric_map in layout.day_cols.items():
        if wd_idx not in past_weekdays:
            continue
        for metric, col in metric_map.items():
            if metric.lower() in _ACTIVITY_METRICS:
                activity_cols.append(col)
    if not activity_cols:
        return 0

    min_col, max_col = min(activity_cols), max(activity_cols)
    rep_data = ws.get(
        f"{_col_letter(min_col)}{first_rep_row}:{_col_letter(max_col)}{last_rep_row}",
        value_render_option="FORMATTED_VALUE",
    )

    # Defensive: clear any leftover italic/gray text formatting from
    # earlier code that used those instead of an emoji. Megan wants the
    # rep-name color/formatting unchanged — the only marker is the emoji.
    rep_col_zi = layout.rep_name_col - 1
    ws.spreadsheet.batch_update({"requests": [{
        "repeatCell": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": first_rep_row - 1, "endRowIndex": last_rep_row,
                "startColumnIndex": rep_col_zi, "endColumnIndex": rep_col_zi + 1,
            },
            "cell": {"userEnteredFormat": {"textFormat": {
                "italic": False,
                "foregroundColor": {"red": 0, "green": 0, "blue": 0},
            }}},
            "fields": "userEnteredFormat.textFormat.italic,userEnteredFormat.textFormat.foregroundColor",
        },
    }]})

    # Read current rep names so we can append/strip the marker per row.
    rep_name_values = ws.col_values(layout.rep_name_col)

    marked_count = 0
    cells_to_write: list[tuple[str, str]] = []
    for ri, row in enumerate(rep_data):
        sheet_row = first_rep_row + ri
        all_x = True
        for col in activity_cols:
            idx = col - min_col
            v = (row[idx] if idx < len(row) else "").strip().lower()
            if v != "x":
                all_x = False
                break
        current = rep_name_values[sheet_row - 1] if sheet_row - 1 < len(rep_name_values) else ""
        base = strip_rep_mark(current)
        target = f"{base} {TABLEAU_ONLY_MARK}" if all_x else base
        if current != target:
            cells_to_write.append(
                (f"{_col_letter(layout.rep_name_col)}{sheet_row}", target)
            )
        if all_x:
            marked_count += 1

    if cells_to_write:
        data = [{"range": f"'{ws.title}'!{a1}", "values": [[v]]} for a1, v in cells_to_write]
        ws.spreadsheet.values_batch_update({"valueInputOption": "RAW", "data": data})
    return marked_count


def apply_empty_cell_defaults(ws, layout: Layout) -> None:
    """Fill empty data cells with '0' or 'x' per Raf's formatting request:

    - Production columns (New INT / Upgrades / DTV / New Lines): empty → 0
    - Activity columns (Total Leads Knocked / Talk To's / Presentations /
      First Knock / Last Knock Date / # Of Gaps / Total Gap Time): empty → x

    Only touches days that have already passed (Mon → today). Future days
    in the current week stay empty — they're 'not yet scraped', not 'rep
    didn't work'.
    """
    if not layout.day_cols:
        return

    rep_vals = ws.col_values(layout.rep_name_col)
    rep_rows = [
        i for i, v in enumerate(rep_vals, start=1)
        if i >= 3
        and v and v.strip()
        and not _is_summary_label(v)
    ]
    if not rep_rows:
        return
    last_rep_row = rep_rows[-1]

    # Only fill defaults for days that have already passed in the current week.
    today_weekday = dt.date.today().weekday()  # 0=Mon..6=Sun
    past_weekdays = set(range(0, today_weekday + 1))

    # Build a flat map of (sheet_col → metric_name) for the day-block cells
    # we care about, restricted to past weekdays. Compare metric names
    # case-insensitively — the resolver may lowercase some keys (e.g.
    # '# of gaps') while the Sheet headers are title case.
    col_to_metric: dict[int, str] = {}
    for wd_idx, metric_map in layout.day_cols.items():
        if wd_idx not in past_weekdays:
            continue
        for metric, col in metric_map.items():
            mlow = metric.lower()
            if mlow in _PRODUCTION_METRICS or mlow in _ACTIVITY_METRICS:
                col_to_metric[col] = mlow

    if not col_to_metric:
        return

    min_col = min(col_to_metric)
    max_col = max(col_to_metric)

    # One range read covers every cell we might touch.
    rep_data = ws.get(
        f"{_col_letter(min_col)}3:{_col_letter(max_col)}{last_rep_row}",
        value_render_option="FORMATTED_VALUE",
    )

    # Only fill defaults on rows that have an actual rep — skip phantom
    # rows (no name in col B) so we don't paint 'x'/'0' across an empty
    # row 3 (or any other empty row in the rep range).
    rep_rows_set = set(rep_rows)

    updates: list[dict] = []
    for ri, row in enumerate(rep_data):
        sheet_row = 3 + ri
        if sheet_row not in rep_rows_set:
            continue  # phantom row — skip
        for col, metric in col_to_metric.items():
            idx = col - min_col
            v = row[idx] if idx < len(row) else ""
            if v != "" and not (isinstance(v, str) and not v.strip()):
                continue  # already populated
            fill = "0" if metric in _PRODUCTION_METRICS else "x"
            updates.append({
                "range": f"{_col_letter(col)}{sheet_row}",
                "values": [[fill]],
            })

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")


def write_office_totals_row(ws, layout: Layout) -> None:
    """Write/refresh the OFFICE TOTALS row at the bottom of the rep list.

    Spans the entire data range (col C through the last per-day metric
    in Sun's block). Per Raf: the totals row should aggregate every per-
    day metric, not just the Weekly Total summary.

    Cell-by-cell rules:
      - Col C: 'OFFICE TOTALS' label (col B is left blank — that's how
        the conditional format detects this row).
      - Weekly Total block (cols C..L): SUM cols summed across reps,
        AVG cols averaged.
      - Per-day cells: each metric summed (or averaged for time-style
        metrics — First Knock, Last Knock Date, total gap time).

    Reads + writes use UNFORMATTED_VALUE so time/duration columns
    (1st Knock, Last Knock, Gap Time) round-trip as serial numbers — the
    Sheet's existing cell formatting handles display.

    Idempotent: replaces the existing OFFICE TOTALS row if one exists
    (detected by 'OFFICE TOTALS' literal in col B, C, or D), otherwise
    appends below the last rep.
    """
    rep_vals = ws.col_values(layout.rep_name_col)
    # Find last rep row — but skip any row whose rep_name_col contains
    # 'OFFICE TOTALS' (an old buggy write may have landed the label there
    # instead of col C).
    rep_rows = [
        i for i, v in enumerate(rep_vals, start=1)
        if i >= 3
        and v and v.strip()
        and not _is_summary_label(v)
    ]
    if not rep_rows:
        return
    last_rep_row = rep_rows[-1]

    # Detect ALL prior OFFICE TOTALS rows — check cols B, C, D since past
    # writes may have placed the label in different cells. Collect every
    # one so we can clear duplicates that earlier buggy runs left behind.
    existing_totals_rows: set[int] = set()
    for probe_col in (2, 3, 4):
        col_vals = ws.col_values(probe_col)
        for i, v in enumerate(col_vals, start=1):
            if isinstance(v, str) and v.strip().upper() == "OFFICE TOTALS":
                existing_totals_rows.add(i)

    # Always position the totals row IMMEDIATELY below the last rep.
    target_row = last_rep_row + 1

    # Per-day metrics that should be AVERAGED (time-style values) rather
    # than summed. Everything else in a day's block is a count → SUM.
    PER_DAY_AVG_METRICS = {"First Knock", "Last Knock Date", "total gap time"}

    # Build the full set of cols we need to read + their aggregation type.
    # Weekly cols (3..12) are classified by row-2 header prefix.
    header_row = ws.row_values(2)
    weekly_sum_cols: list[int] = []
    weekly_avg_cols: list[int] = []
    for col_idx in range(3, 13):  # cols C..L
        h = (header_row[col_idx - 1] if col_idx - 1 < len(header_row) else "").strip()
        if h.startswith("SUM "):
            weekly_sum_cols.append(col_idx)
        elif h.startswith("AVG "):
            weekly_avg_cols.append(col_idx)

    # Per-day cols come from layout.day_cols[wd][metric] → 1-based col idx.
    # Group by (col_idx, agg_type) for downstream aggregation.
    perday_sum_cols: list[int] = []
    perday_avg_cols: list[int] = []
    for wd in sorted(layout.day_cols.keys()):
        for metric, col_idx in layout.day_cols[wd].items():
            if metric in PER_DAY_AVG_METRICS:
                perday_avg_cols.append(col_idx)
            else:
                perday_sum_cols.append(col_idx)

    # Determine the rightmost col we need to write to so we know the
    # write range + can clear stale rows the same width.
    all_cols = (
        weekly_sum_cols + weekly_avg_cols
        + perday_sum_cols + perday_avg_cols
        + [3]  # label cell
    )
    last_col = max(all_cols) if all_cols else 12

    last_col_letter = _col_letter(last_col)

    # Clear any stale totals rows (anything except target_row). This
    # handles the case where prior runs landed at a different position
    # (rep count changed, or a write put the label in the wrong column).
    # Clear across the FULL data range so older writes that landed in
    # per-day cells get wiped too.
    # When clearing a stale OFFICE TOTALS row, ALSO clear the 4 summary
    # rows directly beneath it (TOTAL REPS IN FIELD / SOLD / ROLLED 0 / %
    # ON BOARD) — those form one logical block with OFFICE TOTALS. Without
    # this, a re-run that relocates OFFICE TOTALS leaves the old summary
    # rows orphaned in their original position.
    for stale_row in sorted(existing_totals_rows):
        if stale_row == target_row:
            continue
        stale_block_end = stale_row + 4  # OFFICE TOTALS + 4 summary rows
        ws.update(
            f"A{stale_row}:{last_col_letter}{stale_block_end}",
            [[""] * (last_col)] * 5,
            value_input_option="RAW",
        )
    totals_row = target_row

    # Pull rep-row values across the full width so per-day cols are
    # included. UNFORMATTED keeps time-style cells as serial numbers.
    rep_data = ws.get(
        f"A3:{last_col_letter}{last_rep_row}",
        value_render_option="UNFORMATTED_VALUE",
    )

    def _column(col_idx: int) -> list[float]:
        out: list[float] = []
        for row in rep_data:
            if len(row) < col_idx:
                continue
            v = row[col_idx - 1]
            if isinstance(v, (int, float)):
                out.append(float(v))
        return out

    # Build totals dict {col_idx → value}. Label lives in col B (under
    # the rep-name column, per Megan's preferred layout).
    totals: dict[int, object] = {}
    for col in weekly_sum_cols + perday_sum_cols:
        vals = _column(col)
        totals[col] = sum(vals) if vals else 0
    for col in weekly_avg_cols + perday_avg_cols:
        vals = _column(col)
        # Average reps with numeric values (empty cells excluded by
        # _column's isinstance check). A 0 means the rep worked but had
        # no gaps / instant gap time — legitimate data, not filtered.
        totals[col] = sum(vals) / len(vals) if vals else ""

    # Write the FULL row B..last_col in one shot. Use values_batch_update
    # so we can include col B (label) without hitting gspread's leading-
    # empty-string left-shift bug (that bug only affects ws.update with
    # leading empty cells; values_batch_update with explicit ranges is fine).
    values_b_onward: list[object] = ["OFFICE TOTALS"]  # col B
    for col in range(3, last_col + 1):
        values_b_onward.append(totals.get(col, ""))
    ws.spreadsheet.values_batch_update({
        "valueInputOption": "RAW",
        "data": [{
            "range": f"'{ws.title}'!B{totals_row}:{last_col_letter}{totals_row}",
            "values": [values_b_onward],
        }],
    })
    # Clear col A in case stale content sat there.
    ws.update(f"A{totals_row}", [[""]], value_input_option="RAW")

    # Borders on the totals row:
    #   - Thick black TOP border across the full row → separates totals
    #     from rep rows above.
    #   - Thin black LEFT border at the start of each day's Total Apps
    #     col (M, Y, AK, AW, BI, BU, CG) → visual day-block dividers
    #     within the navy bar.
    # Borders aren't part of conditional formatting, so applied as
    # static formats. Stale prior totals rows get their borders cleared.
    DAY_START_COLS = [13, 25, 37, 49, 61, 73, 85]  # Mon..Sun Total Apps cols
    THICK_BLACK = {"style": "SOLID_THICK", "color": {"red": 0, "green": 0, "blue": 0}}
    THIN_BLACK = {"style": "SOLID_MEDIUM", "color": {"red": 0, "green": 0, "blue": 0}}
    NO_BORDER = {"style": "NONE"}

    border_requests: list[dict] = []
    for stale_row in sorted(existing_totals_rows | {totals_row}):
        is_current = (stale_row == totals_row)
        # Top border across the full row
        border_requests.append({
            "updateBorders": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": stale_row - 1,
                    "endRowIndex": stale_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": last_col,
                },
                "top": THICK_BLACK if is_current else NO_BORDER,
            },
        })
        # Day-start vertical separators (left border on each day's TA col)
        for day_col in DAY_START_COLS:
            if day_col > last_col:
                continue
            border_requests.append({
                "updateBorders": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": stale_row - 1,
                        "endRowIndex": stale_row,
                        "startColumnIndex": day_col - 1,
                        "endColumnIndex": day_col,
                    },
                    "left": THIN_BLACK if is_current else NO_BORDER,
                },
            })
    if border_requests:
        ws.spreadsheet.batch_update({"requests": border_requests})


def write_office_summary_block(ws, layout: Layout) -> None:
    """Append 4 office-level metric rows below OFFICE TOTALS. Per Raf
    Loom 2026-05-15:
      - TOTAL REPS IN FIELD: count of reps with a positive numeric value
        in their Total Leads Knocked cell for the day. Reps with 'x' or
        no data didn't knock anything and are treated as not-in-field.
      - TOTAL REPS SOLD:    count of reps with any sale (New INT /
        Upgrades / DTV / New Lines > 0) for the day.
      - REPS ROLLED 0:      in_field - sold (reps who worked but
        didn't sell).
      - % ON BOARD:         sold / in_field (formatted as percent).

    Each row's per-day value lands under that day's Total Apps col
    (M, Y, AK, AW, BI, BU, CG). Other cells empty. Conditional
    formatting (in recolor_template.build_visual_rule_requests) paints
    all 4 rows + the OFFICE TOTALS row navy/white as one block.

    Idempotent — overwrites the same 4 rows each time. Requires
    write_office_totals_row to have run first (uses its row as anchor).
    """
    # Find OFFICE TOTALS row to anchor the block. Label lives in col B
    # (per Megan's preferred layout — under the rep-name col).
    col_b = ws.col_values(2)
    totals_row: int | None = None
    for i, v in enumerate(col_b, start=1):
        if isinstance(v, str) and v.strip().upper() == "OFFICE TOTALS":
            totals_row = i
            break
    if totals_row is None:
        return  # No anchor → nothing to do

    # Find rep rows above the totals row (skip empty rows + skip totals)
    rep_vals = ws.col_values(layout.rep_name_col)
    rep_rows = [
        i for i, v in enumerate(rep_vals, start=1)
        if i >= 3 and i < totals_row and v and v.strip()
        and not _is_summary_label(v)
    ]
    if not rep_rows:
        return
    last_rep_row = max(rep_rows)

    # Pull rep data once (UNFORMATTED so time-of-day stays a numeric
    # serial; otherwise '8:23 AM' would be a string and not pass the
    # isinstance(_, (int, float)) check below).
    rep_data = ws.get(
        f"A3:CR{last_rep_row}",
        value_render_option="UNFORMATTED_VALUE",
    )

    # All day-column references resolved dynamically from `layout` — no
    # hardcoded col indices. Per Megan: "we shouldn't hardcode this, you
    # should count each scrape."
    SALE_METRICS = ("New INT", "Upgrades", "DTV", "New Lines")
    # Per-day Total Apps col (where the daily count lands)
    day_ta_cols: dict[int, int] = {}
    for wd, metric_map in layout.day_cols.items():
        ta = metric_map.get("Total Apps")
        if ta:
            day_ta_cols[wd] = ta

    # Per-day counts + per-rep weekly flags (for unique weekly totals).
    # In-field rule (per Megan 2026-05-15):
    #   "in the field" = Total Leads Knocked has a positive numeric value
    #   OR any production col (New INT/Upgrades/DTV/New Lines) > 0.
    # Selling implies presence — Tableau-only reps with a sale but no OV
    # door-knock count as in-field via their sale.
    in_field: dict[int, int] = {}
    sold: dict[int, int] = {}
    in_field_any_day = [False] * len(rep_data)
    sold_any_day = [False] * len(rep_data)
    for wd in range(7):
        knocked_col = layout.day_cols.get(wd, {}).get("Total Leads Knocked")
        sale_cols = [
            c for c in (layout.day_cols.get(wd, {}).get(m) for m in SALE_METRICS)
            if c
        ]
        if not knocked_col and not sale_cols:
            in_field[wd] = 0
            sold[wd] = 0
            continue
        in_count = 0
        sold_count = 0
        for ri, row in enumerate(rep_data):
            if not row:
                continue
            has_sale = False
            for sc in sale_cols:
                if len(row) >= sc:
                    v = row[sc - 1]
                    if isinstance(v, (int, float)) and v > 0:
                        has_sale = True
                        break
            if has_sale:
                sold_count += 1
                sold_any_day[ri] = True
            knocked = (row[knocked_col - 1] if knocked_col and len(row) >= knocked_col else None)
            knocked_data = isinstance(knocked, (int, float)) and knocked > 0
            if knocked_data or has_sale:
                in_count += 1
                in_field_any_day[ri] = True
        in_field[wd] = in_count
        sold[wd] = sold_count

    # Weekly UNIQUE counts (a rep counts ONCE per week regardless of how
    # many days they were in field / sold).
    weekly_in_field = sum(in_field_any_day)
    weekly_sold = sum(sold_any_day)
    weekly_rolled_zero = max(0, weekly_in_field - weekly_sold)
    weekly_pct = (weekly_sold / weekly_in_field) if weekly_in_field else 0

    LAST_DATA_COL = 96  # CR

    # (label, weekly_value_for_col_C, per_day_value_fn)
    SUMMARY_ROWS: list[tuple[str, object, callable]] = [
        ("TOTAL REPS IN FIELD", weekly_in_field,    lambda wd: in_field[wd]),
        ("TOTAL REPS SOLD",     weekly_sold,        lambda wd: sold[wd]),
        ("REPS ROLLED 0",       weekly_rolled_zero, lambda wd: max(0, in_field[wd] - sold[wd])),
        ("% ON BOARD",          weekly_pct,         lambda wd: (sold[wd] / in_field[wd]) if in_field[wd] else 0),
    ]

    # Write each summary row from col B onward. Col B = label, Col C =
    # weekly aggregate (matches the SUM Total Apps headline pattern of
    # OFFICE TOTALS), per-day values land in each day's Total Apps col
    # (resolved from layout, not hardcoded).
    update_data = []
    for offset, (label, weekly_val, value_fn) in enumerate(SUMMARY_ROWS, start=1):
        target_row = totals_row + offset
        # Build cols 2..96 (95 cells). Index 0 = col B.
        row_vals: list = [""] * (LAST_DATA_COL - 1)
        row_vals[0] = label                  # col B
        row_vals[1] = weekly_val             # col C
        for wd, ta_col in day_ta_cols.items():
            row_vals[ta_col - 2] = value_fn(wd)
        update_data.append({
            "range": f"'{ws.title}'!B{target_row}:CR{target_row}",
            "values": [row_vals],
        })

    if update_data:
        ws.spreadsheet.values_batch_update({
            "valueInputOption": "RAW",
            "data": update_data,
        })

    # Apply % number format on the % ON BOARD row's per-day cells, plus
    # day-block left borders on all 4 new rows (matches the OFFICE TOTALS
    # row's separators so the navy bar reads as one continuous block).
    pct_row = totals_row + 4
    THIN_BLACK = {"style": "SOLID_MEDIUM", "color": {"red": 0, "green": 0, "blue": 0}}

    fmt_requests = []
    # Apply % format to col C (weekly aggregate) + each day's TA col on
    # the % ON BOARD row.
    pct_cols = [3] + list(day_ta_cols.values())  # col C + day TA cols
    for c in pct_cols:
        fmt_requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": pct_row - 1,
                    "endRowIndex": pct_row,
                    "startColumnIndex": c - 1,
                    "endColumnIndex": c,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                "fields": "userEnteredFormat.numberFormat",
            },
        })
    for offset in range(1, 5):
        target_row = totals_row + offset
        for ta_col in day_ta_cols.values():
            fmt_requests.append({
                "updateBorders": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": target_row - 1,
                        "endRowIndex": target_row,
                        "startColumnIndex": ta_col - 1,
                        "endColumnIndex": ta_col,
                    },
                    "left": THIN_BLACK,
                },
            })
    if fmt_requests:
        ws.spreadsheet.batch_update({"requests": fmt_requests})


# ---- Orchestration ----
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner-tab", default="Cody Cannon",
                    help="Sheet tab name to fill (defaults to 'Cody Cannon')")
    ap.add_argument("--week-start", default=None,
                    help="Monday of week to scrape (YYYY-MM-DD); defaults to current week's Monday")
    args = ap.parse_args()

    today = dt.date.today()
    if args.week_start:
        monday = dt.datetime.strptime(args.week_start, "%Y-%m-%d").date()
    else:
        monday = today - dt.timedelta(days=today.weekday())
    days = [monday + dt.timedelta(days=i) for i in range(7) if monday + dt.timedelta(days=i) <= today]
    print(f"Owner tab: {args.owner_tab}")
    print(f"Days to scrape: {[d.strftime('%a %m/%d') for d in days]}")

    # Open Sheet
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    try:
        ws = sh.worksheet(args.owner_tab)
    except Exception:
        print(f"❌ No tab named {args.owner_tab!r} in the Sheet.")
        return 1

    # Resolve column layout FIRST — any "header changed?" prompts happen
    # here, before we waste time scraping. Covers Time Tracker + Disposition
    # + the per-day sale-type metrics (so Weekly formulas can reference them).
    print(f"  → Resolving column layout from '{args.owner_tab}'…")
    all_metrics = (
        list(TT_FIELD_TO_CANONICAL.values())
        + list(DISP_FIELD_TO_CANONICAL.values())
        + ["Total Apps", "New INT", "Upgrades", "DTV", "New Lines"]
    )
    layout = resolve_layout(ws, metrics=all_metrics)
    print(f"    ✓ Rep Name = col {layout.rep_name_col}; "
          f"resolved {len(layout.day_cols)} day block(s)")

    # Connect to Chrome
    p = sync_playwright().start()
    try:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "ownerville" in pg.url:
                    page = pg
                    break
            if page:
                break
        if not page:
            print("❌ No ownerville tab found.")
            return 1
        print(f"✓ Chrome session: {page.title()}")

        # Read rqstValue once — needed for navigation to both pages.
        rqst = page.evaluate("typeof rqstValue !== 'undefined' ? rqstValue : null")
        if not rqst:
            print("❌ rqstValue not found — not impersonating?")
            return 1

        # Time Tracker scrape: one navigation, then one day at a time.
        if TIME_TRACKER_PAGE not in page.url:
            page.goto(f"https://v2.ownerville.com/index.cfm?p=510&rqst={rqst}",
                      wait_until="networkidle", timeout=20000)
        tt_by_date: dict[dt.date, list[dict]] = {}
        for d in days:
            print(f"  → [Time Tracker] {d.strftime('%a %m/%d/%Y')}…")
            reps = scrape_day(page, d)
            tt_by_date[d] = reps
            print(f"    ✓ {len(reps)} rep(s)")

        # Disposition scrape: re-navigate per day so the URL date filter
        # is actually applied server-side (the on-page picker is cosmetic).
        disp_by_date: dict[dt.date, list[dict]] = {}
        for d in days:
            print(f"  → [Disposition]  {d.strftime('%a %m/%d/%Y')}…")
            reps = scrape_disposition_day(page, d, rqst)
            disp_by_date[d] = reps
            print(f"    ✓ {len(reps)} rep(s)")
    finally:
        p.stop()

    # Merge Time Tracker + Disposition by (date, rep_name) → one combined record per rep.
    scraped_by_date: dict[dt.date, list[dict]] = {}
    for d in days:
        by_name: dict[str, dict] = {}
        for r in tt_by_date.get(d, []):
            key = r["name"].lower().strip()
            by_name[key] = {**by_name.get(key, {}), **r}
        for r in disp_by_date.get(d, []):
            key = r["name"].lower().strip()
            by_name[key] = _merge_rep_records(by_name.get(key, {"name": r["name"]}), r)
        scraped_by_date[d] = list(by_name.values())

    # Write to Sheet
    print(f"  → Writing to '{ws.title}' tab…")
    stats = fill_owner_tab(ws, scraped_by_date, layout)
    print(f"    ✓ wrote {stats['written_cells']} cell(s), "
          f"skipped {stats['skipped_cells']} (already-filled)")
    if stats["new_reps"]:
        print(f"    ✓ added {len(stats['new_reps'])} new rep row(s): {stats['new_reps']}")

    # Post-fill: weekly formulas + alphabetize + border + gap-time format + autosize + collapse
    print(f"  → Weekly formulas + alphabetize + border + gap-time format + autosize + collapse…")
    write_weekly_formulas(ws, layout)
    alphabetize_reps(ws, layout)
    apply_bold_border(ws)
    apply_gap_time_format(ws, layout)
    autosize_all_data_cols(ws)
    update_collapse_states(ws)

    print(f"✅ Done — {args.owner_tab} filled for {len(days)} day(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

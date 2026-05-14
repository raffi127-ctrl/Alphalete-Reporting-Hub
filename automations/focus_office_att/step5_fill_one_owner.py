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

    # Build a {rep_name_lower: row} map from existing data
    rep_col_values = ws.col_values(rep_col)
    name_to_row = {}
    for i, name in enumerate(rep_col_values, start=1):
        if i < 3 or not name.strip():
            continue
        name_to_row[name.lower().strip()] = i

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

    cells_to_write = []  # list of (a1, value)
    new_reps = []
    new_rep_rows: list[int] = []   # rows that need formatting copied from row 3
    skipped_cells = 0
    written_cells = 0

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
                # New rep — assign next available row
                row = max([3] + list(name_to_row.values())) + 1
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
                written_cells += 1

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
        "written_cells": written_cells,
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
                    # AVERAGE wrapped so reps with no data show blank, not #DIV/0!.
                    formula = f'=IFERROR(AVERAGE({",".join(cells)}),"")'
            data.append({
                "range": f"'{ws.title}'!{_col_letter(weekly_col)}{r}",
                "values": [[formula]],
            })

    if data:
        ws.spreadsheet.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})
    return len(data)


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
    """Sort rep rows (rows 3+) alphabetically by the Rep Name column."""
    rep_col_values = ws.col_values(layout.rep_name_col)
    last_row = max([2] + [i for i, v in enumerate(rep_col_values, start=1) if v.strip() and i >= 3])
    if last_row < 4:
        return  # nothing to sort
    all_cols = [c for day_map in layout.day_cols.values() for c in day_map.values()] + [layout.rep_name_col]
    last_data_col = max(all_cols) if all_cols else layout.rep_name_col
    sheet_id = ws.id
    ws.spreadsheet.batch_update({"requests": [{
        "sortRange": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 2,            # row 3 (0-indexed)
                "endRowIndex": last_row,       # exclusive upper bound
                # EXCLUDE col A (the count) from the sort. sortRange doesn't
                # auto-update relative refs when it moves cells, so if col A
                # were included, its =IF($B3="","",ROW()-2) formulas would
                # get shuffled along with rows and end up referencing the
                # WRONG B column — producing scrambled count values (e.g.
                # 3, 4, 6, 8, 13, ... instead of 1, 2, 3, 4, ...).
                # By starting at col B (index 1), col A stays put and its
                # per-row formulas keep evaluating sequentially.
                "startColumnIndex": 1,
                "endColumnIndex": last_data_col,
            },
            "sortSpecs": [{"sortOrder": "ASCENDING",
                          # dimensionIndex is 0-based WITHIN the sortRange,
                          # so subtract startColumnIndex (1) from the actual
                          # rep-name col index. Rep is col B (1-indexed=2);
                          # inside this range that's index 1.
                          "dimensionIndex": layout.rep_name_col - 1 - 1}],
        },
    }]})


_PRODUCTION_METRICS = {"new int", "upgrades", "dtv", "new lines"}
_ACTIVITY_METRICS = {
    "total leads knocked", "talk to's", "presentations",
    "first knock", "last knock date", "# of gaps", "total gap time",
}


def clear_conditional_formatting(ws) -> int:
    """Remove ALL conditional format rules from this tab. Returns the
    count removed. Raf wants no green/red on the report; the only
    coloring source is conditional formatting (added by recolor_template
    during Phase 1 setup). Wiping it leaves the tab plain.
    """
    sheet_id = ws.id
    meta = ws.spreadsheet.fetch_sheet_metadata(
        params={"fields": "sheets(properties.sheetId,conditionalFormats)"}
    )
    target = next(
        (s for s in meta.get("sheets", []) if s["properties"]["sheetId"] == sheet_id),
        None,
    )
    if not target:
        return 0
    rules = target.get("conditionalFormats", [])
    n = len(rules)
    if n == 0:
        return 0
    # Each delete shrinks the list by 1, so always delete index 0 n times.
    ws.spreadsheet.batch_update({"requests": [
        {"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}}
        for _ in range(n)
    ]})
    return n


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
        and v.strip().upper() != "OFFICE TOTALS"
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

    updates: list[dict] = []
    for ri, row in enumerate(rep_data):
        sheet_row = 3 + ri
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

    Spans cols C-L (the Weekly Total summary block, minus the #/Rep Name
    pair). Looks at each summary column's header — 'SUM ...' cols get
    summed across reps, 'AVG ...' cols get averaged. Col C ('SUM Total
    Apps') is repurposed as the label cell per Megan's preferred layout
    (see Cody Cannon tab as reference).

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
        and v.strip().upper() != "OFFICE TOTALS"
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

    # Clear any stale totals rows (anything except target_row). This
    # handles the case where prior runs landed at a different position
    # (rep count changed, or a write put the label in the wrong column).
    for stale_row in sorted(existing_totals_rows):
        if stale_row == target_row:
            continue
        ws.update(
            f"A{stale_row}:L{stale_row}",
            [[""] * 12],
            value_input_option="RAW",
        )
    totals_row = target_row

    # Read header row 2, cols A-L, to classify SUM vs AVG cells
    header_row = ws.row_values(2)
    sum_cols: list[int] = []
    avg_cols: list[int] = []
    for col_idx in range(3, 13):  # cols C..L
        h = (header_row[col_idx - 1] if col_idx - 1 < len(header_row) else "").strip()
        if h.startswith("SUM "):
            sum_cols.append(col_idx)
        elif h.startswith("AVG "):
            avg_cols.append(col_idx)

    # Pull rep-row values for cols A-L as UNFORMATTED so times stay numeric
    rep_data = ws.get(
        f"A3:L{last_rep_row}",
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

    # Build totals dict {col_idx → value} for cols C..L
    totals: dict[int, object] = {3: "OFFICE TOTALS"}  # label in col C
    for col in sum_cols:
        if col == 3:
            continue  # col C is the label, not a sum
        vals = _column(col)
        totals[col] = sum(vals) if vals else 0
    for col in avg_cols:
        vals = _column(col)
        # Average all reps that have a numeric value (empty cells already
        # excluded by _column's isinstance check). A 0 means the rep worked
        # but had no gaps / instant gap time, which is legitimate data —
        # don't filter those out.
        totals[col] = sum(vals) / len(vals) if vals else ""

    # Write ONLY cols C..L. Don't include A/B in the range — past attempts
    # with leading empty strings ('') in a range write caused gspread to
    # shift values left by one column. Sidestep entirely by starting the
    # range at C and clearing A/B separately if they have stale data.
    values_c_to_l: list[object] = [totals.get(col, "") for col in range(3, 13)]
    ws.update(
        f"C{totals_row}:L{totals_row}",
        [values_c_to_l],
        value_input_option="RAW",
    )
    # Clear A/B in case an old buggy write left content there.
    ws.update(f"A{totals_row}:B{totals_row}", [["", ""]], value_input_option="RAW")


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

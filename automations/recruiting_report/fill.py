"""Write fetched funnel metrics into the mass-report Google Sheet.

Tab handling per office (driven by office-mapping.json):
  - confirmed:    write data; if tab is empty (no funnel structure), first
                  inject the Template Fiber tab's contents, then write data
                  for all historical weeks AS has data for.
  - needs_review: color the tab red so the user knows to map it; do NOT
                  overwrite any data.
  - skip:         ignore entirely (admin/template tabs).

Column header convention: the Sunday at the START of the AS week (the date
shown in AS's weekStart picker). Match by exact date string.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gspread


def _retry(fn, *args, attempts: int = 6, base_delay: float = 1.5, **kwargs):
    """Retry a Sheets API call on transient errors with exponential backoff.
    Handles 5xx (server errors) and 429 (quota / rate limit). 429 uses a
    longer base wait since the per-minute quota window is 60s."""
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 429 and i < attempts - 1:
                # Wait at least 30s for quota window to reset
                wait = max(30, base_delay * (2 ** i)) + random.uniform(0, 5)
                time.sleep(wait)
                continue
            if status and 500 <= status < 600 and i < attempts - 1:
                wait = base_delay * (2 ** i) + random.uniform(0, 0.5)
                time.sleep(wait)
                continue
            raise

# Sheet ID resolution order:
#   1. RECRUITING_REPORT_SHEET_ID env var (for ad-hoc overrides)
#   2. ~/.config/recruiting-report/config.json {"spreadsheet_id": "..."}
#   3. Hardcoded fallback below (Megan's test sheet)
import os as _os
_CONFIG_PATH = Path.home() / ".config" / "recruiting-report" / "config.json"

def _resolve_sheet_id() -> str:
    if env := _os.environ.get("RECRUITING_REPORT_SHEET_ID"):
        return env.strip()
    if _CONFIG_PATH.exists():
        try:
            cfg = json.loads(_CONFIG_PATH.read_text())
            if cfg.get("spreadsheet_id"):
                return cfg["spreadsheet_id"].strip()
        except Exception:
            pass
    # Production Recruiting Report Sheet. Teammates without a local
    # ~/.config/recruiting-report/config.json fall through to this default.
    return "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"

SPREADSHEET_ID = _resolve_sheet_id()
OAUTH_CLIENT_PATH = Path.home() / ".config" / "recruiting-report" / "oauth-client.json"
OAUTH_TOKEN_PATH = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MAPPING_PATH = Path(__file__).resolve().parent / "office-mapping.json"
MASTER_TAB = "Raf Hidalgo"
TEMPLATE_TAB = "Template Fiber"
NEEDS_REVIEW_COLOR = {"red": 1.0, "green": 0.0, "blue": 0.0}
UNCATEGORIZED_COLOR = {"red": 0.0, "green": 0.4, "blue": 1.0}

# Per-office tab structure:
#   - row 1 = headers ("OFFICE GOALS", "WE SUNDAY", then weekly Sunday dates from col 3 onward)
#   - col A = office-goals reference values
#   - col B = metric row labels
#   - col C+ = weekly data
# So: scan COLUMN B for labels; find Sunday columns in ROW 1.
LABEL_COLUMN = 2  # column B
HEADER_ROW = 1    # row 1 (1-indexed)

OFFICE_METRIC_TO_ROW_LABEL = {
    "pull":                       ["Sent To Call List - APPS / PULL", "APPS / PULL"],
    "pct_apps_booked_first":      "Retention to Call list",
    "first_booked":               "1ST BOOKED",
    "first_showed":               "1ST SHOWED",
    "pct_first_retention":        "1st Retention",
    "second_booked":              "2ND BOOKED",
    "second_showed":              "2ND SHOWED",
    "pct_second_retention":       "2ND Retention",
    "job_offered":                "Job Offered",
    "pct_job_offered_retention":  "Job Offered Retention",
    "bob":                        "BOB",
    "pct_bob_conversion":         "BOB Conversion",
    "new_starts_scheduled":       "New Starts Scheduled",
    "new_starts_showed":          "New Starts Showed",
    "pct_new_start_retention":    "New Start Retention",
    "removed_from_process_emails": "Removed From Process Emails",
    "total_applies":              "Total Applies",
    "duplicate_pct":              "Duplicate %",
    "pct_first_showed_booked_2nd":["Retention 1st showed Booked for 2nd", "% of 1st Booked 2nd"],
}

# Master tab Table 6: canonical metric -> row-2 sub-header text within the
# date-block columns. Master tab has a 2-row header (row 1 = date, row 2 =
# metric name).
MASTER_METRIC_TO_HEADER = {
    "pull":                       "Pull",
    "first_booked":               "1st rds booked",
    "pct_apps_booked_first":      "% of apps booked for 1st rd",
    "first_showed":               "1st rds showed",
    "pct_first_retention":        "% 1st rd retention",
    "second_booked":              "2nd booked",
    "second_showed":              "2nd showed",
    "pct_second_retention":       "% 2nd rd retention",
    "job_offered":                "Job offered",
    "pct_job_offered_retention":  "% Job offered retention",
    "bob":                        "BOB",
    "pct_bob_conversion":         "% BOB Conversion",
    "new_starts_scheduled":       "New starts scheduled",
    "new_starts_showed":          "New starts showed",
    "pct_new_start_retention":    "% New start retention",
}

def _all_labels(value):
    """A value in OFFICE_METRIC_TO_ROW_LABEL may be a single string or a list."""
    return [value] if isinstance(value, str) else list(value)


PERCENT_METRICS = {
    k for k, val in OFFICE_METRIC_TO_ROW_LABEL.items()
    if any(
        "%" in label
        or "retention" in label.lower()
        or "conversion" in label.lower()
        or "booked for" in label.lower()
        for label in _all_labels(val)
    )
}


def _client() -> gspread.Client:
    if not OAUTH_CLIENT_PATH.exists():
        raise SystemExit(f"OAuth client JSON not found at {OAUTH_CLIENT_PATH}.")
    return gspread.oauth(
        scopes=SCOPES,
        credentials_filename=str(OAUTH_CLIENT_PATH),
        authorized_user_filename=str(OAUTH_TOKEN_PATH),
    )


def open_sheet():
    return _client().open_by_key(SPREADSHEET_ID)


def load_mapping() -> dict:
    return json.loads(MAPPING_PATH.read_text())


# ---------- date helpers ----------

def format_sunday(d: dt.date) -> List[str]:
    """Possible string forms a column header may use for a Sunday date."""
    return [
        f"{d.month}/{d.day}/{d.year % 100}",     # 5/3/26
        f"{d.month}/{d.day}/{d.year}",           # 5/3/2026
        f"{d.month:02d}/{d.day:02d}/{d.year % 100}",  # 05/03/26
        f"{d.month:02d}/{d.day:02d}/{d.year}",   # 05/03/2026
    ]


def find_sunday_columns(values: List[List[str]], header_row_idx: int = 0) -> Dict[dt.date, int]:
    """Return {Sunday-date: 1-indexed column} for every column header that
    parses as a date in row `header_row_idx`."""
    result: Dict[dt.date, int] = {}
    if not values or header_row_idx >= len(values):
        return result
    for col_idx, raw in enumerate(values[header_row_idx], start=1):
        d = _try_parse_date(str(raw).strip())
        if d:
            result[d] = col_idx
    return result


def _try_parse_date(s: str) -> Optional[dt.date]:
    """Parse common date formats found in the Sheet's column headers."""
    if not s:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%-m/%-d/%y", "%-m/%-d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ---------- tab inspection ----------

def is_office_tab_populated(ws: gspread.Worksheet) -> bool:
    """Return True if this office tab already has the funnel structure.
    Check if we can find any of the expected metric rows in column B."""
    try:
        metric_rows = find_office_metric_rows(ws)
        return len(metric_rows) > 0
    except Exception:
        return False


def find_office_section_anchor(ws: gspread.Worksheet, office_id: str) -> Optional[int]:
    """Return the row at which this office_id's metric section starts.
    Searches column A for a cell containing the office_id (e.g.
    '22057 - Chan Park - Nola Management Group, Inc. 2nd'). Returns row+1
    so the caller starts looking for metric labels right after the header.
    Returns None if no anchor found (caller defaults to top of tab)."""
    col_a = _retry(ws.col_values, 1)
    for row_idx, val in enumerate(col_a, start=1):
        if val and str(office_id) in str(val):
            return row_idx + 1
    return None


def find_office_metric_rows(
    ws: gspread.Worksheet,
    anchor_row: int = 1,
    max_rows: int = 30,
) -> Dict[str, int]:
    """Map canonical metric -> 1-indexed row in this office tab. Returns only
    metrics whose row label was found in column B.

    Matching: case-insensitive — exact, prefix-then-separator (e.g. 'APPS / PULL'
    matches 'APPS / PULL Daily'), or suffix-then-separator (e.g. 'APPS / PULL'
    matches 'Jackson - APPS / PULL'). First occurrence wins.

    Section scoping: searches rows in [anchor_row, anchor_row + max_rows). Use
    anchor_row=1 for the primary section at the top of a tab; use the row
    AFTER a section header for sibling sections."""
    result: Dict[str, int] = {}
    col_b = _retry(ws.col_values, LABEL_COLUMN)
    # Build (label_lower, metric) pairs from all aliases, sorted by length DESC
    label_to_metric = []
    for m, val in OFFICE_METRIC_TO_ROW_LABEL.items():
        for label in _all_labels(val):
            label_to_metric.append((label.lower().strip(), m))
    label_to_metric.sort(key=lambda x: -len(x[0]))

    end_row = min(anchor_row + max_rows, len(col_b) + 1)
    for row_idx in range(anchor_row, end_row):
        if row_idx > len(col_b):
            break
        val = col_b[row_idx - 1]
        val_clean = (val or "").strip().lower()
        if not val_clean:
            continue
        for label_lower, metric in label_to_metric:
            if metric in result:
                continue
            if (val_clean == label_lower
                or val_clean.startswith(label_lower + " ")
                or val_clean.startswith(label_lower + "-")
                or val_clean.startswith(label_lower + ":")
                or val_clean.endswith(" " + label_lower)
                or val_clean.endswith("-" + label_lower)):
                result[metric] = row_idx
                break
    return result


# ---------- template injection ----------

def inject_template(sh: gspread.Spreadsheet, target_tab: str) -> None:
    """Copy all cell values from TEMPLATE_TAB into target_tab.

    Preserves the target tab (doesn't delete + recreate, so its position and
    name are unchanged). Note: this copies values only; for full formatting
    fidelity we'd need a Sheets API batchUpdate.
    """
    template = sh.worksheet(TEMPLATE_TAB)
    target = sh.worksheet(target_tab)
    template_values = _retry(template.get_all_values)
    if not template_values:
        return
    # Resize target to match
    rows = max(len(template_values), target.row_count)
    cols = max(max(len(r) for r in template_values), target.col_count)
    if target.row_count != rows or target.col_count != cols:
        _retry(target.resize, rows=rows, cols=cols)
    # Bulk write
    _retry(target.update, template_values, "A1", value_input_option="USER_ENTERED")


# ---------- formatting ----------

def _set_tab_color(ws: gspread.Worksheet, color: dict) -> None:
    try:
        _retry(ws.update_tab_color, color)
    except AttributeError:
        _retry(ws.spreadsheet.batch_update, {
            "requests": [{
                "updateSheetProperties": {
                    "properties": {"sheetId": ws.id, "tabColor": color},
                    "fields": "tabColor",
                }
            }]
        })


def mark_needs_review(ws: gspread.Worksheet) -> None:
    """Color tab red — flag for the user to fix the office mapping."""
    _set_tab_color(ws, NEEDS_REVIEW_COLOR)


def mark_uncategorized(ws: gspread.Worksheet) -> None:
    """Color tab blue — admin/template/notes tab not part of the office set."""
    _set_tab_color(ws, UNCATEGORIZED_COLOR)


# ---------- office tab fill ----------

def _format_value(metric: str, value) -> str:
    if value is None:
        return ""
    if metric in PERCENT_METRICS:
        return f"{int(round(float(value)))}%"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def fill_office_section(
    ws: gspread.Worksheet,
    metric_rows: Dict[str, int],
    sunday_to_col: Dict[dt.date, int],
    week_data: Dict[dt.date, Dict[str, Optional[float]]],
    dry_run: bool,
    label: str = "",
) -> List[str]:
    """Write data into one section of an office tab. Caller pre-computes
    metric_rows (which can be the primary section's rows or a sibling
    section's rows on a multi-office tab) and the date columns."""
    log: List[str] = []
    updates: List[Tuple[str, str]] = []
    for sunday, metrics in week_data.items():
        col = sunday_to_col.get(sunday)
        if col is None:
            log.append(f"  [WARN] {label}: no column for week {sunday.isoformat()}")
            continue
        for metric_key, row in metric_rows.items():
            value = metrics.get(metric_key)
            if value is None:
                continue
            cell = gspread.utils.rowcol_to_a1(row, col)
            updates.append((cell, _format_value(metric_key, value)))

    if not updates:
        return log + [f"[SKIP] {label}: nothing to write"]

    if dry_run:
        log.append(f"[DRY-RUN] {label}: would write {len(updates)} cells across {len(week_data)} weeks")
        for cell, val in updates:
            log.append(f"    {cell} <- {val}")
    else:
        _retry(ws.batch_update, [
            {"range": cell, "values": [[val]]}
            for cell, val in updates
        ], value_input_option="USER_ENTERED")
        log.append(f"[OK] {label}: wrote {len(updates)} cells across {len(week_data)} weeks")
    return log


def fill_office_tab(
    sh: gspread.Spreadsheet,
    tab_name: str,
    week_data: Dict[dt.date, Dict[str, Optional[float]]],
    dry_run: bool,
) -> List[str]:
    """Convenience wrapper: write data into the PRIMARY section (top of tab).
    For multi-office tabs, callers should iterate sections themselves and
    use fill_office_section() with per-section metric_rows."""
    log: List[str] = []
    try:
        ws = sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        return [f"[SKIP] tab not found: {tab_name!r}"]

    if not is_office_tab_populated(ws):
        log.append(f"  {tab_name}: tab is empty; injecting Template Fiber…")
        if not dry_run:
            inject_template(sh, tab_name)
        ws = sh.worksheet(tab_name)

    metric_rows = find_office_metric_rows(ws)
    if not metric_rows:
        return log + [f"[SKIP] {tab_name}: no metric rows found"]

    values = _retry(ws.get_all_values)
    sunday_to_col = find_sunday_columns(values, header_row_idx=0)

    return log + fill_office_section(ws, metric_rows, sunday_to_col, week_data, dry_run, label=tab_name)


# ---------- master tab fill ----------

def fill_master_row(
    sh: gspread.Spreadsheet,
    office_name: str,
    sunday: dt.date,
    metrics: Dict[str, Optional[float]],
    dry_run: bool,
) -> List[str]:
    """Update the master Raf Hidalgo tab's row for one office, single week."""
    log: List[str] = []
    try:
        ws = sh.worksheet(MASTER_TAB)
    except gspread.WorksheetNotFound:
        return [f"[SKIP] master tab not found"]

    values = _retry(ws.get_all_values)
    if len(values) < 2:
        return [f"[SKIP] master tab too short"]

    targets = {t.strip() for t in format_sunday(sunday)}
    date_cols = [i for i, c in enumerate(values[0], start=1) if str(c).strip() in targets]
    if not date_cols:
        return [f"[SKIP] master: no row-1 column for week {sunday.isoformat()}"]

    header_to_col: Dict[str, int] = {}
    for col_idx in date_cols:
        if len(values[1]) >= col_idx:
            header = str(values[1][col_idx - 1]).strip().lower()
            header_to_col[header] = col_idx

    # Find the office's row by scanning column B (ICD Name)
    office_row: Optional[int] = None
    target_name_lower = office_name.strip().lower()
    for row_idx, row in enumerate(values, start=1):
        if len(row) >= 2 and (row[1] or "").strip().lower() == target_name_lower:
            office_row = row_idx
            break
    if office_row is None:
        return [f"[SKIP] master: office row not found for {office_name!r}"]

    updates: List[Tuple[str, str]] = []
    for metric_key, header in MASTER_METRIC_TO_HEADER.items():
        col = header_to_col.get(header.lower())
        value = metrics.get(metric_key)
        if col is None or value is None:
            continue
        cell = gspread.utils.rowcol_to_a1(office_row, col)
        updates.append((cell, _format_value(metric_key, value)))

    if not updates:
        return log + [f"[SKIP] master {office_name}: nothing to write"]

    if dry_run:
        log.append(f"[DRY-RUN] master {office_name} ({sunday}): would write {len(updates)} cells")
    else:
        ws.batch_update([
            {"range": cell, "values": [[val]]}
            for cell, val in updates
        ], value_input_option="USER_ENTERED")
        log.append(f"[OK] master {office_name} ({sunday}): wrote {len(updates)} cells")
    return log


# ---------- helpers for run.py ----------

def list_template_columns(sh: gspread.Spreadsheet) -> List[dt.date]:
    """Return all Sunday dates that exist as column headers in Template Fiber.
    Used to drive backfill on newly-injected office tabs."""
    template = sh.worksheet(TEMPLATE_TAB)
    cols = find_sunday_columns(_retry(template.get_all_values), header_row_idx=0)
    return sorted(cols.keys())


if __name__ == "__main__":
    print("This module is intended to be imported by run.py, not run directly.")
    sys.exit(1)

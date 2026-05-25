"""Daily Recruiting Focus Report.

Fills the "Daily Focus Report" tab with per-ICD daily breakdowns (Mon-Fri)
of the recruiting funnel metrics. Source: AppStream Retention Details
report, scraped per office.

Conventions:
  - The ICD list is read from column V (col 22) of the Daily Focus Report tab.
  - Each ICD has its own SECTION on the tab, starting where col C contains
    "<ICD short name>\\nCurrent Week".
  - Section layout (relative to anchor row, anchor=0):
      offset 0: ICD name + "Current Week" / "Last Week" headers
      offset 2: "Office Focus Report" / "Monday".."Friday"/"Total"/"Next Week"
      offset 3: day-of-month numbers
      offsets 4-22: 19 metric rows
  - Day cell columns within Current Week section: Mon=4, Tue=5, ..., Fri=8,
    Total=9. Within Last Week section: Mon=13, ..., Fri=17, Total=18.
  - On Wednesdays we copy current-week values to last-week before refilling
    current week (Maud's stated workflow).

Run:
    .venv/bin/python -m automations.recruiting_report.daily_focus --captainship Raf
    .venv/bin/python -m automations.recruiting_report.daily_focus --captainship Carlos
    .venv/bin/python -m automations.recruiting_report.daily_focus --captainship Raf --dry-run
    .venv/bin/python -m automations.recruiting_report.daily_focus --captainship Raf --only "Tevin Sterling"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gspread
from playwright.sync_api import sync_playwright

from . import fetch_office, fill

ICD_LIST_COLUMN = 22  # col V

# Each captainship's Daily Focus report is one tab in the shared
# "Daily Focus Report - Raf/Carlos" spreadsheet. The report process is
# identical per captainship — only the AppStream account logged in (and
# therefore which ICDs are reachable) differs. The tab name == the
# captainship name.
DAILY_FOCUS_SPREADSHEET_ID = "11FRYGG1hvuxcbWiYtDv7LzVss6ujZE_SOpqfhrQrVAo"
CAPTAINSHIPS = ["Raf", "Carlos"]
DEFAULT_CAPTAINSHIP = "Raf"

# Sidecar state file, one per captainship: tracks which ICDs the *most
# recent* run couldn't pull because the logged-in AppStream account has no
# access to them. The dashboard reads this to list the skipped ICDs and
# power the "retry just those" button.
_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"

# User-managed ICD-name → office-id overrides. The dashboard pops a confirm
# dialog whenever a new name appears in col V; once the user picks an office,
# it's persisted here so we never ask again. Sentinel "__SKIP__" marks rows
# the user told us aren't real ICDs (e.g. header text) — those names are
# silently ignored on every run.
OVERRIDES_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "icd_office_mappings.json"
SKIP_SENTINEL = "__SKIP__"

# Section structure
METRICS_START_OFFSET = 4   # row 5 is first metric (relative to anchor=row 1 of section)
METRICS_END_OFFSET = 22    # last metric is ~22 rows below anchor

# Day → column index inside Current Week and Last Week sections
CURRENT_WEEK_DAY_COLUMNS = {
    "monday": 4, "tuesday": 5, "wednesday": 6, "thursday": 7, "friday": 8,
}
CURRENT_WEEK_TOTAL_COLUMN = 9
CURRENT_WEEK_NEXT_WEEK_COLUMN = 10

LAST_WEEK_DAY_COLUMNS = {
    "monday": 13, "tuesday": 14, "wednesday": 15, "thursday": 16, "friday": 17,
}
LAST_WEEK_TOTAL_COLUMN = 18

# Metrics that get a "Next Week" projection (forward-looking scheduled counts)
NEXT_WEEK_METRICS = ["second_booked", "new_starts_scheduled"]

# Map the row label as it appears in col C of the Daily Focus Report tab
# to our canonical metric key.
DAILY_LABEL_TO_METRIC = {
    "sent to call list - apps / pull":   "pull",
    "removed from process emails":       "removed_from_process_emails",
    "total applies":                     "total_applies",
    "duplicate %":                       "duplicate_pct",
    "retention to call list":            "pct_apps_booked_first",
    "1st rds showed up":                 "first_showed",
    "1st rds scheduled":                 "first_booked",
    "1st rd retention":                  "pct_first_retention",
    "% of 1st rds booked for 2nd":       "pct_first_showed_booked_2nd",
    "2nd rds showed up":                 "second_showed",
    "2nd rds scheduled":                 "second_booked",
    "2nd rd retention":                  "pct_second_retention",
    "job offered":                       "job_offered",
    "bob":                               "bob",
    "job offered retention":             "pct_job_offered_retention",
    "bob %":                             "pct_bob_conversion",
    "new starts showed":                 "new_starts_showed",
    "new starts scheduled":              "new_starts_scheduled",
    "new start retention":               "pct_new_start_retention",
}

# Manual short-name → office_id map. Short names from col 22 of the Daily
# Focus Report tab; office_ids from our existing mapping. Megan can edit
# this to add more ICDs.
ICD_NAME_TO_OFFICE_ID = {
    # Full names as they appear in AppStream (and in col 22 of the Daily Focus Report tab).
    "tevin sterling":     "22990",
    "jacob morgan":       "22597",
    "jennifer figueroa":  "23132",
    "nii tagoe":          "23275",
    "melik el jaiez":     "23265",
    "kiarri mcbroom":     "23139",
    "natalia gwarda":     "23431",
    "haytham nagi":       "22524",
    "joseph logan":       "23376",
    "marcellus butler":   "22069",
    "edgar muniz ii":     "23377",
    "tre mitchell":       "21182",  # AS owner: Lamar Mitchell III
    "german lopez":       "22797",
    "steve mcelwee":      "23160",
    "carissa ng":         "23402",
    "drew tepper":        "22583",
    "maxamad aden":       "23066",
}
# Backwards-compatible alias
SHORT_NAME_TO_OFFICE_ID = ICD_NAME_TO_OFFICE_ID


RAW_COUNT_METRICS = [
    "sent_to_call_list", "removed_from_process_emails", "emails_received",
    "manual_apps_entry", "first_booked", "first_showed",
    "second_booked", "second_showed", "job_offered", "bob",
    "new_starts_scheduled", "new_starts_showed",
]

# For percent metrics, the Total column should be (num_total / den_total),
# NOT sum of daily percentages. Map each percent metric to its underlying
# numerator + denominator metric rows. Metrics not listed fall back to
# per-day-average behavior (less correct but at least not nonsense).
PERCENT_TOTAL_FORMULA = {
    "duplicate_pct":               ("removed_from_process_emails", "pull"),
    "pct_apps_booked_first":       ("first_booked", "pull"),  # approximation
    "pct_first_retention":         ("first_showed", "first_booked"),
    "pct_first_showed_booked_2nd": ("second_booked", "first_showed"),
    "pct_second_retention":        ("second_showed", "second_booked"),
    "pct_job_offered_retention":   ("job_offered", "second_showed"),
    "pct_bob_conversion":          ("bob", "job_offered"),
    "pct_new_start_retention":     ("new_starts_showed", "new_starts_scheduled"),
}


def _combine_weekend_into_weekdays(daily: Dict[str, Dict[str, Optional[float]]]) -> Dict[str, Dict[str, Optional[float]]]:
    """Per Raf's rule: Saturday's numbers roll into Friday's column,
    Sunday's into Monday's. Combine raw counts; recompute derived percentages
    from the combined counts."""

    def merge(metric: str, *days):
        vals = [daily.get(metric, {}).get(d) for d in days]
        if all(v is None for v in vals):
            return None
        return int(sum(v or 0 for v in vals))

    def take(metric, day):
        return daily.get(metric, {}).get(day)

    def safe_pct(num, den):
        if num is None or den is None:
            return None
        if not den:
            return 0
        return round((num / den) * 100)

    out: Dict[str, Dict[str, Optional[float]]] = {}

    # Raw counts: combine Sun+Mon → Mon, Fri+Sat → Fri; pass through Tue/Wed/Thu
    for m in RAW_COUNT_METRICS:
        out[m] = {
            "monday":    merge(m, "sunday", "monday"),
            "tuesday":   take(m, "tuesday"),
            "wednesday": take(m, "wednesday"),
            "thursday":  take(m, "thursday"),
            "friday":    merge(m, "friday", "saturday"),
        }

    # Derived metrics: recompute from combined raw counts per day
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]

    out["pull"] = {d: (None if (out["sent_to_call_list"][d] is None and out["manual_apps_entry"][d] is None)
                       else int((out["sent_to_call_list"][d] or 0) + (out["manual_apps_entry"][d] or 0))) for d in weekdays}

    out["total_applies"] = {d: (None if (out["pull"][d] is None and out["removed_from_process_emails"][d] is None)
                                else int((out["pull"][d] or 0) + (out["removed_from_process_emails"][d] or 0))) for d in weekdays}

    out["duplicate_pct"] = {d: safe_pct(out["removed_from_process_emails"][d], out["pull"][d]) for d in weekdays}
    out["pct_first_retention"] = {d: safe_pct(out["first_showed"][d], out["first_booked"][d]) for d in weekdays}
    out["pct_second_retention"] = {d: safe_pct(out["second_showed"][d], out["second_booked"][d]) for d in weekdays}
    out["pct_new_start_retention"] = {d: safe_pct(out["new_starts_showed"][d], out["new_starts_scheduled"][d]) for d in weekdays}
    out["pct_job_offered_retention"] = {d: safe_pct(out["job_offered"][d], out["second_showed"][d]) for d in weekdays}
    out["pct_bob_conversion"] = {d: safe_pct(out["bob"][d], out["job_offered"][d]) for d in weekdays}

    # AS-direct percents — daily values come straight from AppStream "Retention" rows.
    # Totals are weighted division (handled in fill_icd_section via PERCENT_TOTAL_FORMULA).
    for m in ["pct_apps_booked_first", "pct_first_showed_booked_2nd"]:
        out[m] = {d: take(m, d) for d in weekdays}

    return out


def _format_value(metric: str, value) -> str:
    """Format a metric value for the Sheet. None becomes 0 (or 0%) so cells
    are never blank — Megan's preference for the daily focus report."""
    if value is None:
        return "0%" if metric in fill.PERCENT_METRICS else "0"
    if metric in fill.PERCENT_METRICS:
        return f"{int(round(float(value)))}%"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _read_icd_list(ws: gspread.Worksheet) -> List[str]:
    """Return the ICDs listed in col 22 (skipping header / blanks)."""
    col = fill._retry(ws.col_values, ICD_LIST_COLUMN)
    icds = []
    for v in col:
        v = (v or "").strip()
        if not v or "office to fill" in v.lower():
            continue
        icds.append(v)
    return icds


SECTION_HEIGHT = 24  # rows per ICD section


def _find_last_section_anchor(col3: List[str]) -> Optional[int]:
    """Highest row in col C containing 'Current Week'."""
    last = None
    for row_idx, val in enumerate(col3, start=1):
        if val and "current week" in val.lower():
            last = row_idx
    return last


def _ensure_sections(
    ws: gspread.Worksheet,
    icds: List[str],
    col3: List[str],
    dry_run: bool,
    log: logging.Logger,
) -> List[str]:
    """For each ICD without a section, clone the first existing section and
    append it at the bottom of the tab. Returns updated col3 values."""
    missing = []
    for icd in icds:
        if not _find_section_anchor(col3, icd):
            missing.append(icd)
    if not missing:
        return col3

    # Dedupe the missing list — if col 22 had duplicate entries (e.g. from a
    # previous bug), don't create the same section multiple times.
    seen = set()
    missing_unique = []
    for icd in missing:
        if icd not in seen:
            seen.add(icd)
            missing_unique.append(icd)
    missing = missing_unique

    log.info("creating %d new section(s) for: %s", len(missing), missing)
    if dry_run:
        log.info("  [DRY-RUN] would clone first section (with formatting) for each missing ICD")
        return col3

    last_anchor = _find_last_section_anchor(col3) or 1
    next_anchor = last_anchor + SECTION_HEIGHT

    # Resize sheet if needed
    needed_rows = next_anchor + (SECTION_HEIGHT * len(missing))
    if ws.row_count < needed_rows:
        fill._retry(ws.resize, rows=needed_rows, cols=ws.col_count)

    sheet_id = ws.id
    for icd in missing:
        # Use Sheets API copyPaste to clone formatting + values from rows 1-24
        # (only cols A-T; col V-W is the ICD list and must NOT be duplicated).
        copy_request = {
            "requests": [{
                "copyPaste": {
                    "source": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": SECTION_HEIGHT,
                        "startColumnIndex": 0,
                        "endColumnIndex": 20,
                    },
                    "destination": {
                        "sheetId": sheet_id,
                        "startRowIndex": next_anchor - 1,
                        "endRowIndex": next_anchor + SECTION_HEIGHT - 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 20,
                    },
                    "pasteType": "PASTE_NORMAL",
                }
            }]
        }
        fill._retry(ws.spreadsheet.batch_update, copy_request)

        # Update headers with the new ICD name
        header_updates = [
            {"range": f"C{next_anchor}", "values": [[f"{icd}\nCurrent Week"]]},
            {"range": f"L{next_anchor}", "values": [[f"{icd}\nLast Week"]]},
        ]
        fill._retry(ws.batch_update, header_updates, value_input_option="USER_ENTERED")

        # Clear data cells (cols D-I + M-R, metric rows) so we don't carry over
        # the template's data values. Formatting is preserved.
        first_metric = next_anchor + METRICS_START_OFFSET
        last_metric = next_anchor + METRICS_END_OFFSET
        fill._retry(ws.batch_clear, [
            f"D{first_metric}:I{last_metric}",
            f"M{first_metric}:R{last_metric}",
        ])

        log.info("  created section for %s at rows %d-%d (with formatting)",
                 icd, next_anchor, next_anchor + SECTION_HEIGHT - 1)
        next_anchor += SECTION_HEIGHT

    # Re-read col3 so callers see the new sections
    return fill._retry(ws.col_values, 3)


def _read_all_sections(ws: gspread.Worksheet, col3: List[str]) -> List[Tuple[str, int, List[List[str]]]]:
    """Return list of (icd_name, anchor_row, section_data_24x20). Section data
    excludes cols 21+ (V/W are the ICD list, independent of sections)."""
    sections = []
    for row_idx, val in enumerate(col3, start=1):
        if val and "current week" in val.lower():
            icd_name = val.split("\n")[0].strip()
            data = fill._retry(ws.get, f"A{row_idx}:T{row_idx + SECTION_HEIGHT - 1}")
            padded = []
            for r in data:
                padded.append(list(r) + [""] * (20 - len(r)))
            while len(padded) < SECTION_HEIGHT:
                padded.append([""] * 20)
            sections.append((icd_name, row_idx, padded))
    return sections


def _sort_sections_alphabetically(
    ws: gspread.Worksheet,
    sections: List[Tuple[str, int, List[List[str]]]],
    dry_run: bool,
    log: logging.Logger,
) -> None:
    """Reorder sections in-place so they appear alphabetically by ICD name.
    Each section is rewritten at the same anchor row positions, in sorted
    order. Cols V-W (ICD list) are not touched here."""
    if len(sections) < 2:
        return
    sorted_secs = sorted(sections, key=lambda s: s[0].lower())
    if [s[0] for s in sections] == [s[0] for s in sorted_secs]:
        log.info("sections already alphabetical")
        return
    log.info("sorting sections: %s -> %s",
             [s[0] for s in sections], [s[0] for s in sorted_secs])
    if dry_run:
        return
    for new_idx, (_, _, data) in enumerate(sorted_secs):
        anchor = sections[new_idx][1]  # original row positions, sorted content
        target_range = f"A{anchor}:T{anchor + SECTION_HEIGHT - 1}"
        fill._retry(ws.update, data, target_range, value_input_option="USER_ENTERED")


def _sort_icd_list_alphabetically(
    ws: gspread.Worksheet,
    dry_run: bool,
    log: logging.Logger,
) -> None:
    """Sort col V (ICD names) + col W (Upline) pairs alphabetically by ICD
    name. Header row 1 is preserved."""
    col22 = fill._retry(ws.col_values, 22)
    col23 = fill._retry(ws.col_values, 23)
    pairs = []
    rows_used = []
    for i in range(1, max(len(col22), len(col23))):  # skip row 1 header
        v22 = (col22[i] if i < len(col22) else "").strip()
        v23 = (col23[i] if i < len(col23) else "").strip()
        if v22 and "office to fill" not in v22.lower():
            pairs.append((v22, v23))
            rows_used.append(i + 1)
    if len(pairs) < 2:
        return
    sorted_pairs = sorted(pairs, key=lambda p: p[0].lower())
    if pairs == sorted_pairs:
        log.info("ICD list already alphabetical")
        return
    log.info("sorting ICD list: %s -> %s", [p[0] for p in pairs], [p[0] for p in sorted_pairs])
    if dry_run:
        return
    updates = []
    for new_idx, (v22, v23) in enumerate(sorted_pairs):
        row = rows_used[new_idx]
        updates.append({"range": f"V{row}", "values": [[v22]]})
        updates.append({"range": f"W{row}", "values": [[v23]]})
    fill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")


def _find_section_anchor(col3: List[str], icd_name: str) -> Optional[int]:
    """Find row containing '<icd_name>\\nCurrent Week' in col C. Returns 1-indexed row."""
    needle = icd_name.strip().lower()
    loose = None
    for row_idx, val in enumerate(col3, start=1):
        if not val:
            continue
        cleaned = val.strip().lower()
        if "current week" not in cleaned:
            continue
        # Match the ICD-name portion exactly so 'George Hipolito' doesn't also
        # grab the 'George Hipolito 2' section. The loose contains-match is
        # kept only as a fallback for an oddly-labelled hand-made section.
        if cleaned.split("current week")[0].strip() == needle:
            return row_idx
        if loose is None and needle in cleaned:
            loose = row_idx
    return loose


def _find_metric_rows_in_section(col3: List[str], anchor_row: int) -> Dict[str, int]:
    """Within one ICD section, find the row for each metric we care about."""
    result: Dict[str, int] = {}
    end_row = min(anchor_row + 1 + METRICS_END_OFFSET, len(col3) + 1)
    start_row = anchor_row + METRICS_START_OFFSET
    for row_idx in range(start_row, end_row + 1):
        if row_idx > len(col3):
            break
        val = (col3[row_idx - 1] or "").strip().lower()
        if not val:
            continue
        for label, metric in DAILY_LABEL_TO_METRIC.items():
            if metric in result:
                continue
            if val == label or val.startswith(label):
                result[metric] = row_idx
                break
    return result


def _is_first_run_of_week(
    ws: gspread.Worksheet,
    anchor_row: int,
    week_start: dt.date,
) -> bool:
    """Returns True if the section's date row doesn't reflect the current week
    yet (meaning we should copy current→last + clear current before refilling).

    Heuristic: the first day-of-month in current-week date row (col 4 of
    anchor+3) should equal the day-of-month of this week's Monday."""
    expected_monday = (week_start + dt.timedelta(days=1)).day
    try:
        row_vals = fill._retry(ws.row_values, anchor_row + 3)
    except Exception:
        return True
    cell = row_vals[3].strip() if len(row_vals) > 3 else ""
    if not cell:
        return True
    try:
        return int(cell) != expected_monday
    except ValueError:
        return True


def _clear_current_week(
    ws: gspread.Worksheet,
    metric_rows: Dict[str, int],
    dry_run: bool,
) -> int:
    """Clear current week DAILY cells (cols D-H, Mon-Fri). Preserves the
    Total column (col I) which contains formulas."""
    if not metric_rows:
        return 0
    rows_sorted = sorted(metric_rows.values())
    first_row, last_row = rows_sorted[0], rows_sorted[-1]
    target_range = f"D{first_row}:H{last_row}"
    if dry_run:
        return (last_row - first_row + 1) * 5
    blank = [["" for _ in range(5)] for _ in range(last_row - first_row + 1)]
    fill._retry(ws.update, blank, target_range, value_input_option="USER_ENTERED")
    return (last_row - first_row + 1) * 5


def _clear_last_week(
    ws: gspread.Worksheet,
    metric_rows: Dict[str, int],
    dry_run: bool,
) -> int:
    """Clear last week DAILY cells (cols M-Q, Mon-Fri). Preserves col R (Total)."""
    if not metric_rows:
        return 0
    rows_sorted = sorted(metric_rows.values())
    first_row, last_row = rows_sorted[0], rows_sorted[-1]
    target_range = f"M{first_row}:Q{last_row}"
    if dry_run:
        return (last_row - first_row + 1) * 5
    blank = [["" for _ in range(5)] for _ in range(last_row - first_row + 1)]
    fill._retry(ws.update, blank, target_range, value_input_option="USER_ENTERED")
    return (last_row - first_row + 1) * 5


def fill_icd_section_last_week(
    ws: gspread.Worksheet,
    icd_name: str,
    metric_rows: Dict[str, int],
    daily_data: Dict[str, Dict[str, Optional[float]]],
    dry_run: bool,
) -> List[str]:
    """Write per-day values into one ICD's LAST WEEK section (cols M-Q).
    Totals (col R) are computed in Python (same logic as current week)."""
    log = []
    updates: List[Tuple[str, str]] = []
    weekdays = list(LAST_WEEK_DAY_COLUMNS.keys())
    for metric_key, row in metric_rows.items():
        per_day = daily_data.get(metric_key, {})
        for day, col in LAST_WEEK_DAY_COLUMNS.items():
            value = per_day.get(day)
            cell = gspread.utils.rowcol_to_a1(row, col)
            updates.append((cell, _format_value(metric_key, value)))
        total_cell = gspread.utils.rowcol_to_a1(row, LAST_WEEK_TOTAL_COLUMN)
        if metric_key in PERCENT_TOTAL_FORMULA:
            num_metric, den_metric = PERCENT_TOTAL_FORMULA[metric_key]
            num_total = sum((daily_data.get(num_metric, {}).get(d) or 0) for d in weekdays)
            den_total = sum((daily_data.get(den_metric, {}).get(d) or 0) for d in weekdays)
            pct = round(num_total / den_total * 100) if den_total else 0
            updates.append((total_cell, f"{pct}%"))
        elif metric_key in fill.PERCENT_METRICS:
            vals = [daily_data.get(metric_key, {}).get(d) for d in weekdays]
            non_null = [v for v in vals if v is not None]
            avg = round(sum(non_null) / len(non_null)) if non_null else 0
            updates.append((total_cell, f"{avg}%"))
        else:
            total = sum((daily_data.get(metric_key, {}).get(d) or 0) for d in weekdays)
            updates.append((total_cell, str(int(total))))
    if not updates:
        return [f"[SKIP] {icd_name} (last week): nothing to write"]
    if dry_run:
        log.append(f"[DRY-RUN] {icd_name} (last week): would write {len(updates)} cells")
    else:
        fill._retry(ws.batch_update, [
            {"range": cell, "values": [[val]]} for cell, val in updates
        ], value_input_option="USER_ENTERED")
        log.append(f"[OK] {icd_name} (last week): wrote {len(updates)} cells")
    return log


def _copy_current_to_last(
    ws: gspread.Worksheet,
    metric_rows: Dict[str, int],
    dry_run: bool,
) -> int:
    """For each metric row, copy values from cols 4-9 (current week) to
    cols 13-18 (last week). Returns the number of cells copied."""
    if not metric_rows:
        return 0
    rows_sorted = sorted(metric_rows.values())
    first_row, last_row = rows_sorted[0], rows_sorted[-1]
    # Read source range D{first}:I{last} (cols 4-9, current week + total)
    source_range = f"D{first_row}:I{last_row}"
    target_range = f"M{first_row}:R{last_row}"  # cols 13-18
    src = fill._retry(ws.get, source_range)
    if not src:
        return 0
    if dry_run:
        return sum(1 for row in src for cell in row if cell)
    fill._retry(ws.update, src, target_range, value_input_option="USER_ENTERED")
    return sum(1 for row in src for cell in row if cell)


def _update_date_row(
    ws: gspread.Worksheet,
    anchor_row: int,
    week_start: dt.date,
    last_week_start: dt.date,
    dry_run: bool,
) -> List[str]:
    """Update row (anchor + 3) with day-of-month for current week (cols 4-8)
    and last week (cols 13-17) Mon-Fri dates."""
    date_row = anchor_row + 3
    # Mon-Fri of current week = week_start + 1 ... +5
    current_days = [(week_start + dt.timedelta(days=i + 1)).day for i in range(5)]
    last_days = [(last_week_start + dt.timedelta(days=i + 1)).day for i in range(5)]
    updates = []
    for offset, day in enumerate(current_days):
        col = 4 + offset
        cell = gspread.utils.rowcol_to_a1(date_row, col)
        updates.append((cell, str(day)))
    for offset, day in enumerate(last_days):
        col = 13 + offset
        cell = gspread.utils.rowcol_to_a1(date_row, col)
        updates.append((cell, str(day)))
    if dry_run:
        return [f"  [DRY-RUN] would update date row: current={current_days}, last={last_days}"]
    fill._retry(ws.batch_update, [
        {"range": cell, "values": [[val]]} for cell, val in updates
    ], value_input_option="USER_ENTERED")
    return [f"  updated date row: current={current_days}, last={last_days}"]


def fill_icd_section(
    ws: gspread.Worksheet,
    icd_name: str,
    anchor_row: int,
    metric_rows: Dict[str, int],
    daily_data: Dict[str, Dict[str, Optional[float]]],
    dry_run: bool,
) -> List[str]:
    """Write per-day values into one ICD's Current Week section."""
    log = []
    updates: List[Tuple[str, str]] = []
    weekdays = list(CURRENT_WEEK_DAY_COLUMNS.keys())
    for metric_key, row in metric_rows.items():
        per_day = daily_data.get(metric_key, {})
        for day, col in CURRENT_WEEK_DAY_COLUMNS.items():
            value = per_day.get(day)
            cell = gspread.utils.rowcol_to_a1(row, col)
            updates.append((cell, _format_value(metric_key, value)))
        # Total column (col I) — computed in Python:
        #   - count metric: SUM of daily values
        #   - percent metric with known num/den: weighted division
        #   - other percent (no clean num/den): average of daily values
        total_cell = gspread.utils.rowcol_to_a1(row, CURRENT_WEEK_TOTAL_COLUMN)
        if metric_key in PERCENT_TOTAL_FORMULA:
            num_metric, den_metric = PERCENT_TOTAL_FORMULA[metric_key]
            num_total = sum((daily_data.get(num_metric, {}).get(d) or 0) for d in weekdays)
            den_total = sum((daily_data.get(den_metric, {}).get(d) or 0) for d in weekdays)
            pct = round(num_total / den_total * 100) if den_total else 0
            updates.append((total_cell, f"{pct}%"))
        elif metric_key in fill.PERCENT_METRICS:
            # Average of non-zero daily percentages (avoids deflating by empty days)
            vals = [daily_data.get(metric_key, {}).get(d) for d in weekdays]
            non_null = [v for v in vals if v is not None]
            avg = round(sum(non_null) / len(non_null)) if non_null else 0
            updates.append((total_cell, f"{avg}%"))
        else:
            total = sum((daily_data.get(metric_key, {}).get(d) or 0) for d in weekdays)
            updates.append((total_cell, str(int(total))))

    if not updates:
        return [f"[SKIP] {icd_name}: nothing to write"]

    if dry_run:
        log.append(f"[DRY-RUN] {icd_name}: would write {len(updates)} cells")
        for cell, val in updates[:10]:
            log.append(f"    {cell} <- {val}")
        if len(updates) > 10:
            log.append(f"    … and {len(updates) - 10} more")
    else:
        fill._retry(ws.batch_update, [
            {"range": cell, "values": [[val]]} for cell, val in updates
        ], value_input_option="USER_ENTERED")
        log.append(f"[OK] {icd_name}: wrote {len(updates)} cells")
    return log


def _load_overrides() -> dict:
    """Read user-confirmed ICD→office-id overrides. Returns {} if missing
    or unreadable. Keys are lowercased ICD names; values are office-id
    strings (or the SKIP_SENTINEL for non-ICD rows the user dismissed)."""
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(OVERRIDES_PATH.read_text())
        return {str(k).lower().strip(): str(v) for k, v in data.items()}
    except Exception:
        return {}


def _save_overrides(overrides: dict) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(
        {k: v for k, v in sorted(overrides.items())}, indent=2,
    ))


def _resolve_office_id(name: str) -> Optional[str]:
    """Return the office id for an ICD name, or None if unmapped/skipped.

    Order: user overrides (incl. SKIP sentinel) → hardcoded
    ICD_NAME_TO_OFFICE_ID. SKIP returns None so the caller skips the row
    without logging a 'no mapping' warning."""
    key = name.lower().strip()
    overrides = _load_overrides()
    if key in overrides:
        v = overrides[key]
        return None if v == SKIP_SENTINEL else v
    return ICD_NAME_TO_OFFICE_ID.get(key)


def _is_skipped(name: str) -> bool:
    """True if the user marked this name as 'not an ICD' in overrides."""
    return _load_overrides().get(name.lower().strip()) == SKIP_SENTINEL


def _state_file() -> Path:
    """Shared retry-state file — the skipped-ICD list from the last run, read
    by the Hub's 'Retry the skipped ICDs' button. One file: a merged run
    covers both captainships."""
    return _OUTPUT_DIR / "daily_focus_state.json"


def find_captainship_worksheet(sh, captainship: str):
    """Return the worksheet for a captainship. Matches any tab whose title
    contains the captainship name, case-insensitive — so 'Carlos' finds a
    tab named 'Carlos Hidalgo' and the lookup survives minor tab renames.
    Returns None if no tab matches."""
    needle = captainship.lower().strip()
    for ws in sh.worksheets():
        if needle in (ws.title or "").lower():
            return ws
    return None


def _read_state() -> dict:
    sf = _state_file()
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text())
    except Exception:
        return {}


def _write_state(inaccessible: List[str], week_start: dt.date,
                 denied: List[str] | None = None,
                 fetch_errors: List[str] | None = None) -> None:
    """Persist the skipped-ICD lists. `denied` and `fetch_errors` are
    the two underlying buckets:
      - denied: AppStream genuinely refused access (cur_raw == {})
      - fetch_errors: transient Playwright/timeout errors (retry-recoverable)
    `inaccessible` is their union, kept for backward compat with older
    Hub builds that only read that key."""
    sf = _state_file()
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps({
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "week_start": week_start.isoformat(),
        "inaccessible": sorted(set(inaccessible)),
        "denied":       sorted(set(denied or [])),
        "fetch_errors": sorted(set(fetch_errors or [])),
    }, indent=2))


def _setup_logging(today: dt.date) -> logging.Logger:
    log_path = fill.MAPPING_PATH.parent.parent.parent / "output" / "logs" / f"daily-focus-{today.isoformat()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
    return logging.getLogger("daily-focus")


def run_captainship(captainship: str, args, week_start: dt.date,
                    log: logging.Logger) -> Tuple[int, dict]:
    """Fill the Daily Focus report for one captainship. Returns
    (return-code, skipped-ICDs dict) where the dict has keys:
      - "inaccessible": union of all skipped ICDs (legacy)
      - "denied":       ICDs AppStream refused (cur_raw == {})
      - "fetch_errors": ICDs that errored transiently (retry-recoverable)
    The caller merges these across captainships into one shared state file."""
    log.info("=== captainship: %s ===", captainship)
    sh = fill.open_by_key(DAILY_FOCUS_SPREADSHEET_ID)
    ws = find_captainship_worksheet(sh, captainship)
    if ws is None:
        log.error("no tab found for captainship %s in the daily-focus sheet "
                  "(looked for a tab whose name contains %r)", captainship, captainship)
        return 1, []
    log.info("using tab: %s", ws.title)

    icds = _read_icd_list(ws)
    if args.only:
        icds = [i for i in icds if i.lower() == args.only.lower()]
    if args.retry_inaccessible:
        prev = _read_state().get("inaccessible", [])
        prev_lower = {n.lower() for n in prev}
        icds = [i for i in icds if i.lower() in prev_lower]
        if not icds:
            log.info("retry-inaccessible: no skipped ICDs for %s — nothing to "
                     "retry.", captainship)
            return 0, {"inaccessible": [], "denied": [], "fetch_errors": []}
        log.info("retry-inaccessible mode: retrying %d ICD(s) from last run: %s",
                 len(icds), icds)
    log.info("ICDs to process: %s", icds)

    # Track ICDs that couldn't be pulled. Split into two buckets so the
    # Hub callout can tell the user the right fix (request access vs.
    # just retry). `inaccessible_this_run` is the union — kept for the
    # function's return-shape compatibility.
    inaccessible_this_run: List[str] = []
    denied_this_run: List[str] = []          # AppStream refused this account
    fetch_errors_this_run: List[str] = []    # transient Playwright/timeout

    col3 = fill._retry(ws.col_values, 3)

    # Auto-create sections for any ICDs in the list without one yet.
    # (Sort functions are defined but not called — Megan's preference.)
    col3 = _ensure_sections(ws, icds, col3, args.dry_run, log)

    p = sync_playwright().start()
    try:
        browser = p.chromium.connect_over_cdp(fetch_office.CDP_URL)
        target_page = None
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "applicantstream" in page.url:
                    target_page = page
                    break
            if target_page:
                break
        if not target_page:
            log.error("no applicantstream tab open in attached Chrome")
            return 1, []

        for icd in icds:
            if _is_skipped(icd):
                # User dismissed this row as 'not an ICD' (e.g. header text).
                # Silent skip — don't log a warning every run.
                continue
            office_id = _resolve_office_id(icd)
            if not office_id:
                log.warning("[%s] no office_id mapping — confirm it from the dashboard's "
                            "'Map new ICDs' prompt and re-run; skip for now", icd)
                continue

            anchor = _find_section_anchor(col3, icd)
            if not anchor:
                log.warning("[%s] no section anchor on tab; skip", icd)
                continue

            metric_rows = _find_metric_rows_in_section(col3, anchor)
            if not metric_rows:
                log.warning("[%s] no metric rows in section starting row %d; skip", icd, anchor)
                continue

            log.info("→ %s (office %s, anchor row %d, %d metric rows)",
                     icd, office_id, anchor, len(metric_rows))

            # Fetch CURRENT week FIRST so we know if the office is accessible.
            # Only clear + fill when fetch succeeds — preserves data for offices
            # that need the other AS account.
            #
            # 3 failure modes, each with a DIFFERENT cause/banner so the user
            # knows whether to request access or just retry:
            #   - exception during fetch  -> fetch_errors  (transient, retry)
            #   - cur_raw == {}           -> denied        (real access issue)
            #   - cur_raw is falsy/empty  -> fetch_errors  (transient, retry)
            #
            # Retry transient errors ONCE before giving up — Raf + JR Young
            # have been flaking with timeout/empty pulls and a single retry
            # almost always recovers. Don't retry an empty-dict (real denial)
            # because that's a server answer, not a flake.
            last_week_start = week_start - dt.timedelta(days=7)

            def _try_current() -> tuple[object, str]:
                """Returns (raw_data, error_kind) where error_kind is one of
                'ok', 'denied', 'exception', 'empty'. raw_data only meaningful
                when error_kind == 'ok'."""
                try:
                    raw = fetch_office.fetch_one_daily(target_page, office_id, icd, week_start)
                except Exception as e:
                    log.exception("  fetch failed for %s (current): %s", icd, e)
                    return None, "exception"
                if raw == {}:
                    return None, "denied"
                if not raw:
                    return None, "empty"
                return raw, "ok"

            cur_raw, err = _try_current()
            if err in ("exception", "empty"):
                log.info("  retrying %s once after transient %s …", icd, err)
                cur_raw, err = _try_current()
                if err == "ok":
                    log.info("  ✓ %s recovered on retry", icd)

            if err == "exception":
                log.warning("  %s still failing after retry — flagged as transient fetch error", icd)
                fetch_errors_this_run.append(icd)
                inaccessible_this_run.append(icd)
                continue
            if err == "denied":
                log.warning("  not accessible from current AS account; skip (data preserved)")
                denied_this_run.append(icd)
                inaccessible_this_run.append(icd)
                continue
            if err == "empty":
                log.warning("  empty current fetch after retry; flagged as transient fetch error")
                fetch_errors_this_run.append(icd)
                inaccessible_this_run.append(icd)
                continue

            # Office is accessible for current week — clear + fill current.
            # Last week's cells are NOT cleared yet: we only clear them once
            # we have last-week data in hand (line below). Otherwise a
            # transient last-week fetch failure would leave the section
            # empty (Maud's incident 2026-05-21: 5 ICDs lost last-week data
            # because the clear ran before a flaky fetch).
            cleared_c = _clear_current_week(ws, metric_rows, args.dry_run)
            log.info("  cleared %d current-week daily cells", cleared_c)

            # Update day-of-month numbers in the section's date row
            for line in _update_date_row(ws, anchor, week_start, last_week_start, args.dry_run):
                log.info(line)

            # Fetch LAST week's data (Maud needs both each run). Same
            # retry-once-on-transient as current — Khalil and others were
            # silently dropping last-week data when the first fetch flaked.
            # Track failures so retry-inaccessible re-pulls those ICDs too.
            def _try_last() -> tuple[object, str]:
                try:
                    raw = fetch_office.fetch_one_daily(target_page, office_id, icd, last_week_start)
                except Exception as e:
                    log.exception("  fetch failed for %s (last week): %s", icd, e)
                    return None, "exception"
                if raw == {}:
                    return None, "denied"
                if not raw:
                    return None, "empty"
                return raw, "ok"

            last_raw, last_err = _try_last()
            if last_err in ("exception", "empty"):
                log.info("  retrying %s (last week) once after transient %s …", icd, last_err)
                last_raw, last_err = _try_last()
                if last_err == "ok":
                    log.info("  ✓ %s (last week) recovered on retry", icd)

            if last_err != "ok":
                # Last-week pull failed even after retry. Current week is fine,
                # so we still fill it — but flag the ICD so retry-inaccessible
                # tries again. CRITICAL: we never cleared last week's cells
                # here, so existing data stays intact (preserves the prior
                # successful pull from an earlier run).
                log.warning("  %s (last week) failed after retry (%s) — last week's "
                            "existing data preserved; flagging for retry",
                            icd, last_err)
                fetch_errors_this_run.append(icd)
                inaccessible_this_run.append(icd)
                last_raw = None

            cur_daily = _combine_weekend_into_weekdays(cur_raw)
            for line in fill_icd_section(ws, icd, anchor, metric_rows, cur_daily, args.dry_run):
                log.info(line)

            if last_raw:
                # Only clear last week NOW that we have data to write into it.
                cleared_l = _clear_last_week(ws, metric_rows, args.dry_run)
                log.info("  cleared %d last-week daily cells (have fresh data to fill)", cleared_l)
                last_daily = _combine_weekend_into_weekdays(last_raw)
                for line in fill_icd_section_last_week(ws, icd, metric_rows, last_daily, args.dry_run):
                    log.info(line)

            # Fetch NEXT week (week_start + 7) for forward-looking scheduled counts
            next_week_start = week_start + dt.timedelta(days=7)
            try:
                next_weekly = fetch_office.fetch_one(target_page, office_id, icd, next_week_start)
            except Exception as e:
                log.exception("  fetch failed for %s (next week): %s", icd, e)
                next_weekly = {}
            if next_weekly:
                next_updates = []
                for metric_key in NEXT_WEEK_METRICS:
                    row = metric_rows.get(metric_key)
                    val = next_weekly.get(metric_key)
                    if row and val is not None:
                        cell = gspread.utils.rowcol_to_a1(row, CURRENT_WEEK_NEXT_WEEK_COLUMN)
                        next_updates.append((cell, _format_value(metric_key, val)))
                if next_updates:
                    if args.dry_run:
                        log.info("  [DRY-RUN] would write %d next-week cells", len(next_updates))
                    else:
                        fill._retry(ws.batch_update, [
                            {"range": c, "values": [[v]]} for c, v in next_updates
                        ], value_input_option="USER_ENTERED")
                        log.info("  wrote %d next-week scheduled cells", len(next_updates))

        # Keep the AppStream office list current — scrape this account's
        # offices into all-offices.json so new ICDs show up in the Hub's
        # mapping picker without anyone running a separate scrape.
        try:
            from automations.recruiting_report.list_all_offices import (
                refresh_offices_from_page,
            )
            log.info(refresh_offices_from_page(target_page))
        except Exception as e:
            log.warning("office-list refresh skipped: %s", e)
    finally:
        p.stop()

    if inaccessible_this_run:
        if denied_this_run:
            log.info("%s: %d ICD(s) denied by AppStream account: %s",
                     captainship, len(denied_this_run), ", ".join(denied_this_run))
        if fetch_errors_this_run:
            log.info("%s: %d ICD(s) had transient fetch errors (retry-recoverable): %s",
                     captainship, len(fetch_errors_this_run),
                     ", ".join(fetch_errors_this_run))

    log.info("done")
    return 0, {
        "inaccessible": inaccessible_this_run,
        "denied":       denied_this_run,
        "fetch_errors": fetch_errors_this_run,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--captainship", choices=CAPTAINSHIPS + ["all"],
                    default="all",
                    help="Which captainship to run, or 'all' (default) — "
                         "both Raf and Carlos in one run.")
    ap.add_argument("--week-start", help="Sunday at start of week to fetch (default: most recent past Sunday).")
    ap.add_argument("--only", help="Only one ICD (short name as in col 22).")
    ap.add_argument("--retry-inaccessible", action="store_true",
                    help="Only re-run the ICDs the last run flagged as not "
                         "pulled (rcaptain had no AppStream access yet). Run "
                         "this once that access has been granted.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-copy", action="store_true",
                    help="Skip the Wednesday copy-current-to-last step.")
    args = ap.parse_args()

    today = dt.date.today()
    log = _setup_logging(today)

    # Default: AS picker = most recent Sunday on or before today (current week's start)
    if args.week_start:
        week_start = dt.date.fromisoformat(args.week_start)
    else:
        week_start = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    log.info("week_start (AS picker Sunday) = %s", week_start.isoformat())
    log.info("today is %s", today.strftime("%A"))
    log.info("(copy current→last is auto-detected per ICD: triggered when "
             "section's date row doesn't match current week's Monday)")

    targets = CAPTAINSHIPS if args.captainship == "all" else [args.captainship]
    rc = 0
    skipped: List[str] = []
    denied: List[str] = []
    fetch_errors: List[str] = []
    for cs in targets:
        cs_rc, cs_result = run_captainship(cs, args, week_start, log)
        rc |= cs_rc
        skipped       += cs_result.get("inaccessible", [])
        denied        += cs_result.get("denied", [])
        fetch_errors  += cs_result.get("fetch_errors", [])

    # One shared retry-state file for the whole run — the Hub reads it to list
    # the skipped ICDs and power the "Retry the skipped ICDs" button. Not
    # written on --only / --dry-run (those aren't a full-list view).
    if not args.only and not args.dry_run:
        _write_state(skipped, week_start, denied=denied, fetch_errors=fetch_errors)
        if skipped:
            log.info("%d ICD(s) skipped this run — saved to %s for retry",
                     len(skipped), _state_file().name)
        else:
            log.info("all ICDs pulled — cleared retry state")
    return rc


if __name__ == "__main__":
    sys.exit(main())

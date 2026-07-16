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

# Make emoji / checkmarks safe on the Windows console (cp1252 default), so the
# Hub can run this on Eve's machine — same guard the other reports use.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import gspread

from . import fetch_office, fill

ICD_LIST_COLUMN = 22  # col V

# Each captainship's Daily Focus report is one tab in the shared
# Daily Focus spreadsheet. The report process is identical per
# captainship — only the AppStream account logged in (and therefore
# which ICDs are reachable) differs. Each entry is matched to its tab by
# substring of the tab title (find_captainship_worksheet), so the full
# name here finds the matching tab. Each captain owns their tab's col V
# list — add a name here to include that captain's tab in the run.
DAILY_FOCUS_SPREADSHEET_ID = "11FRYGG1hvuxcbWiYtDv7LzVss6ujZE_SOpqfhrQrVAo"
CAPTAINSHIPS = ["Raf", "Carlos", "Sahil Multani", "Chan Park", "Jose Antonio Chavez",
                "Colten Wright", "Jairo Ruiz"]
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
# Two-layer mappings (Megan 2026-06-25): the COMMITTED base file syncs the
# known-good ICD→office map to every machine via git, so the mini resolves the
# same ICDs the laptop does. The LOCAL (gitignored) output/ file layers on top
# for per-machine additions made through the Hub's "Map new ICDs" prompt — it
# stays gitignored on purpose so those writes never dirty the tree and block the
# mini's git self-update (the stale-code bug from this morning). Promote local
# additions into the base when you want to share them.
BASE_OVERRIDES_PATH = Path(__file__).resolve().parent / "icd_office_mappings.json"
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
    "roshan amin ahmad":  "19833",
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


def _rebuild_sections_from_list(
    ws: gspread.Worksheet,
    icds: List[str],
    col3: List[str],
    dry_run: bool,
    log: logging.Logger,
) -> List[str]:
    """Sync the tab's section body so one section exists per ICD in col V, in
    col V order. Sections whose ICD is no longer in col V are removed; new
    ICDs get a fresh blank section. The fetch loop that runs after this
    repopulates metric cells on every run, so we don't bother preserving
    in-section data (Megan 2026-05-26).

    Returns updated col3 values."""
    # Dedupe col V preserving order — guards against duplicate entries.
    seen = set()
    desired: List[str] = []
    for icd in icds:
        key = icd.lower()
        if key not in seen:
            seen.add(key)
            desired.append(icd)

    # Empty col V → refuse to rebuild. Rebuilding to zero sections would
    # blank A1:T0 (an invalid range → APIError 400, Eve glitch 2026-05-26)
    # AND would wipe every existing section. Empty almost always means the
    # ICD source/col V didn't populate this run, not that the tab should be
    # emptied — flag it and leave the tab untouched.
    if not desired:
        log.warning("col V has no ICDs for this tab — skipping section "
                    "rebuild (refusing to blank all sections). Check the "
                    "tab's col V / ICD source.")
        return col3

    existing = _read_all_sections(ws, col3)
    existing_names = [e[0] for e in existing]

    # No-op when the section order already matches col V exactly.
    if [n.lower() for n in existing_names] == [n.lower() for n in desired]:
        return col3

    if not existing:
        log.warning("no existing sections on tab — cannot bootstrap template; "
                    "manually add one section then re-run")
        return col3

    log.info("rebuilding sections to match col V: %s -> %s",
             existing_names, desired)
    # Empty col V -> rebuilding to 0 sections would (a) crash on the empty
    # 'A1:T0' range and (b) wipe every section on the tab. An empty list is
    # almost always a transient/empty-tab read, not a real "remove all ICDs" —
    # so skip the rebuild and leave the tab as-is (fixes the 'Unable to parse
    # range: …A1:T0' crash seen on a captainship with 0 ICDs to process).
    if not desired:
        log.warning("  col V resolved to 0 ICDs — skipping rebuild (won't wipe "
                    "existing sections; check this tab's col V list)")
        return col3
    if dry_run:
        log.info("  [DRY-RUN] would rewrite %d section header(s) + blank "
                 "metric cells (next fetch fills)", len(desired))
        return col3

    # Blank-template from section 1 (preserves label cells in col C, all
    # formatting-irrelevant text, and the row/header structure). Metric data
    # cells D:I + M:R are blanked — fetch loop repopulates.
    import copy
    template = copy.deepcopy(existing[0][2])
    for r in range(METRICS_START_OFFSET, METRICS_END_OFFSET + 1):
        if r >= len(template):
            break
        for c in range(3, 9):    # D-I
            template[r][c] = ""
        for c in range(12, 18):  # M-R
            template[r][c] = ""

    flat: List[List[str]] = []
    for icd in desired:
        block = copy.deepcopy(template)
        block[0][2]  = f"{icd}\nCurrent Week"  # col C row 1 of section
        block[0][11] = f"{icd}\nLast Week"     # col L row 1 of section
        flat.extend(block)

    new_total = len(desired) * SECTION_HEIGHT
    old_total = len(existing) * SECTION_HEIGHT

    # Grow if needed (never shrink — col V's list may extend past sections).
    if ws.row_count < new_total:
        fill._retry(ws.resize, rows=new_total, cols=ws.col_count)

    # Clone section-1 formatting into any newly-needed rows. Sheets API
    # tiles the 24-row source across the destination, so a single call
    # handles however many new section slots we just added.
    if new_total > old_total:
        sheet_id = ws.id
        copy_request = {"requests": [{
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
                    "startRowIndex": old_total,
                    "endRowIndex": new_total,
                    "startColumnIndex": 0,
                    "endColumnIndex": 20,
                },
                "pasteType": "PASTE_FORMAT",
            }
        }]}
        fill._retry(ws.spreadsheet.batch_update, copy_request)

    # Write the full section body in one call.
    fill._retry(ws.update, flat, f"A1:T{new_total}",
                value_input_option="USER_ENTERED")

    # Wipe any trailing rows that USED to hold sections but no longer do.
    # Col V/W are out of range (cols 22/23) so they stay intact.
    if old_total > new_total:
        fill._retry(ws.batch_clear, [f"A{new_total + 1}:T{old_total}"])
        log.info("  removed %d trailing section(s) no longer in col V",
                 (old_total - new_total) // SECTION_HEIGHT)

    log.info("  rebuilt %d section(s) in col V order", len(desired))
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
    """Read user-confirmed ICD→office-id overrides: the COMMITTED base file
    merged with the LOCAL (gitignored) output/ file, local winning. Returns {}
    if neither exists. Keys are lowercased ICD names; values are office-id
    strings (or the SKIP_SENTINEL for non-ICD rows the user dismissed)."""
    merged: dict = {}
    for path in (BASE_OVERRIDES_PATH, OVERRIDES_PATH):  # base first, local last (local wins)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            merged.update({str(k).lower().strip(): str(v) for k, v in data.items()})
        except Exception:
            continue
    return merged


def _save_overrides(overrides: dict) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(
        {k: v for k, v in sorted(overrides.items())}, indent=2,
    ))


ALL_OFFICES_PATH = Path(__file__).resolve().parent / "all-offices.json"
_OFFICE_DIRECTORY_CACHE: Optional[dict] = None


def _load_office_directory() -> dict:
    """Map {owner-name-lower: [office_id, ...]} from all-offices.json — the full
    AppStream office directory the Hub already uses for its 'Map new ICDs'
    suggestions. Built once + cached. Only entries with a real owner + numeric
    office id are included (the file also has raw, owner-less rows)."""
    global _OFFICE_DIRECTORY_CACHE
    if _OFFICE_DIRECTORY_CACHE is None:
        d: dict = {}
        try:
            for o in json.loads(ALL_OFFICES_PATH.read_text()).get("offices", []):
                owner = (o.get("owner") or "").lower().strip()
                oid = str(o.get("office_id") or "").strip()
                if owner and oid.isdigit():
                    d.setdefault(owner, [])
                    if oid not in d[owner]:
                        d[owner].append(oid)
        except Exception:
            pass
        _OFFICE_DIRECTORY_CACHE = d
    return _OFFICE_DIRECTORY_CACHE


def _resolve_office_id(name: str) -> Optional[str]:
    """Return the office id for an ICD name, or None if unmapped/skipped.

    Order: user overrides (incl. SKIP sentinel) → hardcoded ICD_NAME_TO_OFFICE_ID
    → all-offices.json directory (exact, UNAMBIGUOUS owner-name match). The
    directory fallback means an ICD whose sheet name matches its AppStream office
    name exactly is auto-resolved — no manual 'Map new ICDs' step — so only
    genuinely new or ambiguous names fall through to the prompt (Megan 2026-06-27:
    "you should have auto done that on the report run"). SKIP returns None so the
    caller skips the row without logging a 'no mapping' warning."""
    key = name.lower().strip()
    overrides = _load_overrides()
    if key in overrides:
        v = overrides[key]
        return None if v == SKIP_SENTINEL else v
    hard = ICD_NAME_TO_OFFICE_ID.get(key)
    if hard:
        return hard
    # Directory fallback: auto-resolve an exact, unambiguous owner match. If a
    # name maps to >1 office (e.g. a captain with two offices), DON'T guess —
    # leave it for a manual pick so we never write the wrong office's data.
    dir_hits = _load_office_directory().get(key, [])
    _log = logging.getLogger("daily-focus")
    if len(dir_hits) == 1:
        _log.info("[%s] auto-resolved to office %s from all-offices.json",
                  name, dir_hits[0])
        return dir_hits[0]
    if len(dir_hits) > 1:
        _log.warning("[%s] %d offices share this name in all-offices.json (%s) — "
                     "needs a manual pick; skipping for now", name, len(dir_hits), dir_hits)
    return None


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
                    log: logging.Logger,
                    office_cache: Optional[dict] = None) -> Tuple[int, dict]:
    """Fill the Daily Focus report for one captainship. Returns
    (return-code, skipped-ICDs dict) where the dict has keys:
      - "inaccessible": union of all skipped ICDs (legacy)
      - "denied":       ICDs AppStream refused (cur_raw == {})
      - "fetch_errors": ICDs that errored transiently (retry-recoverable)
    The caller merges these across captainships into one shared state file.

    office_cache: run-level {(office_id, week[, "next"]): fetched_data} shared
    across ALL captainships by main(), so an office that appears on more than one
    captainship tab (e.g. Rafael Hidalgo / office 11280 is on 4 tabs) is scraped
    from AppStream ONCE per week and reused everywhere — ~24% of the fetches
    across the 5 tabs are these duplicates. It caches scraped DATA (not the live
    page), so reuse is safe even though each captainship opens its own session.
    Defaults to a private dict for standalone / --only calls."""
    if office_cache is None:
        office_cache = {}
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
    unmapped_this_run: List[str] = []        # no office_id mapping — dropped silently before

    col3 = fill._retry(ws.col_values, 3)

    # Sync the section body to col V every full run: add new ICDs, remove
    # sections whose ICD was deleted from col V, reorder to match col V's
    # order. Metric cells are blanked — the fetch loop below refills them.
    #
    # CRITICAL: skip the rebuild on --only / --retry-inaccessible. Those
    # modes intentionally narrow `icds` to a subset; if we passed that
    # subset to the rebuild, it would treat col V as "wants just these
    # names" and DELETE every other section. (Megan, 2026-05-26 — bug we
    # hit minutes after the first push: single-ICD run nuked the tab.)
    # The rebuild is for whole-list sync only; partial runs leave the
    # tab body alone and just refill metric cells for their targets.
    if not args.only and not args.retry_inaccessible:
        full_icds = _read_icd_list(ws)
        col3 = _rebuild_sections_from_list(ws, full_icds, col3, args.dry_run, log)

    # Unattended AppStream login via patchright (rcaptain) — replaces the old
    # connect_over_cdp(9222) path, which broke on Chrome 148. Mirrors the
    # weekly run.py migration; session is a full AppStream console with the
    # #searchMC office switcher.
    from automations.shared.tableau_patchright import (
        appstream_direct_session, APPSTREAM_PROFILE_DIR,
    )
    session_kwargs = {"verbose": True}
    if args.alt_appstream:
        # Alternate AppStream account for ICDs the primary account can't see.
        # Creds come from env (not creds.py / keychain) so the primary
        # credentials stay the default; profile dir is separate so the
        # alt session's cookies don't overwrite rcaptain's.
        import os
        alt_user = os.environ.get("APPLICANTSTREAM_USERNAME", "").strip()
        alt_pass = os.environ.get("APPLICANTSTREAM_PASSWORD", "").strip()
        if not alt_user or not alt_pass:
            log.error("--alt-appstream needs APPLICANTSTREAM_USERNAME and "
                      "APPLICANTSTREAM_PASSWORD env vars set on the command "
                      "(e.g. APPLICANTSTREAM_USERNAME=... "
                      "APPLICANTSTREAM_PASSWORD=... python -m ...).")
            return 1, {"inaccessible": [], "denied": [], "fetch_errors": []}
        session_kwargs["username"] = alt_user
        session_kwargs["password"] = alt_pass
        session_kwargs["profile_dir"] = (
            APPSTREAM_PROFILE_DIR.parent / ".appstream_profile_alt"
        )
        log.info("logging into AppStream via patchright (ALT account: %s) — "
                 "unattended; using separate profile", alt_user)
    else:
        log.info("logging into AppStream via patchright (rcaptain) — unattended")
    with appstream_direct_session(**session_kwargs) as target_page:

        for icd in icds:
            if _is_skipped(icd):
                # User dismissed this row as 'not an ICD' (e.g. header text).
                # Silent skip — don't log a warning every run.
                continue
            office_id = _resolve_office_id(icd)
            if not office_id:
                log.warning("[%s] no office_id mapping — confirm it from the dashboard's "
                            "'Map new ICDs' prompt and re-run; skip for now", icd)
                unmapped_this_run.append(icd)  # surfaced as a manifest failure, not a silent drop
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

            _ck_cur = (office_id, week_start)
            if _ck_cur in office_cache:
                cur_raw, err = office_cache[_ck_cur]
                log.info("  ✓ %s office %s current-week reused from cache "
                         "(already scraped this run)", icd, office_id)
            else:
                cur_raw, err = _try_current()
                if err in ("exception", "empty"):
                    log.info("  retrying %s once after transient %s …", icd, err)
                    cur_raw, err = _try_current()
                    if err == "ok":
                        log.info("  ✓ %s recovered on retry", icd)
                office_cache[_ck_cur] = (cur_raw, err)

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

            _ck_last = (office_id, last_week_start)
            if _ck_last in office_cache:
                last_raw, last_err = office_cache[_ck_last]
                log.info("  ✓ %s office %s last-week reused from cache", icd, office_id)
            else:
                last_raw, last_err = _try_last()
                if last_err in ("exception", "empty"):
                    log.info("  retrying %s (last week) once after transient %s …", icd, last_err)
                    last_raw, last_err = _try_last()
                    if last_err == "ok":
                        log.info("  ✓ %s (last week) recovered on retry", icd)
                office_cache[_ck_last] = (last_raw, last_err)

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
            _ck_next = (office_id, next_week_start, "next")
            if _ck_next in office_cache:
                next_weekly = office_cache[_ck_next]
                log.info("  ✓ %s office %s next-week reused from cache", icd, office_id)
            else:
                try:
                    next_weekly = fetch_office.fetch_one(target_page, office_id, icd, next_week_start)
                except Exception as e:
                    log.exception("  fetch failed for %s (next week): %s", icd, e)
                    next_weekly = {}
                office_cache[_ck_next] = next_weekly
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
    # (appstream_direct_session closes the browser on exit — no manual teardown)

    if inaccessible_this_run:
        if denied_this_run:
            log.info("%s: %d ICD(s) denied by AppStream account: %s",
                     captainship, len(denied_this_run), ", ".join(denied_this_run))
        if fetch_errors_this_run:
            log.info("%s: %d ICD(s) had transient fetch errors (retry-recoverable): %s",
                     captainship, len(fetch_errors_this_run),
                     ", ".join(fetch_errors_this_run))

    if unmapped_this_run:
        log.info("%s: %d ICD(s) skipped — no office_id mapping: %s",
                 captainship, len(unmapped_this_run), ", ".join(unmapped_this_run))

    log.info("done")
    return 0, {
        "inaccessible": inaccessible_this_run,
        "denied":       denied_this_run,
        "fetch_errors": fetch_errors_this_run,
        "unmapped":     unmapped_this_run,
        "tab":          ws.title,
        "icds":         icds,   # col-V names processed (full list on a non-only run)
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--captainship", choices=CAPTAINSHIPS + ["all"],
                    default="all",
                    help="Which captainship to run, or 'all' (default) — "
                         "every captainship tab in one run.")
    ap.add_argument("--week-start", help="Sunday at start of week to fetch (default: most recent past Sunday).")
    ap.add_argument("--only", help="Only one ICD (short name as in col 22).")
    ap.add_argument("--retry-inaccessible", action="store_true",
                    help="Only re-run the ICDs the last run flagged as not "
                         "pulled (rcaptain had no AppStream access yet). Run "
                         "this once that access has been granted.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-copy", action="store_true",
                    help="Skip the Wednesday copy-current-to-last step.")
    ap.add_argument("--no-slack", action="store_true",
                    help="Skip the Carlos-tab screenshot group DM "
                         "(Carlos + Elena + Valeria + Eve).")
    ap.add_argument("--alt-appstream", action="store_true",
                    help="Log in with the ALTERNATE AppStream account (read "
                         "from env APPLICANTSTREAM_USERNAME / "
                         "APPLICANTSTREAM_PASSWORD) into a separate profile "
                         "dir. Use this for ICDs visible only from a "
                         "different account, e.g. one waiting on rcaptain "
                         "access. Combine with --only \"ICD Name\" to pull "
                         "just that ICD without touching the rest.")
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
    unmapped: List[str] = []
    icds_by_tab: dict = {}   # tab title -> col-V names, for the terminated check
    results_by_cs: dict = {}  # captainship name -> its run result (for screenshot DMs)
    # Shared across all captainships so a duplicated office (an ICD on more than
    # one tab, e.g. Rafael Hidalgo / office 11280 on 4 tabs) is scraped ONCE per
    # week and reused — ~24% of the fetches across the 5 tabs are duplicates.
    office_cache: dict = {}
    for cs in targets:
        cs_rc, cs_result = run_captainship(cs, args, week_start, log,
                                           office_cache=office_cache)
        rc |= cs_rc
        skipped       += cs_result.get("inaccessible", [])
        denied        += cs_result.get("denied", [])
        fetch_errors  += cs_result.get("fetch_errors", [])
        unmapped      += cs_result.get("unmapped", [])
        tab = cs_result.get("tab")
        if tab:
            icds_by_tab.setdefault(tab, []).extend(cs_result.get("icds", []))
        results_by_cs[cs] = cs_result

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
        # Standard failure manifest for the Hub's generic "Retry failed only"
        # action: the failed parts are the inaccessible ICDs, and re-running
        # ONLY those is exactly what --retry-inaccessible does. mark_clean when
        # none failed so the Hub hides the retry button. Best-effort — a
        # manifest hiccup must never fail the run. report_id matches the card
        # id 'daily-focus' in dashboard.py.
        # Cross-reference every filled ICD against the 'Terminated ICDs' tab and
        # ALERT the runner about anyone terminated who's still on a tab so they
        # can remove them. Advisory only — never marks the run failed, never
        # deletes the section. Folded into the manifest note so the mini email
        # surfaces it on unattended runs too.
        term_note = None
        try:
            from automations.shared import terminated_icds as _ti
            all_names = [n for names in icds_by_tab.values() for n in names]
            hits, _flag = _ti.alert_terminated(
                all_names, report_label="the Daily Recruiting Focus tabs")
            if hits:
                term_note = ("terminated ICD(s) still on the report (remove them): "
                             + ", ".join(h["report_name"] for h in hits))
        except Exception as e:  # noqa: BLE001 — advisory must never fail the run
            log.warning("terminated-ICD check skipped: %s", e)

        try:
            from automations.shared import run_manifest as _rm
            # Include UNMAPPED ICDs (no office id) alongside access failures —
            # both mean the report is incomplete. Dropping the unmapped ones
            # silently is exactly what let a 24-ICD-short run report "clean"
            # (Megan 2026-06-25). reconcile reads this manifest, so a non-empty
            # failed list now correctly marks the run INCOMPLETE, not clean.
            # Terminated ICDs are appended to the NOTE only — they're an advisory
            # to act on, not a failed part to retry.
            uniq = sorted(set(skipped) | set(unmapped))
            if uniq:
                bits = []
                if set(skipped):
                    bits.append(f"{len(set(skipped))} not pulled (no AppStream access)")
                if set(unmapped):
                    bits.append(f"{len(set(unmapped))} unmapped "
                                f"(need an office id via 'Map new ICDs')")
                note = "; ".join(bits) + "."
                if term_note:
                    note += " ⚠ " + term_note
                _rm.write_manifest(
                    "daily-focus", failed=uniq,
                    retry_args=["--retry-inaccessible"], kind="ICD", note=note)
            elif term_note:
                # No failures, but terminated ICDs to remove — keep the run clean
                # (ok=true, no failed parts) while carrying the advisory note.
                _rm.write_manifest("daily-focus", failed=[], kind="ICD",
                                   note="⚠ " + term_note)
            else:
                _rm.mark_clean("daily-focus", kind="ICD")
        except Exception as e:  # noqa: BLE001 — manifest is best-effort
            log.warning("run manifest write failed (run still OK): %s", e)

    # Canonical success sentinel the Hub scans for to classify the run
    # (dashboard.py: '=== done ===' in the log => success, BEFORE the
    # full-log traceback scan). Without it, a benign caught-and-logged
    # per-ICD traceback (e.g. a transient next-week fetch error that we
    # recover from) flips the whole run to 'failed' even though it
    # completed and the data is correct (Maud, 2026-06-02). Only emitted
    # on rc == 0 so genuine failures still fall through to the scan.
    # Per-captainship screenshot DMs — after a captainship's tab is filled,
    # render it to PNG(s) and DM it to that captainship's group DM (recipients
    # in focus_slack.FOCUS_DM_RECIPIENTS: Carlos, Colten Wright, Jairo Ruiz).
    # Best-effort per tab: a Slack failure on one tab logs a warning but never
    # fails the run, blocks the success sentinel, or stops the other tabs' DMs
    # (the data fill already succeeded). Skipped on --dry-run / --only (partial
    # views) and with --no-slack.
    if not args.dry_run and not args.only and not args.no_slack:
        from automations.recruiting_report import focus_render, focus_slack
        sh = fill.open_by_key(DAILY_FOCUS_SPREADSHEET_ID)
        for cs, recipients in focus_slack.FOCUS_DM_RECIPIENTS.items():
            if cs not in targets:
                continue
            try:
                ws = find_captainship_worksheet(sh, cs)
                if ws is None:
                    raise RuntimeError(f"{cs} tab not found — skipping Slack DM.")
                # Split into one image per 3 owners so the DM is easy to read.
                slug = cs.lower().replace(" ", "-")
                pngs = focus_render.render_tab_grouped(
                    sh, ws.title, _OUTPUT_DIR,
                    prefix=f"daily-focus-{slug}-{today.isoformat()}", per=3)
                summary = None
                inaccessible = (results_by_cs.get(cs) or {}).get("inaccessible", [])
                if inaccessible:
                    summary = (f"⚠️ {len(inaccessible)} ICD(s) couldn't be pulled: "
                               + ", ".join(inaccessible))
                res = focus_slack.post_focus_screenshots(
                    pngs, recipients, cs, today, summary=summary)
                log.info("Slack DM sent — %d %s screenshot(s) → %s",
                         len(pngs), cs, ", ".join(res["recipients"]))
            except Exception as e:  # noqa: BLE001 — post is best-effort
                log.warning("%s screenshot DM failed (run still OK): %s", cs, e)

    if rc == 0:
        log.info("=== done ===")
    return rc


if __name__ == "__main__":
    sys.exit(main())

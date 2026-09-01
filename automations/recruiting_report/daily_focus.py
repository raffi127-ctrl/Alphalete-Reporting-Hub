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
# Map a name to this instead of an office id to take it OFF the report for good:
# the row is passed over silently — no fetch, no "not pulled" warning, no manifest
# failure, no 🚨 dropped-section alert. Two reasons to use it:
#   - the row isn't a person at all (a header / title row), or
#   - the person is on the tab but doesn't recruit, so AppStream has nothing to
#     give and every run flagged them as "no AppStream access" (Javeon Lara and
#     Melik El Jaiez, Eve 2026-08-12 — the alert was crying wolf daily).
# Their sections on the Sheet are LEFT ALONE, never cleared. Don't "fix" a
# __SKIP__ back to an office id without checking that the person recruits now.
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


def _load_base_overrides() -> dict:
    """Just the COMMITTED base map (no local layer)."""
    try:
        return {str(k).lower().strip(): str(v)
                for k, v in json.loads(BASE_OVERRIDES_PATH.read_text()).items()}
    except Exception:
        return {}


def _save_overrides(overrides: dict) -> None:
    """Write the LOCAL (gitignored) override file, keeping only entries that
    actually differ from the committed base map.

    Callers hand us a MERGED dict (the Hub's 'Map new ICDs' picker does
    _load_overrides() → edit → _save_overrides()). Writing that merge verbatim
    copied the whole base map into the local file, and since local wins, the
    copy then shadowed the base forever — a later correction committed to the
    base would never take effect on that machine. Pruning the identical entries
    keeps the local file to genuine per-machine additions only."""
    base = _load_base_overrides()
    local_only = {k: v for k, v in overrides.items()
                  if base.get(str(k).lower().strip()) != str(v)}
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(
        {k: v for k, v in sorted(local_only.items())}, indent=2,
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


_ALIAS_TABLE_CACHE: Optional[dict] = None


def _alias_table() -> dict:
    """The shared 'ICD Aliases' table, loaded once per process.

    Canonical source is the Sheet (see focus_office_att.aliases) — that's the
    house rule: a name-spelling mismatch is fixed THERE, not with a per-report
    mapping entry. Sheet-outage resilience (fall back to the local mirror of
    the last good read) lives inside aliases.load_aliases() itself, so the
    weekly report and the Hub get it too; this wrapper only memoizes the one
    read per run."""
    global _ALIAS_TABLE_CACHE
    if _ALIAS_TABLE_CACHE is None:
        try:
            from automations.focus_office_att import aliases as _al
            _ALIAS_TABLE_CACHE = _al.load_aliases()
        except Exception as e:  # noqa: BLE001 — never let aliases break a run
            logging.getLogger("daily-focus").warning(
                "ICD Aliases unavailable (%s) — alias spellings won't resolve "
                "this run", e)
            _ALIAS_TABLE_CACHE = {}
    return _ALIAS_TABLE_CACHE


def _alias_spellings(name: str) -> List[str]:
    """Other spellings of this person from the ICD Aliases sheet, in both
    directions (sheet spelling → canonical, and canonical → its aliases).
    Excludes the input itself. Empty list when the name isn't in the table."""
    table = _alias_table()
    if not table:
        return []
    try:
        from automations.focus_office_att import aliases as _al
        canonical = _al.alias_to_canonical(name, table)
        out = [c for c in _al.get_search_candidates(canonical, table)
               if _al._norm_name(c) != _al._norm_name(name)]
        if _al._norm_name(canonical) != _al._norm_name(name) and canonical not in out:
            out.insert(0, canonical)
        return out
    except Exception:  # noqa: BLE001
        return []


def _resolve_office_id_with_source(name: str,
                                   _via_alias: bool = False) -> Tuple[Optional[str], str]:
    """Like _resolve_office_id, but also says WHERE the id came from.

    Source is one of "overrides" (base or local mapping file), "hardcoded"
    (ICD_NAME_TO_OFFICE_ID), "directory" (all-offices.json owner match),
    "alias" (matched under another spelling from the ICD Aliases sheet), or
    "none". The caller uses it to auto-pin a directory-only resolution — see
    _pin_office_id — because the directory is machine-local and gitignored, so
    an ICD that resolves ONLY there silently vanishes on any box whose scrape
    hasn't caught up (Fernando Munoz / office 22604, 2026-08-18)."""
    key = name.lower().strip()
    overrides = _load_overrides()
    if key in overrides:
        v = overrides[key]
        return (None if v == SKIP_SENTINEL else v), "overrides"
    hard = ICD_NAME_TO_OFFICE_ID.get(key)
    if hard:
        return hard, "hardcoded"
    # Directory fallback: auto-resolve an exact, unambiguous owner match. If a
    # name maps to >1 office (e.g. a captain with two offices), DON'T guess —
    # leave it for a manual pick so we never write the wrong office's data.
    dir_hits = _load_office_directory().get(key, [])
    _log = logging.getLogger("daily-focus")
    if len(dir_hits) == 1:
        _log.info("[%s] auto-resolved to office %s from all-offices.json",
                  name, dir_hits[0])
        return dir_hits[0], "directory"
    if len(dir_hits) > 1:
        _log.warning("[%s] %d offices share this name in all-offices.json (%s) — "
                     "needs a manual pick; skipping for now", name, len(dir_hits), dir_hits)
    # Last resort: the ICD Aliases sheet. A tab may spell someone differently
    # from AppStream ("Kim Rodriguez" on Raf's tab vs owner "Kimberly
    # Rodriguez"), and per the house rule that mismatch belongs in the shared
    # alias sheet, NOT in this file. Retry the other spellings through the same
    # three layers. _via_alias stops a chain of aliases from recursing.
    if not _via_alias:
        for alt in _alias_spellings(name):
            alt_id, _ = _resolve_office_id_with_source(alt, _via_alias=True)
            if alt_id:
                _log.info("[%s] resolved to office %s via the ICD Aliases sheet "
                          "(as %r)", name, alt_id, alt)
                return alt_id, "alias"
    return None, "none"


def _resolve_office_id(name: str) -> Optional[str]:
    """Return the office id for an ICD name, or None if unmapped/skipped.

    Order: user overrides (incl. SKIP sentinel) → hardcoded ICD_NAME_TO_OFFICE_ID
    → all-offices.json directory (exact, UNAMBIGUOUS owner-name match). The
    directory fallback means an ICD whose sheet name matches its AppStream office
    name exactly is auto-resolved — no manual 'Map new ICDs' step — so only
    genuinely new or ambiguous names fall through to the prompt (Megan 2026-06-27:
    "you should have auto done that on the report run"). SKIP returns None so the
    caller skips the row without logging a 'no mapping' warning."""
    return _resolve_office_id_with_source(name)[0]


def _pin_office_id(name: str, office_id: str) -> bool:
    """Persist a directory-resolved ICD→office id into the LOCAL mapping file.

    Called only after the office actually pulled clean, so we never pin a guess.
    Writes to OVERRIDES_PATH (output/, gitignored) — NOT the committed base
    file: a run that dirtied a tracked file would block the mini's
    `git pull --ff-only` and silently strand every later deploy. The base file
    stays a deliberate, committed decision; main() prints the exact line to add
    so promoting it is a copy-paste.

    Returns True if this call added the pin (False if it was already there)."""
    key = name.lower().strip()
    overrides = _load_overrides()
    if overrides.get(key) == str(office_id):
        return False
    try:
        local = {}
        if OVERRIDES_PATH.exists():
            local = {str(k).lower().strip(): str(v)
                     for k, v in json.loads(OVERRIDES_PATH.read_text()).items()}
        if local.get(key) == str(office_id):
            return False
        local[key] = str(office_id)
        _save_overrides(local)
        return True
    except Exception as e:  # noqa: BLE001 — pinning is a nicety, never fail a run
        logging.getLogger("daily-focus").warning(
            "couldn't pin %s -> %s locally: %s", name, office_id, e)
        return False


def _is_skipped(name: str) -> bool:
    """True if the user took this name off the report in overrides — a non-ICD
    row, or a real person who doesn't recruit. See SKIP_SENTINEL. Keys are
    lowercased, so one entry covers every capitalization on the tabs (the tabs
    carry both 'Melik El Jaiez' and 'MELIK EL JAIEZ')."""
    return _load_overrides().get(name.lower().strip()) == SKIP_SENTINEL


def _promote_pins(log: logging.Logger) -> int:
    """Merge every local-only ICD→office mapping into the COMMITTED base map.

    Closes the loop that let Fernando Munoz get flagged (2026-08-18): mappings
    made on one machine — by the Hub's 'Map new ICDs' picker, or auto-pinned by
    a run — lived only in the gitignored output/ file, so no other box ever saw
    them. This promotes them in one command; commit the base file afterwards and
    every machine has them. The local file is left holding only what is still
    genuinely local (nothing, after a full promote)."""
    base = _load_base_overrides()
    try:
        local = {str(k).lower().strip(): str(v)
                 for k, v in json.loads(OVERRIDES_PATH.read_text()).items()}
    except Exception:
        local = {}

    new = {k: v for k, v in local.items() if k not in base}
    changed = {k: v for k, v in local.items() if k in base and base[k] != v}

    if not new and not changed:
        log.info("nothing to promote — the local mapping file adds nothing the "
                 "committed base map doesn't already have.")
        return 0

    for k, v in new.items():
        log.info("  + %-28s %s   (new)", k, v)
    for k, v in changed.items():
        log.info("  ~ %-28s %s   (was %s)", k, v, base[k])

    base.update(local)
    BASE_OVERRIDES_PATH.write_text(
        json.dumps({k: base[k] for k in sorted(base)}, indent=2) + "\n")
    # Re-save the local file — _save_overrides prunes anything now identical to
    # the base, so the promoted entries drop out and local stays honest.
    _save_overrides(local)

    log.info("promoted %d new + %d changed mapping(s) into %s — commit it so "
             "the mini and every other machine pick them up.",
             len(new), len(changed), BASE_OVERRIDES_PATH.name)
    return 0


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
    # (name, office_id) pairs pinned to the local mapping file this run because
    # they had been resolving only through the machine-local all-offices.json.
    auto_pinned_this_run: List[Tuple[str, str]] = []

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
                # Taken off the report on purpose (header text, or someone who
                # doesn't recruit). Silent skip — no warning, and crucially it
                # never reaches inaccessible/unmapped, so it can't raise a
                # dropped-section alarm every morning. Log at debug so a
                # "where did this person go?" question still has an answer.
                log.debug("[%s] marked __SKIP__ in the ICD mappings — "
                          "off the report on purpose", icd)
                continue
            office_id, office_src = _resolve_office_id_with_source(icd)
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

            # The office pulled clean, so this name→office id is now PROVEN.
            # If it only resolved through all-offices.json (machine-local and
            # gitignored), pin it to the local mapping file right now so the ICD
            # can never silently vanish when that scrape is regenerated or when
            # the report moves to another box. Reported at the end of the run so
            # the pin gets promoted into the committed base file.
            if office_src == "directory" and not args.dry_run:
                if _pin_office_id(icd, office_id):
                    log.info("  pinned %s -> office %s locally (was resolving "
                             "only via all-offices.json)", icd, office_id)
                    auto_pinned_this_run.append((icd, office_id))

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

    if auto_pinned_this_run:
        log.info("%s: %d ICD(s) auto-pinned to the local mapping file after a "
                 "clean pull: %s", captainship, len(auto_pinned_this_run),
                 ", ".join(f"{n} -> {o}" for n, o in auto_pinned_this_run))

    log.info("done")
    return 0, {
        "inaccessible": inaccessible_this_run,
        "denied":       denied_this_run,
        "fetch_errors": fetch_errors_this_run,
        "unmapped":     unmapped_this_run,
        "auto_pinned":  auto_pinned_this_run,
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
    ap.add_argument("--promote-pins", action="store_true",
                    help="Move every local-only ICD→office mapping into the "
                         "COMMITTED base map, then exit. Run this on the "
                         "laptop and commit — it's how a mapping made on one "
                         "machine (the Hub's 'Map new ICDs' picker, or a run's "
                         "auto-pin) reaches the mini and everyone else.")
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

    if args.promote_pins:
        return _promote_pins(log)

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
    auto_pinned: List[Tuple[str, str]] = []
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
        auto_pinned   += cs_result.get("auto_pinned", [])
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
                # Split the two causes: AppStream genuinely refusing the office
                # needs an access request, a transient pull error just needs a
                # retry. Lumping both under "no AppStream access" sent people
                # chasing access grants for what was a timeout (Megan 2026-08-18).
                _den = set(denied)
                _tra = set(fetch_errors) - _den
                if _den:
                    bits.append(f"{len(_den)} refused by AppStream (needs access)")
                if _tra:
                    bits.append(f"{len(_tra)} transient pull error (retry)")
                _other = set(skipped) - _den - _tra
                if _other:
                    bits.append(f"{len(_other)} not pulled")
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

        # Slack any skipped / unmapped ICD to #claudecorrections-and-requests so
        # the gap is SEEN even though the pill goes green (Megan 2026-07-28 —
        # replaces the on-card "IF AN ICD IS SKIPPED" prompt). Best-effort: a
        # Slack hiccup never fails the run.
        _gap = sorted(set(skipped) | set(unmapped))
        if _gap:
            try:
                from automations.day_orchestrator import notify
                from automations.day_orchestrator.registry import load_config
                _lines = ["☀️ *Daily Recruiting Focus — {} ICD(s) not pulled "
                          "today*".format(len(_gap))]
                # Same split as the manifest note: only a real AppStream refusal
                # gets the "no access" wording, so nobody goes off requesting
                # access for what a retry fixes.
                _den = set(denied)
                _tra = set(fetch_errors) - _den
                _other = set(skipped) - _den - _tra
                if _den:
                    _lines.append("• AppStream refused these — needs access ({}): {}".format(
                        len(_den), ", ".join(sorted(_den))))
                if _tra:
                    _lines.append("• Transient pull error — a retry usually fixes it ({}): {}".format(
                        len(_tra), ", ".join(sorted(_tra))))
                if _other:
                    _lines.append("• Not pulled ({}): {}".format(
                        len(_other), ", ".join(sorted(_other))))
                if set(unmapped):
                    _lines.append("• Unmapped — needs an office id ({}): {}".format(
                        len(set(unmapped)), ", ".join(sorted(set(unmapped)))))
                # ONE THREAD PER PROBLEM, not one post per run (Eve
                # 2026-09-01: "sigue generando mensajes nuevos sobre esta falla
                # en el canal, marea y es redundante"). This producer went
                # straight to _post_corrections, which has no dedupe at all, so
                # every pass that ended with a gap opened ANOTHER top-level
                # "N ICD(s) not pulled today" — the 4am run, the orchestrator's
                # retry and each manual re-run, four near-identical posts about
                # the same three ICDs that day. Same key + same day now updates
                # one status line inside the open thread instead of bumping the
                # channel again, and a clean run closes it through
                # run_manifest -> incident_thread.resolve_report("daily-focus").
                # `drop-` is the right family: the report RAN, part of it just
                # didn't fill — so it shares a thread with the manifest's own
                # failure alert rather than competing with it.
                _posted = None
                try:
                    from automations.shared import incident_thread as _inc
                    _posted = _inc.open_or_followup(
                        key="drop-daily-focus",
                        title=_lines[0], body=_lines[1:],
                        label="*Daily Recruiting Focus*")
                except Exception as e:  # noqa: BLE001 — never fail the run
                    log.warning("incident thread unavailable (%s) — posting "
                                "standalone", e)
                if not _posted:
                    notify._post_corrections(load_config(), None, _lines,
                                             dry_run=False, tag="daily-focus-skips")
            except Exception as e:  # noqa: BLE001 — Slack must not fail the run
                log.warning("corrections post (skips) failed: %s", e)

    # Any ICD pinned this run was resolving only through the machine-local
    # all-offices.json — it is now safe on THIS box, but every other machine
    # still depends on its own scrape. Print the exact JSON lines so promoting
    # them into the committed base map is a copy-paste. Deliberately not written
    # to the base file by the run itself: dirtying a tracked file would block the
    # mini's `git pull --ff-only` and strand every later deploy.
    if auto_pinned:
        uniq_pins = sorted({(n.lower().strip(), o) for n, o in auto_pinned})
        log.info("")
        log.info("=== %d ICD(s) auto-pinned locally — promote these into %s ===",
                 len(uniq_pins), BASE_OVERRIDES_PATH.name)
        for n, o in uniq_pins:
            log.info('  "%s": "%s",', n, o)

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
    # (the data fill already succeeded). Skipped on --dry-run / --only /
    # --retry-inaccessible (partial views) and with --no-slack.
    #
    # --retry-inaccessible BELONGS in that list and was missing (Eve 2026-09-01:
    # "hoy se enviaron varios DMs de este reporte y parecen repetidos"). A retry
    # re-pulls ONLY the ICDs that were skipped, but the loop below walks every
    # captainship tab and sends regardless of whether anything changed — so each
    # retry re-sent the whole report to Carlos', Colten's and Jairo's group DMs.
    # Four retries that morning put four identical posts in each one. The Hub's
    # "Retry the skipped ICDs" button runs this same flag, so it was never
    # specific to a re-run queued by hand. The full run that preceded the retry
    # already sent the screenshots; the retry's job is to fill the cells.
    if (not args.dry_run and not args.only and not args.retry_inaccessible
            and not args.no_slack):
        from automations.recruiting_report import focus_shot, focus_slack
        sh = fill.open_by_key(DAILY_FOCUS_SPREADSHEET_ID)
        _dm_failures: List[str] = []
        for cs, recipients in focus_slack.FOCUS_DM_RECIPIENTS.items():
            if cs not in targets:
                continue
            try:
                ws = find_captainship_worksheet(sh, cs)
                if ws is None:
                    raise RuntimeError(f"{cs} tab not found — skipping Slack DM.")
                # Split into one image per 3 owners so the DM is easy to read.
                # focus_SHOT, not focus_render: the shots are exported by Google
                # (exact borders / wrapped headers / the black "Office Focus
                # Report" band) instead of redrawn cell-by-cell with PIL. The
                # redraw silently dropped all three — most visibly it painted the
                # black header white, so its white text vanished — and these DMs
                # had carried that the whole time (Megan 2026-08-30: "they've been
                # missed/messed up the whole time").
                slug = cs.lower().replace(" ", "-")
                pngs = focus_shot.render_tab_grouped(
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
                _dm_failures.append("{} ({})".format(cs, e))

        # A group-DM that didn't send is a real miss even though the fill
        # succeeded — Slack it to #claudecorrections-and-requests (Megan
        # 2026-07-28). Best-effort; never fails the run.
        if _dm_failures:
            try:
                from automations.day_orchestrator import notify
                from automations.day_orchestrator.registry import load_config
                _lines = ["☀️ *Daily Recruiting Focus — {} Slack DM(s) didn't "
                          "send*".format(len(_dm_failures))]
                _lines += ["• " + f for f in _dm_failures]
                notify._post_corrections(load_config(), None, _lines,
                                         dry_run=False, tag="daily-focus-dm-fail")
            except Exception as e:  # noqa: BLE001 — Slack must not fail the run
                log.warning("corrections post (DM fail) failed: %s", e)

    if rc == 0:
        log.info("=== done ===")
    return rc


if __name__ == "__main__":
    sys.exit(main())

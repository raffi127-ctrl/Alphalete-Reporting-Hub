"""Write today's New Internet ABP data to the AT&T Fiber Metrics Report
sheet's 'Local Office - New Internet ABP%' tab.

The tab is a SINGLE section (ABP has no period buckets), so this is a
lean cousin of new_internet_churn.fill — same visual grammar (date-pair
columns, Office Avg row, Rep rows sorted by today's % desc, blanks
hidden) but one section instead of four.

DESTINATION LAYOUT:
    Row 1: NEW INTERNET ABP %   | <date> (merged B:C) | <prev date> | ...
    Row 2: Office Avg           | pct   | units        | ...
    Row 3: Rep                  | %     | units        | ...
    Row 4+: <rep>               | pct   | units        | ...

The tab is created EMPTY (Megan, 2026-07-10), so run 1 bootstraps the
header block + seeds the roster; every later run inserts 2 fresh B:C
columns and fills today.

pct is written USER_ENTERED as a fraction (0.667) so the server-side
sortRange orders reps numerically and the col-B number format renders
it as '66.7%'. units ('108/124') is RAW so Sheets doesn't read it as a
date. Blank slots leave both cells empty = 'no data'.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time
from typing import Optional

from automations.new_internet_abp import pull
from automations.recruiting_report.fill import open_by_key, _retry
from automations.new_internet_churn.fill import _date_label, _col_index_to_letter

SHEET_ID = os.environ.get("ABP_SHEET_ID", "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8")
TAB = "Local Office - New Internet ABP%"

SECTION_LABEL = "NEW INTERNET ABP %"
HEADER_ROW = 1        # section label + date-pair headers
OFFICE_ROW = 2        # Office Avg
REP_HEADER_ROW = 3    # 'Rep | % | units'
FIRST_REP_ROW = 4     # roster starts here

PCT_FMT = {"type": "PERCENT", "pattern": "0.0%"}


def open_ws(sheet_id: Optional[str] = None):
    """Open the ABP tab. `sheet_id` overrides the office's sheet (the
    combined runner passes Raf's vs Rashad's sheet explicitly). The TAB
    title is identical across offices, so only the sheet id differs."""
    return open_by_key(sheet_id or SHEET_ID).worksheet(TAB)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def _pct_fraction(pct_str: str) -> Optional[float]:
    """'66.7%' -> 0.667 for USER_ENTERED numeric write. None if unparseable."""
    try:
        return round(float((pct_str or "").replace("%", "").strip()) / 100.0, 6)
    except ValueError:
        return None


def is_bootstrapped(ws) -> bool:
    a1 = _retry(ws.acell, "A1").value or ""
    return _norm(a1) == _norm(SECTION_LABEL)


def find_rep_rows(ws) -> dict:
    """Map rep-name(lower) -> 1-indexed sheet row for the roster block.
    Roster runs from FIRST_REP_ROW down to the last non-blank col-A row."""
    col_a = _retry(ws.col_values, 1)
    out: dict[str, int] = {}
    for i in range(FIRST_REP_ROW - 1, len(col_a)):
        name = (col_a[i] or "").strip()
        if not name:
            continue
        out[name.lower()] = i + 1
    return out


def last_rep_row(rep_rows: dict) -> int:
    return max(rep_rows.values()) if rep_rows else REP_HEADER_ROW


def today_already_filled(ws, today: dt.date) -> bool:
    b1 = _retry(ws.acell, f"{_col_index_to_letter(1)}{HEADER_ROW}").value or ""
    return b1.strip() == _date_label(today)


# ---------------------------------------------------------------- bootstrap

def _sorted_reps(parsed: dict) -> list[str]:
    """Reps with data first (desc by ABP %), then blank-data reps (kept in
    the roster but hidden). Ties broken by name for stability."""
    reps = parsed.get("reps", {})
    def key(item):
        name, slot = item
        pv = _pct_fraction(slot.get("pct", "")) if pull.has_pct(slot) else None
        # data reps sort ahead of blanks; within data, higher % first
        return (0 if pv is None else 1, pv or 0.0, name.lower())
    ordered = sorted(reps.items(), key=key, reverse=True)
    return [n for n, _ in ordered]


def bootstrap(ws, today: dt.date, parsed: dict, *, dry_run=False, logfn=print) -> None:
    """First-run: lay down the header block + seed the roster with today's
    data already in B/C."""
    office = parsed.get("office_total", {})
    reps = parsed.get("reps", {})
    order = _sorted_reps(parsed)
    date_label = _date_label(today)

    # Column A labels + the header/office rows.
    grid: list[list] = [
        [SECTION_LABEL, date_label, ""],   # row 1
        ["Office Avg", None, pull.fmt_units(office)],  # row 2 (pct filled below)
        ["Rep", "%", "units"],             # row 3
    ]
    # Rep rows
    for name in order:
        grid.append([name, None, pull.fmt_units(reps.get(name, {}))])

    if dry_run:
        logfn(f"  (dry-run) would BOOTSTRAP {TAB!r}: header + {len(order)} reps; "
              f"office {office.get('pct','-')} {pull.fmt_units(office)}")
        return

    # 1. Write the text grid (col A labels + units) RAW so '108/124' stays text.
    end_row = len(grid)
    ws.spreadsheet.values_batch_update({
        "valueInputOption": "RAW",
        "data": [{
            "range": f"'{TAB}'!A1:C{end_row}",
            "values": grid,
        }],
    })
    # 2. Write pct cells (col B) USER_ENTERED as fractions so they're numeric.
    #    Office at B2 and reps at B{FIRST_REP_ROW}+ are written as SEPARATE
    #    ranges so the 'Rep'/'%' header row (B3) is left untouched.
    office_pct = _pct_fraction(office.get("pct", "")) if pull.has_pct(office) else ""
    rep_pcts = [[_pct_fraction(reps.get(n, {}).get("pct", ""))
                 if pull.has_pct(reps.get(n, {})) else ""] for n in order]
    ws.spreadsheet.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": [
            {"range": f"'{TAB}'!B{OFFICE_ROW}", "values": [[office_pct]]},
            {"range": f"'{TAB}'!B{FIRST_REP_ROW}:B{end_row}", "values": rep_pcts},
        ],
    })
    # 3. Merge B1:C1 (date spans the pair) + set percent format on col B +
    #    hide blank-data rep rows.
    _post_write_structure(ws, today, parsed, find_rep_rows(ws),
                          dry_run=False, logfn=logfn, bootstrapped=True)
    logfn(f"  bootstrapped {TAB!r} with {len(order)} reps")


# ------------------------------------------------------------- daily insert

def insert_two_cols_at_b(ws) -> None:
    """Insert 2 fresh columns at B (0-idx 1) across the whole tab, then copy
    the PRIOR day's formatting (now shifted to D:E) onto the new B:C so
    Megan's manual look (colors, borders, number format, conditional
    rules) carries forward every day. Values are NOT copied (PASTE_FORMAT
    only) — write_today fills today's numbers into the clean B:C. Row-1
    col A (section label) is untouched; single section → no preserve block
    needed (unlike churn)."""
    last_row = ws.row_count
    ws.spreadsheet.batch_update({"requests": [{
        "insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": 3},
            "inheritFromBefore": False,
        }
    }]})
    time.sleep(1)
    # Carry yesterday's per-column formatting (D:E, post-shift) onto B:C.
    ws.spreadsheet.batch_update({"requests": [{
        "copyPaste": {
            "source": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": last_row,
                       "startColumnIndex": 3, "endColumnIndex": 5},   # D:E
            "destination": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": last_row,
                            "startColumnIndex": 1, "endColumnIndex": 3},  # B:C
            "pasteType": "PASTE_FORMAT",
        }
    }]})
    time.sleep(2)


def append_missing_reps(ws, parsed: dict, rep_rows: dict, *,
                        dry_run=False, logfn=print) -> list:
    """Append any data rep not already in the roster to the bottom."""
    have = set(rep_rows.keys())
    missing = [n for n in _sorted_reps(parsed)
               if pull.has_pct(parsed["reps"].get(n, {})) and n.lower() not in have]
    if not missing:
        return []
    if dry_run:
        logfn(f"  (dry-run) would append {len(missing)} new rep(s): {missing[:5]}")
        return missing
    start = last_rep_row(rep_rows) + 1
    ws.spreadsheet.values_batch_update({
        "valueInputOption": "RAW",
        "data": [{
            "range": f"'{TAB}'!A{start}:A{start + len(missing) - 1}",
            "values": [[n] for n in missing],
        }],
    })
    logfn(f"  appended {len(missing)} new rep(s): {missing[:5]}"
          + (" …" if len(missing) > 5 else ""))
    return missing


def write_today(ws, today: dt.date, parsed: dict, rep_rows: dict, *,
                dry_run=False, logfn=print) -> dict:
    """Fill the newly-inserted B:C with today's office + per-rep data."""
    office = parsed.get("office_total", {})
    reps = parsed.get("reps", {})
    date_label = _date_label(today)

    raw_data = [{"range": f"'{TAB}'!B{HEADER_ROW}", "values": [[date_label]]},
                {"range": f"'{TAB}'!C{OFFICE_ROW}", "values": [[pull.fmt_units(office)]]}]
    pct_data = [{"range": f"'{TAB}'!B{OFFICE_ROW}",
                 "values": [[_pct_fraction(office.get("pct", "")) if pull.has_pct(office) else ""]]}]

    filled = 0
    unmatched = []
    for name, slot in reps.items():
        if not pull.has_pct(slot):
            continue
        row = rep_rows.get(name.lower())
        if not row:
            unmatched.append(name)
            continue
        raw_data.append({"range": f"'{TAB}'!C{row}", "values": [[pull.fmt_units(slot)]]})
        pct_data.append({"range": f"'{TAB}'!B{row}",
                         "values": [[_pct_fraction(slot.get("pct", ""))]]})
        filled += 1

    if dry_run:
        logfn(f"  (dry-run) would write office {office.get('pct','-')} "
              f"{pull.fmt_units(office)} + {filled} reps"
              + (f"; {len(unmatched)} unmatched: {unmatched[:5]}" if unmatched else ""))
        return {"filled": filled, "unmatched": unmatched}

    ws.spreadsheet.values_batch_update({"valueInputOption": "RAW", "data": raw_data})
    ws.spreadsheet.values_batch_update({"valueInputOption": "USER_ENTERED", "data": pct_data})
    logfn(f"  wrote office + {filled} reps"
          + (f"; {len(unmatched)} unmatched: {unmatched[:5]}" if unmatched else ""))
    return {"filled": filled, "unmatched": unmatched}


# --------------------------------------------------------- structure / sort

def _post_write_structure(ws, today, parsed, rep_rows, *, dry_run=False,
                          logfn=print, bootstrapped=False) -> None:
    """Merge B1:C1, set col-B percent format, sort reps by today's % desc,
    hide blank-data rep rows. Idempotent — safe to run every fill."""
    if dry_run:
        logfn("  (dry-run) skipping merge/format/sort/hide")
        return
    last = last_rep_row(rep_rows)
    requests = [
        # Merge the date across the B:C pair on the header row.
        {"mergeCells": {"range": {"sheetId": ws.id,
                                  "startRowIndex": HEADER_ROW - 1, "endRowIndex": HEADER_ROW,
                                  "startColumnIndex": 1, "endColumnIndex": 3},
                        "mergeType": "MERGE_ALL"}},
        # Percent format on col B, office + rep rows.
        {"repeatCell": {"range": {"sheetId": ws.id,
                                  "startRowIndex": OFFICE_ROW - 1, "endRowIndex": last,
                                  "startColumnIndex": 1, "endColumnIndex": 2},
                        "cell": {"userEnteredFormat": {"numberFormat": PCT_FMT}},
                        "fields": "userEnteredFormat.numberFormat"}},
    ]
    ws.spreadsheet.batch_update({"requests": requests})

    # At bootstrap: install the house style (matches Raf) + the insert-proof
    # color rules, so every new office's tab looks the same automatically.
    if bootstrapped:
        apply_house_style(ws, last_row=last, logfn=logfn)
        apply_color_rules(ws, logfn=logfn)

    # Sort the rep block by today's % (col B) descending — server-side,
    # atomic, moves whole rows (history stays aligned). Unhide first so
    # sortRange can move rows hidden on a prior run.
    _unhide_reps(ws, rep_rows)
    if last >= FIRST_REP_ROW:
        ws.spreadsheet.batch_update({"requests": [{
            "sortRange": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": FIRST_REP_ROW - 1, "endRowIndex": last,
                          "startColumnIndex": 0, "endColumnIndex": ws.col_count},
                "sortSpecs": [{"dimensionIndex": 1, "sortOrder": "DESCENDING"}],
            }
        }]})
        time.sleep(1)
    _hide_blank_reps(ws)


def _unhide_reps(ws, rep_rows) -> None:
    last = last_rep_row(rep_rows)
    if last < FIRST_REP_ROW:
        return
    ws.spreadsheet.batch_update({"requests": [{
        "updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": FIRST_REP_ROW - 1, "endIndex": last},
            "properties": {"hiddenByUser": False}, "fields": "hiddenByUser",
        }
    }]})


def _hide_blank_reps(ws) -> dict:
    """Hide rep rows whose today (col B) is blank; unhide those with data.
    Reads current grid (post-sort) so it acts on final row positions."""
    grid = _retry(ws.get_all_values)
    requests = []
    hidden, unhidden = [], []
    for i in range(FIRST_REP_ROW - 1, len(grid)):
        row = grid[i]
        name = (row[0] if row else "").strip()
        if not name:
            continue
        b = (row[1] if len(row) > 1 else "").strip()
        hide = b == ""
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": i, "endIndex": i + 1},
            "properties": {"hiddenByUser": hide}, "fields": "hiddenByUser"}})
        (hidden if hide else unhidden).append(name)
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})
    return {"hidden": hidden, "unhidden": unhidden}


# House style read off Raf's tab (Megan's formatting, 2026-07-10): every
# cell centered, size-12, full grid borders, no bold; col widths A/B/C =
# 185/90/67. Encoded here so every office's tab matches Raf and new
# offices inherit it at onboarding. (No yellow header on Raf currently.)
HOUSE_COL_WIDTHS = {0: 185, 1: 90, 2: 67}


def apply_house_style(ws, *, last_row: Optional[int] = None, logfn=print) -> None:
    """Match Megan's Raf formatting on this tab: center + size-12 + grid
    borders across the data block, and the A/B/C column widths. Static only
    — colors are handled by apply_color_rules. Idempotent."""
    last_row = last_row or last_rep_row(find_rep_rows(ws))
    solid = {"style": "SOLID"}
    requests = [
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": last_row,
                      "startColumnIndex": 0, "endColumnIndex": ws.col_count},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"fontSize": 12},
                "borders": {"top": solid, "bottom": solid, "left": solid, "right": solid},
            }},
            "fields": ("userEnteredFormat.horizontalAlignment,"
                       "userEnteredFormat.verticalAlignment,"
                       "userEnteredFormat.textFormat.fontSize,"
                       "userEnteredFormat.borders"),
        }},
    ]
    for col_0, px in HOUSE_COL_WIDTHS.items():
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": col_0, "endIndex": col_0 + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    ws.spreadsheet.batch_update({"requests": requests})
    logfn("  applied house style (center/size-12/borders + A/B/C widths)")


def apply_color_rules(ws, *, clear_first: bool = True, logfn=print) -> None:
    """Install the value-based red/yellow/green conditional-format rules on
    the %-columns (insert-proof wide range). Claude owns these — Megan owns
    the static look (borders/header/font/centering). Idempotent: clears any
    existing conditional rules on the tab first so re-runs don't stack
    duplicates. Reusable across offices at onboarding."""
    from automations.new_internet_abp import bands
    if clear_first:
        meta = ws.spreadsheet.fetch_sheet_metadata(
            {"fields": "sheets(properties(sheetId),conditionalFormats)"})
        n = 0
        for s in meta["sheets"]:
            if s["properties"]["sheetId"] == ws.id:
                n = len(s.get("conditionalFormats", []))
        if n:
            # Delete from the highest index down so earlier indices stay valid.
            ws.spreadsheet.batch_update({"requests": [
                {"deleteConditionalFormatRule": {"sheetId": ws.id, "index": i}}
                for i in range(n - 1, -1, -1)]})
            logfn(f"  cleared {n} existing conditional rule(s)")
    ws.spreadsheet.batch_update({"requests": bands.conditional_format_requests(
        ws.id, OFFICE_ROW - 1, ws.row_count, end_col_0=min(ws.col_count, 400))})
    logfn("  applied red/yellow/green rules (insert-proof, %-columns)")


def fill_office(ws, today, parsed, *, force_insert=False, dry_run=False,
                logfn=print) -> None:
    """One office's full fill: bootstrap an empty tab, else insert today's
    date columns, write, sort, hide. Shared by run.py (single office) and
    run_all.py (combined Raf+Rashad session) so the two can't drift."""
    if not is_bootstrapped(ws):
        logfn("  Tab is empty → bootstrapping header + roster.")
        bootstrap(ws, today, parsed, dry_run=dry_run, logfn=logfn)
        return
    rep_rows = find_rep_rows(ws)
    already = today_already_filled(ws, today)
    if already and not force_insert:
        logfn(f"  ⚠ '{_date_label(today)}' already present — refreshing in place "
              f"(no new column).")
    append_missing_reps(ws, parsed, rep_rows, dry_run=dry_run, logfn=logfn)
    if not (already and not force_insert):
        if dry_run:
            logfn("  (dry-run) would insert 2 fresh B+C columns.")
        else:
            insert_two_cols_at_b(ws)
    rep_rows = find_rep_rows(ws)   # re-read after append (+ insert)
    write_today(ws, today, parsed, rep_rows, dry_run=dry_run, logfn=logfn)
    _post_write_structure(ws, today, parsed, rep_rows, dry_run=dry_run, logfn=logfn)

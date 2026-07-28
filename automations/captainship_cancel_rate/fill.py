"""Sheet writer for the Captainship Cancel Rate tabs.

TAB LAYOUT (2 sections, top to bottom) — e.g. 'Cancel Rate - Wayne (ATT Fiber)':

    A1  WAYNE RUDE
    A2  CANCEL RATE 0-30 DAYS      B2  Tue 7/28/26     <- section header + date
    A3  Captainship Avg            B3  7.7%
    A4  Rep                        B4  %               <- column-header row
    A5  Wayne Rude                 B5  7.5%
    ...                                                <- rep rows (ICD owners)
    (blank spacer rows)
    A15 CANCEL RATE 30-60 DAYS     B15 Tue 7/28/26
    A16 Captainship Avg            B16 15.7%
    A17 Rep                        B17 %
    A18 Mason Davis                B18 ...

One value column per day, NEWEST IN B — history grows to the right (same
convention as the churn tabs in this workbook).

EACH DAILY RUN
  1. Grow the grid if it's running out of columns.
  2. Insert ONE fresh column at B across the rep-data rows, then paste
     yesterday's formatting (now in C) onto it. Row 1 (the captain's name)
     is preserved.
     Skipped when B already carries today's date label — a re-run refreshes
     the values in place instead of adding a second column for the same day
     (--force-insert overrides).
  3. Write today's date label into each section header's B.
  4. Write the Captainship Avg + every matched ICD owner's % into B.
  5. Owners in Tableau with no row on the tab get one appended to their
     section; owners on the tab with no Tableau value today are reported
     (never deleted, never hidden — the sheet owner decides).

Rows are found by their column-A LABEL, columns by the date header. No
hardcoded indices — the templates drift.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Optional

from automations.recruiting_report.fill import open_by_key, _retry
from automations.captainship_cancel_rate import captains as C
from automations.captainship_cancel_rate.pull import P_030, P_3060

# canonical period -> the col-A section-header marker (uppercase, normalized).
SECTION_LABELS = (
    (P_030,  "CANCEL RATE 0-30 DAYS"),
    (P_3060, "CANCEL RATE 30-60 DAYS"),
)

# Keep this much empty room to the right so the daily insert never runs the
# grid out of columns mid-run.
MIN_SPARE_COLS = 12
GROW_COLS_BY = 40

_WEEKDAY_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _norm(s: str) -> str:
    """Match key for names AND labels: uppercase, trimmed, inner whitespace
    collapsed. Tableau shouts, the tabs use Title Case — normalize both."""
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def _date_label(today: dt.date) -> str:
    """'Tue 7/28/26' — the exact format already on these tabs. Built by hand
    because %-m / %-d are glibc-only and this has to run on Windows too."""
    return (f"{_WEEKDAY_SHORT[today.weekday()]} "
            f"{today.month}/{today.day}/{today.year % 100}")


def open_ws(tab: str, *, real: bool = False):
    return open_by_key(C.sheet_id(real)).worksheet(tab)


# ------------------------------------------------------------------ structure
def find_sections(ws) -> dict:
    """Locate both sections by scanning col A for their header labels.

    Returns {period: {header_row, avg_row, rep_header_row,
                      rep_rows: {NORMALIZED_NAME: row}}} — all 1-indexed.
    Call BEFORE the column insert (that shifts columns, not rows)."""
    grid = _retry(ws.get_all_values)
    col_a = [(r[0] if r else "") for r in grid]
    n_rows = len(col_a)

    found: dict[str, int] = {}
    for i, label in enumerate(col_a):
        norm = _norm(label)
        for period, marker in SECTION_LABELS:
            if period not in found and marker in norm:
                found[period] = i + 1
                break

    sections: dict = {}
    ordered = sorted(found.items(), key=lambda kv: kv[1])
    for idx, (period, header_row) in enumerate(ordered):
        end_row = (ordered[idx + 1][1] - 1 if idx + 1 < len(ordered) else n_rows)

        avg_row = rep_header_row = None
        for r in range(header_row + 1, min(end_row, n_rows) + 1):
            norm = _norm(col_a[r - 1])
            if norm == "REP":
                rep_header_row = r
                break
            if avg_row is None and "AVG" in norm:
                avg_row = r
        # Canonical offsets as a fallback so a tab that loses a label still runs.
        if rep_header_row is None:
            rep_header_row = header_row + 2
        if avg_row is None:
            avg_row = header_row + 1

        rep_rows: dict[str, int] = {}
        for r in range(rep_header_row + 1, min(end_row, n_rows) + 1):
            name = col_a[r - 1].strip()
            if not name:
                continue
            norm = _norm(name)
            if norm == "REP" or "AVG" in norm or "CANCEL RATE" in norm:
                continue        # never let a structural row into the rep map
            rep_rows[_norm(name)] = r

        sections[period] = {
            "header_row": header_row,
            "avg_row": avg_row,
            "rep_header_row": rep_header_row,
            "rep_rows": rep_rows,
        }
    return sections


def ensure_columns(ws, *, dry_run: bool = False, logfn=print) -> None:
    """Append columns when the grid is nearly full. These tabs ship with 4
    columns and grow by one per day; without this the daily insert would push
    the oldest column off the right edge of the grid and lose it."""
    grid = _retry(ws.get_all_values)
    used = max((len(r) for r in grid), default=0)
    if ws.col_count - used >= MIN_SPARE_COLS:
        return
    target = ws.col_count + GROW_COLS_BY
    if dry_run:
        logfn(f"  (dry-run) would grow the grid from {ws.col_count} to "
              f"{target} columns ({used} in use)")
        return
    logfn(f"  Growing grid: {ws.col_count} -> {target} columns ({used} in use)")
    ws.spreadsheet.batch_update({"requests": [{
        "appendDimension": {"sheetId": ws.id, "dimension": "COLUMNS",
                            "length": GROW_COLS_BY}}]})
    time.sleep(1)


def today_already_filled(ws, sections: dict, today: dt.date) -> bool:
    """True when column B of any section header already carries today's label
    — i.e. an earlier run today already inserted the day's column."""
    label = _date_label(today)
    if not sections:
        return False
    rows = sorted({s["header_row"] for s in sections.values()})
    cells = _retry(ws.batch_get, [f"B{r}" for r in rows])
    for got in cells:
        val = (got[0][0] if got and got[0] else "")
        if (val or "").strip() == label:
            return True
    return False


def insert_col_at_b(ws, sections: dict, *, dry_run: bool = False,
                    logfn=print) -> None:
    """Insert ONE column at B across the data rows, then paste yesterday's
    formatting (now in C) onto the new B.

    Row 1 (the captain's name banner) is preserved: the insert range starts at
    the first section's header row, so a merge or banner above it is never
    split — Sheets rejects a range that partially intersects a merge."""
    if not sections:
        return
    preserve_top_rows = min(s["header_row"] for s in sections.values()) - 1
    last_row = ws.row_count
    if dry_run:
        logfn(f"  (dry-run) would insert 1 column at B, rows "
              f"{preserve_top_rows + 1}..{last_row}, and copy C's formatting")
        return

    ws.spreadsheet.batch_update({"requests": [{
        "insertRange": {
            "range": {"sheetId": ws.id,
                      "startRowIndex": preserve_top_rows, "endRowIndex": last_row,
                      "startColumnIndex": 1, "endColumnIndex": 2},
            "shiftDimension": "COLUMNS",
        }}]})
    time.sleep(1)

    # C = yesterday's column (just shifted out of B) -> the format template.
    ws.spreadsheet.batch_update({"requests": [{
        "copyPaste": {
            "source": {"sheetId": ws.id,
                       "startRowIndex": preserve_top_rows, "endRowIndex": last_row,
                       "startColumnIndex": 2, "endColumnIndex": 3},
            "destination": {"sheetId": ws.id,
                            "startRowIndex": preserve_top_rows, "endRowIndex": last_row,
                            "startColumnIndex": 1, "endColumnIndex": 2},
            "pasteType": "PASTE_FORMAT",
        }}]})
    # Let the paste commit before any values land, or the write can hit the
    # pre-insert column.
    time.sleep(2)


# ------------------------------------------------------------------- roster
def insert_missing_reps(ws, sections: dict, data: dict, *,
                        dry_run: bool = False, logfn=print) -> dict:
    """Append a row for every ICD owner Tableau has a value for but the tab
    has no row for. Returns {period: [names]} and updates sections in place.

    Inserts are batched bottom-section-first so the row indices captured in
    `sections` stay valid while the batch is being built; the final write
    positions account for every insert above them."""
    reps = data.get("reps", {})
    if not reps:
        return {}

    requests: list[dict] = []
    added: dict = {}
    for period, sect in sorted(sections.items(),
                               key=lambda kv: kv[1]["header_row"], reverse=True):
        existing = set(sect["rep_rows"].keys())
        missing = sorted(name for name, slot in reps.items()
                         if _norm(name) not in existing
                         and (slot.get(period) or "").strip())
        if not missing:
            continue
        anchor = (max(sect["rep_rows"].values()) if sect["rep_rows"]
                  else sect["rep_header_row"])
        requests.append({"_period": period, "_anchor": anchor, "_names": missing})
        added[period] = missing

    if not requests:
        return {}
    if dry_run:
        for req in requests:
            logfn(f"  (dry-run) would add {len(req['_names'])} ICD(s) to the "
                  f"{req['_period']} section at row {req['_anchor'] + 1}: "
                  f"{req['_names']}")
        return added

    ws.spreadsheet.batch_update({"requests": [{
        "insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": req["_anchor"],
                      "endIndex": req["_anchor"] + len(req["_names"])},
            "inheritFromBefore": True,
        }} for req in requests]})
    time.sleep(1)

    def _shift_above(req) -> int:
        return sum(len(r["_names"]) for r in requests
                   if r["_anchor"] < req["_anchor"])

    cells = []
    for req in requests:
        base = req["_anchor"] + _shift_above(req)
        for i, name in enumerate(req["_names"]):
            cells.append({"range": f"{ws.title}!A{base + 1 + i}",
                          "values": [[name]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": cells})

    # Re-resolve every row index the inserts pushed down.
    for req in sorted(requests, key=lambda r: r["_anchor"]):
        delta = len(req["_names"])
        for s in sections.values():
            if s["header_row"] > req["_anchor"]:
                s["header_row"] += delta
                s["avg_row"] += delta
                s["rep_header_row"] += delta
                s["rep_rows"] = {n: (r + delta if r > req["_anchor"] else r)
                                 for n, r in s["rep_rows"].items()}
    for req in requests:
        base = req["_anchor"] + _shift_above(req)
        for i, name in enumerate(req["_names"]):
            sections[req["_period"]]["rep_rows"][_norm(name)] = base + 1 + i
    return added


# -------------------------------------------------------------------- write
def write_today(ws, sections: dict, today: dt.date, data: dict, *,
                dry_run: bool = False, logfn=print) -> dict:
    """Write the date label + Captainship Avg + every matched owner's % into
    column B. Returns {period: {filled, unmatched, blank}}."""
    label = _date_label(today)
    reps = data.get("reps", {})
    avg = data.get("avg", {})
    # Tableau's spelling vs the tab's spelling differ only in case/spacing once
    # the ICD Aliases pass has run — match on the normalized key.
    by_key = {_norm(n): slot for n, slot in reps.items()}
    cells: list[dict] = []
    summary: dict = {}

    for period, sect in sections.items():
        cells.append({"range": f"{ws.title}!B{sect['header_row']}",
                      "values": [[label]]})
        avg_val = (avg.get(period) or "").strip()
        cells.append({"range": f"{ws.title}!B{sect['avg_row']}",
                      "values": [[avg_val]]})
        # The column-insert copies FORMAT only, so the '%' label under 'Rep'
        # doesn't ride along with the new column — rewrite it every run.
        cells.append({"range": f"{ws.title}!B{sect['rep_header_row']}",
                      "values": [["%"]]})

        filled, blank = 0, []
        for key, row in sect["rep_rows"].items():
            val = ((by_key.get(key) or {}).get(period) or "").strip()
            if val:
                filled += 1
            else:
                # An owner on the tab with no value today: write "" so the
                # number pasted in from yesterday's column can never sit under
                # today's date pretending to be fresh.
                blank.append(key.title())
            cells.append({"range": f"{ws.title}!B{row}", "values": [[val]]})

        unmatched = sorted(n for n, slot in reps.items()
                           if _norm(n) not in sect["rep_rows"]
                           and (slot.get(period) or "").strip())
        summary[period] = {"filled": filled, "unmatched": unmatched,
                           "blank": sorted(blank), "avg": avg_val}

    if dry_run:
        for period, s in summary.items():
            logfn(f"  (dry-run) {period}: avg {s['avg'] or '-'}, "
                  f"{s['filled']} owner cell(s), {len(s['blank'])} blank, "
                  f"{len(s['unmatched'])} unmatched")
        return summary

    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": cells})
    return summary


def recent_history(ws, sections: dict, lookback_cols: int = 5) -> dict:
    """{period: {NORMALIZED_NAME: had_recent_data}} — did this owner carry a
    value in any of the last `lookback_cols` columns AFTER today's B? Lets the
    run tell 'never had data' apart from 'stopped filling' (went dark)."""
    grid = _retry(ws.get_all_values)
    out: dict = {}
    for period, sect in sections.items():
        seen: dict = {}
        for key, row in sect["rep_rows"].items():
            vals = grid[row - 1] if row - 1 < len(grid) else []
            window = vals[2:2 + lookback_cols]      # C.. (skip today's B)
            seen[key] = any((v or "").strip() for v in window)
        out[period] = seen
    return out

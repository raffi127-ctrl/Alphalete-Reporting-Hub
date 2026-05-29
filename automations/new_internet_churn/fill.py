"""Write today's Raf-Local-Office Churn data to the AT&T Fiber Metrics
Report sheet's 'Local Office - New Internet Churn' tab.

DESTINATION LAYOUT (4 churn-period sections, top to bottom):
    NEW INTERNET CHURN \n0-30 DAYS    | <date>  (merged B+C)
    Office Avg                         | pct     | units
    Rep                                | %       | units    (column-header row)
    <reps>                             | pct     | units
    (~6 blank rows)
    NEW INTERNET CHURN \n30 DAYS       | <date>  (merged B+C)
    ...
    (...repeat for 60 + 90 DAYS sections)

EACH DAILY RUN:
  1. Insert 2 fresh columns at B+C (sheet-wide). The previous most-recent
     date columns shift right to D+E. Sections aren't synchronized
     date-wise — each section just shows whatever its prior fill date was
     in the next column over. The newly-inserted B+C is empty.
  2. For each section: merge B+C in its header row + write today's date
     label (e.g. 'Thu 5/28/26').
  3. Write Office Avg's pct in B, units (N/D) in C.
  4. Match every rep in our pulled data to their existing row by name (in
     col A). Write the rep's pct + units into that row's B+C. Reps with
     no Tableau data for this period get blank cells (the per-cell
     conditional formatting in the sheet renders that as 'no entry').
  5. Reps in Tableau but not in the sheet's roster are logged as
     'unmatched' so Megan can add them by hand if needed.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Optional

from automations.new_internet_churn import pull
from automations.recruiting_report.fill import open_by_key

SHEET_ID = "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8"
TAB_LOCAL_OFFICE = "Local Office - New Internet Churn"

PERIOD_SECTION_LABELS = (
    # canonical period → marker substring (uppercase, whitespace-normalized)
    ("0-30", "0-30 DAYS"),
    ("30",   "30 DAYS"),
    ("60",   "60 DAYS"),
    ("90",   "90 DAYS"),
)

# Hide rule: after today's fill, hide any rep whose TODAY % cell is
# blank (no data this fill); unhide rows that have a non-blank today.
# Simpler than tracking 5-weeks-of-history because the cell is right
# there in col B after write_today. Names are never deleted (Megan
# 2026-05-28: "don't delete any names, just hide").

_WEEKDAY_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def open_ws():
    return open_by_key(SHEET_ID).worksheet(TAB_LOCAL_OFFICE)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().upper())


def _has_nonzero_pct(slot: Optional[dict]) -> bool:
    """True if `slot` carries a non-zero churn %. Used by auto-insert to
    skip 0% reps (Megan: only add reps with at least one meaningful churn)."""
    if not slot:
        return False
    pct_raw = (slot.get("pct") or "").strip().rstrip("%")
    if not pct_raw:
        return False
    try:
        return float(pct_raw) > 0
    except ValueError:
        return False


def _col_index_to_letter(idx_0: int) -> str:
    """Convert a 0-indexed column number to its A1 letter
    (0→'A', 25→'Z', 26→'AA', 51→'AZ', 52→'BA', …)."""
    n = idx_0
    out = ""
    while True:
        n, rem = divmod(n, 26)
        out = chr(ord("A") + rem) + out
        if n == 0:
            return out
        n -= 1


def _date_label(today: dt.date) -> str:
    """Build the section-header date label in Eve's format ('Thu 5/28/26').
    Hand-rolled instead of strftime('%a %-m/%-d/%y') because %-m / %-d
    are Mac/Linux only — they crash on Windows. Cross-platform per
    workflows/report-validation-checklist.md."""
    return f"{_WEEKDAY_SHORT[today.weekday()]} {today.month}/{today.day}/{today.year % 100}"


def find_sections(ws) -> dict:
    """Locate each churn-period section's anchor rows by scanning col A
    for the section-header label. Returns a dict keyed by canonical
    period name with the rows + a {rep_name_lower → row} map per section.

    Called BEFORE the 2-col insert so the returned row numbers are still
    valid (insert shifts columns, not rows)."""
    grid = ws.get_all_values()
    col_a = [(r[0] if r else "") for r in grid]
    n_rows = len(col_a)

    # 1. Find the header row for each period. We scan top-to-bottom and
    # match on "NEW INTERNET CHURN" + the period marker. We check 0-30
    # FIRST so the broader "30 DAYS" check on the next iteration doesn't
    # eat the 0-30 row.
    found: dict[str, int] = {}
    for i, label in enumerate(col_a):
        norm = _norm(label)
        # Match BOTH 'NEW INTERNET CHURN ... DAYS' (New Internet tab) and
        # 'WIRELESS CHURN ... DAYS' (Wireless tab). The wireless tab is
        # structurally identical except (a) different label prefix and
        # (b) no Churn Tiers reference block at the top, so the first
        # section starts at row 1 not row 7.
        if "CHURN" not in norm or "DAY" not in norm:
            continue
        for period, marker in PERIOD_SECTION_LABELS:
            if period in found:
                continue
            if marker not in norm:
                continue
            # disambiguate "30 DAYS" inside "0-30 DAYS"
            if period == "30" and "0-30" in norm:
                continue
            found[period] = i + 1   # 1-indexed sheet row
            break

    # 2. For each period in row-order, derive office_avg_row + rep_header_row
    # + the rep_name → row map. A section's rep block runs from
    # (rep_header_row + 1) until just before the next section's header
    # (or end of sheet for the last one).
    sections: dict = {}
    sorted_periods = sorted(found.items(), key=lambda kv: kv[1])
    for idx, (period, header_row) in enumerate(sorted_periods):
        end_row = (sorted_periods[idx + 1][1] - 1
                   if idx + 1 < len(sorted_periods) else n_rows)
        rep_rows: dict[str, int] = {}
        for r in range(header_row + 3, end_row + 1):
            if r > n_rows:
                break
            name = col_a[r - 1].strip()
            if not name:
                continue
            rep_rows[name.lower()] = r
        sections[period] = {
            "header_row": header_row,
            "office_avg_row": header_row + 1,
            "rep_header_row": header_row + 2,
            "rep_rows": rep_rows,
        }
    return sections


def insert_missing_reps(
    ws,
    sections: dict,
    parsed: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> dict:
    """For each rep that appears in Tableau but doesn't already have a
    row in their section's chart, append a new row at the BOTTOM of that
    section (just above the next section's blank-gap). Returns
    {period: [added_rep_names]} and updates `sections[period]["rep_rows"]`
    in place so the subsequent write_today call knows where to find them.

    Inserts happen BOTTOM-section-first so earlier section row indices
    don't shift mid-loop. Each section's `header_row` references are
    re-resolved from the live grid after the inserts complete.
    """
    reps = parsed.get("reps", {})
    if not reps:
        return {}

    # Identify the bottom-most existing rep row per section. That's the
    # anchor — new rows insert just AFTER it (i.e. row + 1).
    sorted_periods = sorted(
        sections.items(), key=lambda kv: kv[1]["header_row"], reverse=True,
    )

    added: dict = {}
    insert_requests: list[dict] = []

    for period, sect in sorted_periods:
        existing_lc = set(sect["rep_rows"].keys())
        missing = sorted(
            rep_name for rep_name, periods in reps.items()
            if rep_name.lower() not in existing_lc
        )
        # Only auto-insert when the rep has a NON-ZERO churn % for THIS
        # period (Megan 2026-05-28: "skip 0% inserts"). Rationale: a 0%
        # churn rep is technically active but not actionable — keep them
        # out of the roster until they actually churn at least once.
        # They still get included in the Office Avg calculation upstream
        # (Tableau already aggregated the totals), and can be added by
        # hand later if Megan ever wants them tracked.
        missing = [m for m in missing if _has_nonzero_pct(reps[m].get(period))]
        if not missing:
            continue
        # Anchor row = max existing rep row in this section.
        anchor = max(sect["rep_rows"].values()) if sect["rep_rows"] else sect["rep_header_row"]
        # We insert N rows starting AT (anchor + 1).
        insert_requests.append({
            "_period": period,
            "_anchor": anchor,
            "_names": missing,
        })
        added[period] = missing

    if not insert_requests:
        return {}

    if dry_run:
        for req in insert_requests:
            logfn(f"  (dry-run) would insert {len(req['_names'])} reps "
                  f"into '{req['_period']}' section at row {req['_anchor'] + 1}: "
                  f"{req['_names']}")
        return added

    # Apply inserts bottom-up. Each insert shifts all rows below the
    # insertion point by N; sections ABOVE this one are unaffected.
    batch_requests: list[dict] = []
    for req in insert_requests:
        n = len(req["_names"])
        anchor = req["_anchor"]
        batch_requests.append({
            "insertDimension": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "ROWS",
                    "startIndex": anchor,           # 0-indexed → inserts AT row (anchor + 1)
                    "endIndex": anchor + n,
                },
                "inheritFromBefore": True,
            }
        })
    ws.spreadsheet.batch_update({"requests": batch_requests})

    # Write the rep names into col A of the freshly-inserted rows.
    name_cells: list[dict] = []
    for req in insert_requests:
        anchor = req["_anchor"]
        for i, name in enumerate(req["_names"]):
            row_num = anchor + 1 + i
            name_cells.append({
                "range": f"{ws.title}!A{row_num}",
                "values": [[name]],
            })
    ws.spreadsheet.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": name_cells,
    })

    # Re-resolve sections in case insertions changed downstream row numbers.
    # Cheaper than a full re-scan: walk the insert requests from bottom up
    # and shift any section whose header_row sits below the insert point.
    sorted_inserts_top_down = sorted(insert_requests, key=lambda r: r["_anchor"])
    for req in sorted_inserts_top_down:
        delta = len(req["_names"])
        for p, s in sections.items():
            if s["header_row"] > req["_anchor"]:
                s["header_row"] += delta
                s["office_avg_row"] += delta
                s["rep_header_row"] += delta
                s["rep_rows"] = {
                    name: (row + delta if row > req["_anchor"] else row)
                    for name, row in s["rep_rows"].items()
                }
        # Add the freshly-inserted reps to their section's rep_rows map.
        p = req["_period"]
        for i, name in enumerate(req["_names"]):
            sections[p]["rep_rows"][name.lower()] = req["_anchor"] + 1 + i
    return added


def today_already_filled(ws, sections: dict, today: dt.date) -> bool:
    """Return True if the leftmost date column (B) of any section
    already carries today's date label — that means a previous run or
    Eve's manual fill already added today's column, and we should NOT
    insert another one (idempotency)."""
    if not sections:
        return False
    label = _date_label(today)
    for sect in sections.values():
        cell = ws.cell(sect["header_row"], 2).value or ""
        if cell.strip() == label:
            return True
    return False


def _find_formatted_template_col_after_insert(ws, section_header_row: int) -> Optional[int]:
    """Scan the cols after the just-inserted B+C looking for the first
    col with Eve's template orange-peach section-header background on
    `section_header_row`. Returns the 0-indexed col number, or None if
    no formatted col was found.

    Why: prior --force-insert runs left unformatted col pairs in
    positions D, F, etc. We can't paste from D+E if D is one of OUR
    earlier unformatted runs — we need to scan past them to find Eve's
    actual template col before pasting from it."""
    rng = f"{ws.title}!B{section_header_row}:Z{section_header_row}"
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/"
           f"{ws.spreadsheet.id}?ranges={rng}&includeGridData=true"
           f"&fields=sheets(data(rowData(values(userEnteredFormat(backgroundColor)))))")
    try:
        result = ws.spreadsheet.client.request("get", url).json()
    except Exception:
        return None
    rows = result.get('sheets', [{}])[0].get('data', [{}])[0].get('rowData', [])
    if not rows:
        return None
    values = rows[0].get('values', [])
    # Eve's section-header orange-peach: red ~0.96, green ~0.70, blue ~0.42.
    # Scan starting at col B (idx 1); the offset within `values` is 0
    # (since rng started at col B).
    for offset, cell in enumerate(values):
        bg = cell.get('userEnteredFormat', {}).get('backgroundColor', {})
        red = bg.get('red', 0.0)
        green = bg.get('green', 0.0)
        blue = bg.get('blue', 0.0)
        # Orange-peach signature
        if 0.93 <= red <= 1.0 and 0.62 <= green <= 0.76 and 0.35 <= blue <= 0.48:
            return 1 + offset       # 0-indexed sheet col
    return None


_CHURN_TIERS_PRESERVE_ROWS = 3   # rows 1-3 on tabs that carry the block


def _detect_preserve_top_rows(ws) -> int:
    """Return the number of top rows to preserve when inserting today's
    B+C cols. Tabs with the CHURN TIERS reference block at A1 (NEW INT
    tabs, Local Office + Captainship) keep rows 1-3 static. Tabs without
    it (Wireless) preserve nothing — section header starts at row 1.

    Detected by reading A1: if it contains 'CHURN TIERS', preserve rows
    1-3. Megan 2026-05-29: 'this top section never changes'."""
    try:
        a1 = (ws.acell("A1").value or "").upper()
    except Exception:
        return 0
    return _CHURN_TIERS_PRESERVE_ROWS if "CHURN TIERS" in a1 else 0


def insert_two_cols_at_b(ws, sections: Optional[dict] = None) -> None:
    """Insert 2 new B+C columns into the rep-data area ONLY (rows
    preserve_top_rows..end), then paste yesterday's formatting from D+E
    (just shifted from B+C by the insert) onto the new B+C.

    Uses insertRange with shiftDimension=COLUMNS — shifts existing cells
    right by 2 WITHIN the rep-data rows only. Rows 1..preserve_top_rows
    (the CHURN TIERS reference block on NEW INT tabs) stay put.

    Megan 2026-05-29:
      * 'this top section never changes' — rows 1-3 cols A-G on NEW INT
        tabs are the CHURN TIERS reference block; prior insertDimension
        was shifting the whole column sheet-wide, dragging that block
        right by 2 every day.
      * 'formatting from the previous pull should be copied exactly' —
        D+E (post-insert yesterday) is the source of truth; copyPaste
        PASTE_NORMAL brings over values + formatting + merges +
        conditional rules.
    """
    last_row = ws.row_count
    preserve_top_rows = _detect_preserve_top_rows(ws)

    # Pass 1: insert a 2-col-wide blank range at rows
    # (preserve_top_rows..end) cols B-C, shifting existing cells right
    # WITHIN those rows only (insertRange respects the row bounds).
    ws.spreadsheet.batch_update({"requests": [{
        "insertRange": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": preserve_top_rows,    # 0-indexed inclusive
                "endRowIndex":   last_row,             # exclusive
                "startColumnIndex": 1,                 # B
                "endColumnIndex":   3,                 # C+1 exclusive
            },
            "shiftDimension": "COLUMNS",
        }
    }]})
    # Brief wait so the insert is fully committed server-side.
    time.sleep(1)

    # Pass 2: paste yesterday's pull (D+E, just shifted from B+C by the
    # insert above) onto today's new B+C. Same row range — preserve_top_rows
    # to last_row — so the CHURN TIERS block at rows 1-3 isn't repainted.
    paste_src = {
        "sheetId": ws.id,
        "startRowIndex": preserve_top_rows,
        "endRowIndex": last_row,
        "startColumnIndex": 3,    # D (0-indexed) = yesterday's pull, post-insert
        "endColumnIndex": 5,      # F exclusive
    }
    paste_dst = {
        "sheetId": ws.id,
        "startRowIndex": preserve_top_rows,
        "endRowIndex": last_row,
        "startColumnIndex": 1,    # B
        "endColumnIndex": 3,      # D exclusive
    }
    ws.spreadsheet.batch_update({"requests": [
        {"copyPaste": {"source": paste_src, "destination": paste_dst,
                       "pasteType": "PASTE_NORMAL"}},
    ]})
    # Wait for the paste to fully commit server-side before the next
    # values_batch_update fires. Without this, writes can land on the
    # OLD col B (which became D after the insert settled).
    time.sleep(3)


def _merge_section_headers(ws, sections: dict) -> None:
    """Merge B+C in each section's header row so the date label spans
    the two columns visually (matches Eve's manual format)."""
    requests = [{
        "mergeCells": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": sect["header_row"] - 1,
                "endRowIndex": sect["header_row"],
                "startColumnIndex": 1,
                "endColumnIndex": 3,
            },
            "mergeType": "MERGE_ALL",
        }
    } for sect in sections.values()]
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def write_today(
    ws,
    sections: dict,
    today: dt.date,
    parsed: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> dict:
    """Fill the newly-inserted B+C across all 4 sections with today's
    data. Returns a per-section summary {period: {filled, blank, unmatched}}.

    Cell-value semantics:
      - pct (col B): USER_ENTERED so '1.47%' parses to 0.0147 and the
        sheet's conditional formatting reads the numeric value.
      - units (col C): RAW so '1/7' stays as the literal string and is
        NOT auto-interpreted as a date (1/7 → Jan 7).
      - Missing data (rep has no value this period): both cells left blank.
    """
    office = parsed.get("office_total", {})
    reps = parsed.get("reps", {})

    pct_cells: list[dict] = []   # USER_ENTERED batch
    raw_cells: list[dict] = []   # RAW batch
    summary: dict = {}

    date_label = _date_label(today)

    for period, sect in sections.items():
        # 1. Section header — merged B+C, write date label into B
        pct_cells.append({
            "range": f"{ws.title}!B{sect['header_row']}",
            "values": [[date_label]],
        })

        # 1b. Rep-header row — write '%' to B + 'units' to C so each
        # date column has its own filterable column labels (matches Eve's
        # template; copy-format from insert_two_cols_at_b preserves the
        # filter range so the filter icons keep working in each section).
        # Sections' rep_header_row is found dynamically by find_sections,
        # so we never hardcode '9' or '51' or similar.
        pct_cells.append({
            "range": f"{ws.title}!B{sect['rep_header_row']}",
            "values": [["%"]],
        })
        pct_cells.append({
            "range": f"{ws.title}!C{sect['rep_header_row']}",
            "values": [["units"]],
        })

        # 2. Office Avg row — B = pct, C = units
        odata = office.get(period, {})
        pct_cells.append({
            "range": f"{ws.title}!B{sect['office_avg_row']}",
            "values": [[odata.get("pct", "")]],
        })
        raw_cells.append({
            "range": f"{ws.title}!C{sect['office_avg_row']}",
            "values": [[pull.fmt_units(odata)]],
        })

        # 3. Per-rep rows — only consider reps with actual data for THIS
        # period. The newly-inserted B+C are already empty, so reps with
        # no data this period just stay blank (no explicit write needed).
        sect_summary = {"filled": 0, "unmatched": []}
        rep_rows = sect["rep_rows"]
        for rep_name, rep_periods in reps.items():
            pdata = rep_periods.get(period)
            if not pdata or not pdata.get("pct"):
                continue   # rep has no data here; B+C already blank
            # Write 0.00% + units too (Megan 2026-05-29 reversal of the
            # 2026-05-28 skip rule — the team wants 0% reps SHOWN with
            # their unit count, not left blank). Auto-insert still
            # filters 0%-only reps to avoid roster bloat — they appear
            # here only if they're already in the existing roster.
            row = rep_rows.get(rep_name.lower())
            if row is None:
                # Has data but no row. With auto-insert keeping its
                # non-zero-only rule, this path is for 0% reps the team
                # hasn't added to the roster yet. Skip silently (would
                # otherwise be noisy); flag genuine surprises only.
                if _has_nonzero_pct(pdata):
                    sect_summary["unmatched"].append(rep_name)
                continue
            pct_cells.append({
                "range": f"{ws.title}!B{row}",
                "values": [[pdata.get("pct", "")]],
            })
            raw_cells.append({
                "range": f"{ws.title}!C{row}",
                "values": [[pull.fmt_units(pdata)]],
            })
            sect_summary["filled"] += 1
        summary[period] = sect_summary

    if dry_run:
        logfn(f"  (dry-run) would write {len(pct_cells)} pct cells "
              f"+ {len(raw_cells)} units cells")
        return summary

    sh = ws.spreadsheet
    # pct cells (incl. section header date label) → USER_ENTERED
    sh.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": pct_cells,
    })
    # units cells (N/D fractions) → RAW so 1/7 isn't read as 7-Jan
    sh.values_batch_update({
        "valueInputOption": "RAW",
        "data": raw_cells,
    })
    return summary


def apply_filters(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> None:
    """Set up filters per section.

    Sheets allows ONE basic filter per sheet (always-visible dropdowns),
    so we put that on the FIRST section's rep-header row (the most-
    prominent visual). The other 3 sections get saved FILTER VIEWS,
    accessible from Data → Filter views in the Sheets UI.

    Idempotent across runs: clear the existing basic filter and any
    prior filter views we installed before re-adding.
    """
    if not sections:
        return

    sorted_periods = sorted(sections.items(), key=lambda kv: kv[1]["header_row"])

    def section_range(idx_in_sorted: int) -> dict:
        sect = sorted_periods[idx_in_sorted][1]
        rep_hdr_row = sect["rep_header_row"]
        if idx_in_sorted + 1 < len(sorted_periods):
            last_row = sorted_periods[idx_in_sorted + 1][1]["header_row"] - 1
        else:
            last_row = ws.row_count
        return {
            "sheetId": ws.id,
            "startRowIndex": rep_hdr_row - 1,    # 0-indexed inclusive
            "endRowIndex":   last_row,           # 0-indexed exclusive
            "startColumnIndex": 0,
            "endColumnIndex":   ws.col_count,
        }

    if dry_run:
        logfn(f"  (dry-run) would set basic filter on first section + "
              f"{len(sorted_periods) - 1} saved filter views")
        return

    # First, find + delete any prior filter views we installed.
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{ws.spreadsheet.id}"
           f"?fields=sheets(properties(sheetId),filterViews(title,filterViewId))")
    result = ws.spreadsheet.client.request("get", url).json()
    our_titles = {f"{p}-Day Section" for p, _ in sorted_periods}
    delete_requests: list[dict] = []
    for sheet in result.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") != ws.id:
            continue
        for fv in sheet.get("filterViews", []) or []:
            if fv.get("title") in our_titles:
                delete_requests.append({
                    "deleteFilterView": {"filterId": fv["filterViewId"]}
                })

    # Clear basic filter, then re-set on first section.
    requests: list[dict] = list(delete_requests)
    requests.append({"clearBasicFilter": {"sheetId": ws.id}})
    requests.append({"setBasicFilter": {
        "filter": {"range": section_range(0)}
    }})
    # Saved filter views for remaining sections.
    for idx in range(1, len(sorted_periods)):
        period = sorted_periods[idx][0]
        requests.append({
            "addFilterView": {
                "filter": {
                    "title": f"{period}-Day Section",
                    "range": section_range(idx),
                }
            }
        })
    ws.spreadsheet.batch_update({"requests": requests})


_PCT_THRESHOLDS = {
    # period → (green-cap, red-floor) — from Eve's transcript
    "0-30": (2.0, 3.5),
    "30":   (5.0, 8.0),
    "60":   (5.0, 8.0),
    "90":   (5.0, 8.0),
}
_PCT_GREEN  = {"red": 147/255, "green": 196/255, "blue": 125/255}
_PCT_YELLOW = {"red": 255/255, "green": 217/255, "blue": 102/255}
_PCT_RED    = {"red": 224/255, "green": 102/255, "blue": 102/255}


def _pct_color_for(period: str, pct_str: str) -> Optional[dict]:
    raw = (pct_str or "").strip().rstrip("%")
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    g_cap, r_floor = _PCT_THRESHOLDS.get(period, (2.0, 3.5))
    if v <= g_cap:
        return _PCT_GREEN
    if v >= r_floor:
        return _PCT_RED
    return _PCT_YELLOW


def apply_pct_direct_colors(
    ws,
    sections: dict,
    parsed: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> None:
    """Set DIRECT background color on each pct cell (col B) — Office
    Avg + every rep with non-blank pct — using Eve's threshold logic
    (≤ green-cap = green, ≥ red-floor = red, else yellow).

    Required because Eve's existing conditional-format rules don't
    cover every rep row (only the ones she's filled by hand before);
    cells outside their range stay white even after we write a value.
    Setting a DIRECT background works regardless of rule coverage —
    in cells Eve's rule covers, the rule still wins on top, so the
    visible state is unchanged for those. Cells NOT covered by her
    rule fall back to our direct color, which matches her logic
    anyway, so the visual result is uniform across all rep rows.
    """
    reps = parsed.get("reps", {})
    office_total = parsed.get("office_total", {})
    requests: list[dict] = []

    for period, sect in sections.items():
        rep_rows = sect["rep_rows"]
        # Office Avg row.
        odata = office_total.get(period, {})
        bg = _pct_color_for(period, odata.get("pct", ""))
        if bg is not None:
            requests.append({"repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": sect["office_avg_row"] - 1,
                    "endRowIndex":   sect["office_avg_row"],
                    "startColumnIndex": 1,
                    "endColumnIndex":   2,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }})
        # Rep rows.
        for rep_name, periods in reps.items():
            pdata = periods.get(period)
            if not pdata or not pdata.get("pct"):
                continue
            row = rep_rows.get(rep_name.lower())
            if row is None:
                continue
            bg = _pct_color_for(period, pdata.get("pct", ""))
            if bg is None:
                continue
            requests.append({"repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": row - 1,
                    "endRowIndex":   row,
                    "startColumnIndex": 1,
                    "endColumnIndex":   2,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }})

    if dry_run:
        logfn(f"  (dry-run) would paint pct backgrounds on {len(requests)} cells")
        return
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def unhide_all_rep_rows(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> None:
    """Unhide every rep row in every section. Required BEFORE
    sort_sections_via_sortrange because Sheets' sortRange skips hidden
    rows — leaving them stuck in their old positions. Without this
    step, a rep that was hidden yesterday (e.g. had 0% under the
    skip-rule) but has a real value today (e.g. Bill Hirwa: 6.67% on
    2026-05-29) stays at his old row position even after writes,
    because sort can't move him.

    hide_blanks_today runs AFTER sort to re-hide rows whose today %
    is blank — so the cycle is: unhide all → write today → sort →
    hide blanks today. Names are never deleted."""
    if not sections:
        return
    requests = []
    sorted_periods = sorted(sections.items(), key=lambda kv: kv[1]["header_row"])
    for idx, (_, sect) in enumerate(sorted_periods):
        rep_rows = sect["rep_rows"]
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        # End at the next section's header row (or sheet end for the
        # last section) so we also unhide any gap-rows that may have
        # been hidden previously.
        if idx + 1 < len(sorted_periods):
            last_row = sorted_periods[idx + 1][1]["header_row"] - 1
        else:
            last_row = ws.row_count
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "ROWS",
                    "startIndex": first_row - 1,    # 0-indexed inclusive
                    "endIndex":   last_row,         # 0-indexed exclusive
                },
                "properties": {"hiddenByUser": False},
                "fields": "hiddenByUser",
            }
        })

    if dry_run:
        logfn(f"  (dry-run) would unhide rep rows across {len(requests)} sections")
        return
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def sort_sections_via_sortrange(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> None:
    """Sort each section's rep block by today's % (col B) descending,
    using the Sheets-native sortRange request — atomic server-side, no
    client read-after-write race.

    Sheets sorts blanks to the TOP for DESCENDING. That's fine for us
    because `hide_blanks_today` runs RIGHT AFTER this and hides every
    rep row whose today % is blank — so the blank rows at the top end
    up hidden. Visual end state: non-blank reps in % desc order, blank
    reps invisible.
    """
    if not sections:
        return
    sorted_periods = sorted(sections.items(), key=lambda kv: kv[1]["header_row"])
    requests = []
    for idx, (period, sect) in enumerate(sorted_periods):
        rep_rows = sect["rep_rows"]
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        if idx + 1 < len(sorted_periods):
            last_row = sorted_periods[idx + 1][1]["header_row"] - 1
        else:
            last_row = max(rep_rows.values())
        requests.append({
            "sortRange": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": first_row - 1,    # 0-indexed inclusive
                    "endRowIndex":   last_row,          # 0-indexed exclusive
                    "startColumnIndex": 0,
                    "endColumnIndex":   ws.col_count,
                },
                "sortSpecs": [
                    {"dimensionIndex": 1, "sortOrder": "DESCENDING"}
                ],
            }
        })

    if dry_run:
        logfn(f"  (dry-run) would sortRange {len(requests)} sections by col B desc")
        return
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})

    # After server-side sort, the rep_rows map in `sections` is stale
    # (names moved to different rows). Refresh it by re-scanning col A
    # so hide_blanks_today sees the new positions.
    for period, sect in sections.items():
        rep_rows = sect["rep_rows"]
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        last_row  = max(rep_rows.values())
        col_a = ws.range(f"A{first_row}:A{last_row}")
        new_map: dict[str, int] = {}
        for offset, cell in enumerate(col_a):
            name = (cell.value or "").strip()
            if name:
                new_map[name.lower()] = first_row + offset
        sect["rep_rows"] = new_map


def apply_units_white_override(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> None:
    """Add a high-priority conditional-format rule that paints col C
    (units) WHITE regardless of value. Required because Eve's existing
    color-by-pct rules have ranges that cover 3 cols at a time
    (cols [1-4) = B + C + D), so the rule fires red on the % value
    and paints C red as a side-effect. Megan 2026-05-28: 'C - the
    units on internet - should all be white but most are red.'

    Adds 4 ranges (one per section's rep block) in a single rule at
    priority 0 (highest), so it wins over Eve's rules for col C. We
    use NOT_BLANK as the condition so the rule fires whenever the
    cell has a value, beating Eve's NUMBER_GREATER_THAN_EQ etc.

    Idempotent across runs: before adding, scans the existing rules
    and deletes any prior identical override (same condition + bg)
    so we don't pile up duplicate rules over many days of runs.
    """
    if not sections:
        return
    # Build the col-C ranges, one per section's rep block.
    ranges: list[dict] = []
    sorted_periods = sorted(sections.items(), key=lambda kv: kv[1]["header_row"])
    for idx, (_, sect) in enumerate(sorted_periods):
        first_row = sect["rep_header_row"]   # row 9 / 123 / 263 / 428
        if idx + 1 < len(sorted_periods):
            last_row = sorted_periods[idx + 1][1]["header_row"] - 1
        else:
            last_row = ws.row_count
        ranges.append({
            "sheetId": ws.id,
            "startRowIndex": first_row,         # 0-indexed → row first_row+1
            "endRowIndex":   last_row,          # 0-indexed exclusive
            "startColumnIndex": 2,              # col C
            "endColumnIndex":   3,
        })

    if dry_run:
        logfn(f"  (dry-run) would install col-C-white override with "
              f"{len(ranges)} section ranges")
        return

    # First, find + delete any prior override we added (idempotency).
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{ws.spreadsheet.id}"
           f"?fields=sheets(properties(sheetId,title),conditionalFormats)")
    result = ws.spreadsheet.client.request("get", url).json()
    delete_indices: list[int] = []
    for sheet in result.get("sheets", []):
        if sheet.get("properties", {}).get("title") != ws.title:
            continue
        for i, rule in enumerate(sheet.get("conditionalFormats", [])):
            bool_rule = rule.get("booleanRule", {})
            cond = bool_rule.get("condition", {})
            fmt = bool_rule.get("format", {}).get("backgroundColor", {})
            # Our override has: NOT_BLANK + bg white. Anything matching
            # this signature is our prior install.
            is_white = (fmt.get("red") == 1 and fmt.get("green") == 1
                        and fmt.get("blue") == 1)
            if cond.get("type") == "NOT_BLANK" and is_white:
                delete_indices.append(i)

    delete_requests = [{"deleteConditionalFormatRule": {
        "sheetId": ws.id, "index": i,
    }} for i in sorted(delete_indices, reverse=True)]

    add_request = {"addConditionalFormatRule": {
        "rule": {
            "ranges": ranges,
            "booleanRule": {
                "condition": {"type": "NOT_BLANK"},
                "format": {"backgroundColor": {"red": 1, "green": 1, "blue": 1}},
            },
        },
        "index": 0,    # highest priority — wins over Eve's % color rules
    }}

    ws.spreadsheet.batch_update({"requests": delete_requests + [add_request]})


def sort_sections_desc(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> dict:
    """Sort each section's rep block by today's % cell (col B) descending.
    Blanks sink to the bottom. Done JS-style because Sheets' built-in
    sortRange treats blank-prefixed numbers oddly and the section also
    has merged header rows we don't want to disturb.

    Returns {period: {sorted: int, rep_block_rows: (first, last)}}.
    """
    summary: dict = {}
    if not sections:
        return summary

    sorted_periods = sorted(sections.items(), key=lambda kv: kv[1]["header_row"])
    sh = ws.spreadsheet

    for idx, (period, sect) in enumerate(sorted_periods):
        rep_rows = sect["rep_rows"]
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        # End the block one row before the next section's header (or end
        # of sheet for the last section).
        if idx + 1 < len(sorted_periods):
            last_row = sorted_periods[idx + 1][1]["header_row"] - 1
        else:
            last_row = max(rep_rows.values())
        # Read the FULL block (all columns) so the sort moves entire rows.
        rng = f"{ws.title}!A{first_row}:{last_row}"
        block = sh.values_get(
            rng, params={"valueRenderOption": "FORMATTED_VALUE"},
        ).get("values", [])
        # Pad short rows so write-back lengths line up.
        max_w = max((len(r) for r in block), default=0)
        block = [r + [""] * (max_w - len(r)) for r in block]
        # Drop fully-empty rows (Sheets may return shorter blocks); we'll
        # re-pad with empty rows at the end so the destination range is
        # the same length we read.
        original_len = last_row - first_row + 1
        while len(block) < original_len:
            block.append([""] * max_w)

        def _key(row: list[str]) -> tuple:
            # B (idx 1) carries today's % e.g. '1.47%'. Blank → bottom.
            pct = (row[1] if len(row) > 1 else "").strip()
            if not pct:
                return (1, 0.0)
            try:
                # FORMATTED_VALUE may return '1.47%' or '1.47'; both parse.
                return (0, -float(pct.rstrip("%")))
            except ValueError:
                return (1, 0.0)

        sorted_block = sorted(block, key=_key)

        if dry_run:
            logfn(f"  (dry-run) would sort {period}-day section "
                  f"(rows {first_row}–{last_row}, {len(sorted_block)} rows)")
        else:
            # Two-pass write so the sort doesn't corrupt the units strings.
            # The block contains alternating cols: A=rep, B=%, C=units,
            # D=%, E=units, F=%, G=units, … Writing the whole block via
            # USER_ENTERED would make Sheets re-parse units like '1/7'
            # as Jan 7 dates — which then trip the % conditional
            # formatting (because dates are numeric) and turn the units
            # cells red. Eve's manual fills never had that problem
            # because she only typed once into the cell and never had
            # Sheets re-parse them.
            #
            # Pass 1: USER_ENTERED for the whole block — preserves %
            # conditional formatting on every pct column (the values are
            # already-percent strings; Sheets parses them as numbers).
            sh.values_update(
                rng,
                params={"valueInputOption": "USER_ENTERED"},
                body={"values": sorted_block},
            )
            # Pass 2: re-write JUST the units cells (every column at
            # an even 0-indexed offset starting at 2) with RAW so they
            # stay as literal strings — no date parsing, no conditional
            # red on the units cells.
            units_cells: list[dict] = []
            for ri, row in enumerate(sorted_block):
                for ci in range(2, len(row), 2):   # 2, 4, 6, … = units cols
                    v = row[ci] if ci < len(row) else ""
                    if not v:
                        continue
                    sheet_row = first_row + ri
                    col_letter = _col_index_to_letter(ci)
                    units_cells.append({
                        "range": f"{ws.title}!{col_letter}{sheet_row}",
                        "values": [[v]],
                    })
            if units_cells:
                sh.values_batch_update({
                    "valueInputOption": "RAW",
                    "data": units_cells,
                })
        # Refresh the rep_rows map — names moved, so the cached row
        # numbers are stale. Walk the new block + rebuild.
        new_rep_rows: dict = {}
        for offset, row in enumerate(sorted_block):
            name = (row[0] if row else "").strip()
            if name:
                new_rep_rows[name.lower()] = first_row + offset
        sect["rep_rows"] = new_rep_rows
        summary[period] = {
            "sorted": len(sorted_block),
            "rep_block_rows": (first_row, last_row),
        }
    return summary


def hide_blanks_today(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> dict:
    """Hide every rep row whose TODAY % cell (col B) is blank after the
    fill; unhide every rep row whose today % has data. Names are NEVER
    deleted — they just become invisible until they get data again.
    Runs AFTER sort_sections_desc so the hidden block clusters at the
    bottom of each section visually.

    Returns {"hidden": [(period, row, name), …], "unhidden": [...]}.
    """
    actions: dict = {"hidden": [], "unhidden": []}
    batch_requests: list[dict] = []

    for period, sect in sections.items():
        rep_rows = sect["rep_rows"]
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        last_row = max(rep_rows.values())
        # One bulk read for the whole rep block of A:B (we only need col B today).
        rng = f"{ws.title}!A{first_row}:B{last_row}"
        block = ws.spreadsheet.values_get(rng).get("values", [])

        for offset, row_data in enumerate(block):
            sheet_row = first_row + offset
            name = (row_data[0] if row_data else "").strip()
            today_pct = (row_data[1] if len(row_data) > 1 else "").strip()
            if not name:
                continue
            if today_pct:
                actions["unhidden"].append((period, sheet_row, name))
            else:
                actions["hidden"].append((period, sheet_row, name))

    for action_key, hidden_flag in (("hidden", True), ("unhidden", False)):
        for _period, row, _name in actions[action_key]:
            batch_requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "ROWS",
                        "startIndex": row - 1,
                        "endIndex": row,
                    },
                    "properties": {"hiddenByUser": hidden_flag},
                    "fields": "hiddenByUser",
                }
            })

    if dry_run:
        logfn(f"  (dry-run) would hide {len(actions['hidden'])} rep row(s), "
              f"unhide {len(actions['unhidden'])}")
        return actions

    if batch_requests:
        ws.spreadsheet.batch_update({"requests": batch_requests})
    return actions


def clear_empty_cell_backgrounds(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> None:
    """Force WHITE background on every empty-value cell in each section's
    rep-row block (cols B onwards). Catches inherited bg from inserts
    (cols D+ of a freshly-inserted rep inherit format from the row above
    via insertDimension(inheritFromBefore=True)) plus any leftover bg
    from prior pulls whose values have since been cleared.

    Only touches cells with NO value — cells with data keep their
    existing background (which is set by apply_pct_direct_colors for col B
    and Eve's template/conditional rules for the rest).

    Megan 2026-05-29: 'formatting is weird under the sections' — empty
    rows below the last visible rep + empty cells on inserted reps were
    showing leftover red/green/yellow backgrounds. This cleans it.
    """
    if not sections:
        return

    # Determine read range per section: every row from the first rep
    # row down through the row before the next section's header (or
    # ws.row_count for the last section). Using min/max of rep_rows
    # leaves empty buffer rows between the last named rep and the
    # next section header out of the cleanup — those rows keep
    # whatever bg they inherited from prior pulls (Megan 2026-05-29:
    # red col J bleeding into rows 129-132 of Captainship 60-day).
    sorted_periods = sorted(sections.items(),
                            key=lambda kv: kv[1]["header_row"])
    section_end_rows: dict = {}
    for idx, (period, sect) in enumerate(sorted_periods):
        if idx + 1 < len(sorted_periods):
            section_end_rows[period] = (
                sorted_periods[idx + 1][1]["header_row"] - 1
            )
        else:
            section_end_rows[period] = ws.row_count

    requests: list[dict] = []
    cleared_count = 0

    for period, sect in sections.items():
        rep_rows = sect.get("rep_rows") or {}
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        last_row  = section_end_rows[period]
        # Read cols B..min(ws.col_count, 30) — past col 30 we're well into
        # historical weekly cols which are usually fine; capping keeps
        # the read fast.
        end_col_excl = min(ws.col_count, 30)
        if end_col_excl <= 1:
            continue
        end_col_letter = _col_letter(end_col_excl)   # exclusive
        # NB: NO {ws.title}! prefix — gspread.Worksheet.get_values
        # already qualifies the range with the worksheet title. Adding
        # it again double-prefixes (becomes 'Tab!Tab!B…:Z…') which
        # gspread can't parse — error gets swallowed by the bare except
        # below and every section silently no-ops. (Megan 2026-05-29:
        # the bg bleed bug that wouldn't go away.)
        rng = f"B{first_row}:{end_col_letter}{last_row}"
        try:
            values = ws.get_values(rng)
        except Exception:
            continue

        # For each row, find contiguous runs of empty cells (cols B+) and
        # batch one repeatCell white-bg request per run. Much fewer
        # requests than per-cell.
        for ri, row in enumerate(values):
            row_num = first_row + ri        # 1-indexed sheet row
            # Pad row to end_col_excl - 1 columns so trailing-empty cols
            # past the data still get checked.
            padded = list(row) + [""] * ((end_col_excl - 1) - len(row))
            start = None
            for ci, cell in enumerate(padded):
                is_empty = (cell or "").strip() == ""
                if is_empty:
                    if start is None:
                        start = ci
                else:
                    if start is not None:
                        run_len = ci - start
                        cleared_count += run_len
                        requests.append({
                            "repeatCell": {
                                "range": {
                                    "sheetId": ws.id,
                                    "startRowIndex": row_num - 1,
                                    "endRowIndex":   row_num,
                                    # ci offsets are within the B-onwards
                                    # window, so add +1 to land in
                                    # absolute col indices (B=1).
                                    "startColumnIndex": 1 + start,
                                    "endColumnIndex":   1 + ci,
                                },
                                "cell": {"userEnteredFormat": {
                                    "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                                }},
                                "fields": "userEnteredFormat.backgroundColor",
                            }
                        })
                        start = None
            if start is not None:
                run_len = (end_col_excl - 1) - start
                cleared_count += run_len
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": row_num - 1,
                            "endRowIndex":   row_num,
                            "startColumnIndex": 1 + start,
                            "endColumnIndex":   1 + (end_col_excl - 1),
                        },
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                        }},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                })

    if dry_run:
        logfn(f"  (dry-run) would clear bg on {cleared_count} empty cell(s) "
              f"across {len(sections)} sections ({len(requests)} requests)")
        return

    if not requests:
        return

    # Sheets batch_update accepts thousands of requests; we chunk at 1000
    # as a safe limit.
    for i in range(0, len(requests), 1000):
        ws.spreadsheet.batch_update({"requests": requests[i:i + 1000]})

    logfn(f"  cleared bg on {cleared_count} empty cell(s) "
          f"({len(requests)} ranges across {len(sections)} sections)")


_ZERO_PCT_LITERALS = {"0", "0.00", "0.0", "0%", "0.00%", "0.0%"}


def hide_after_5_zero_pulls(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> dict:
    """Hide rep rows whose 5 leftmost pct columns (B, D, F, H, J) are
    ALL explicit zero (0.00%, 0%, 0). Blank cells DO NOT count as zero —
    blank means 'no data that pull', so a row with mixed blanks + zeros
    is NOT hidden (it hasn't actually had 5 consecutive 0% pulls yet).

    Returns {'hidden': [row_nums]} for logging.

    Megan 2026-05-29: ICDs that show 0% across 5 consecutive pulls aren't
    actionable for the team — hide them so the visible roster is the
    set of ICDs currently churning.
    """
    actions = {"hidden": []}
    if not sections:
        return actions

    PCT_COL_OFFSETS = (0, 2, 4, 6, 8)   # B=0, D=2, F=4, H=6, J=8 in B-J window

    batch_requests: list[dict] = []

    for period, sect in sections.items():
        rep_rows = sect.get("rep_rows") or {}
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        last_row  = max(rep_rows.values())
        # Same gspread no-prefix rule as clear_empty_cell_backgrounds.
        rng = f"B{first_row}:J{last_row}"
        try:
            values = ws.get_values(rng)
        except Exception:
            continue

        for ri, row in enumerate(values):
            row_num = first_row + ri
            # Need at least 9 cols (B..J = 9 entries). Pad with "" so
            # missing trailing cells count as blank (rule: blank ≠ zero,
            # so a row with < 5 pulls of data won't trigger).
            padded = list(row) + [""] * (9 - len(row))
            pct_cells = [padded[i] for i in PCT_COL_OFFSETS]
            all_zero = all(
                (c or "").strip() in _ZERO_PCT_LITERALS
                for c in pct_cells
            )
            if all_zero:
                actions["hidden"].append(row_num)
                batch_requests.append({
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": ws.id,
                            "dimension": "ROWS",
                            "startIndex": row_num - 1,
                            "endIndex": row_num,
                        },
                        "properties": {"hiddenByUser": True},
                        "fields": "hiddenByUser",
                    }
                })

    if dry_run:
        logfn(f"  (dry-run) would hide {len(actions['hidden'])} rep row(s) "
              f"(5 consecutive 0% pulls)")
        return actions

    if batch_requests:
        ws.spreadsheet.batch_update({"requests": batch_requests})
        logfn(f"  hid {len(actions['hidden'])} rep row(s) "
              f"(5 consecutive 0% pulls)")
    else:
        logfn("  (no rep rows match 5-consecutive-0% rule)")
    return actions


def apply_rep_row_borders(
    ws,
    sections: dict,
    *,
    dry_run: bool = False,
    logfn=print,
) -> None:
    """Apply uniform Eve rep-row border pattern to every rep row in
    each section. The pattern (observed on Cyrus Wade row 90, a
    correctly-formatted reference row):

      Pair-start cols (B, D, F, ...):
        top + bottom = SOLID_MEDIUM
        left = SOLID_THICK    (the dark vertical line between date pairs)
        right = SOLID_MEDIUM  (the lighter line between % and units in
                               the same pair)
      Pair-end cols (C, E, G, ...):
        top + bottom = SOLID_MEDIUM
        left = SOLID_MEDIUM    (matches the right of the pair-start col)

    Required because sortRange physically moves rows + their borders —
    if a rep gets sorted into a row position that was previously an
    empty buffer row (no border), the borders disappear entirely on
    that row. This pass restores the canonical pattern for every rep
    row across all sections.

    Megan 2026-05-29: Sam Park row 91 (NEW INT 30) + FNU Stephen
    Sharon row 83 (Wireless 30) — both the last visible rep in their
    section — were missing borders. First attempt only applied
    top + bottom (which API confirmed but borders still didn't show
    because the THICK left/right pair-separator lines were absent).
    This version paints the full pattern.
    """
    if not sections:
        return
    MED = {"style": "SOLID_MEDIUM",
           "color": {"red": 0, "green": 0, "blue": 0}}
    THICK = {"style": "SOLID_THICK",
             "color": {"red": 0, "green": 0, "blue": 0}}
    end_col_excl = min(ws.col_count, 12)   # cover ~5 date pairs (B-K)

    requests: list[dict] = []
    for period, sect in sections.items():
        rep_rows = sect.get("rep_rows") or {}
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        last_row  = max(rep_rows.values())
        for col_idx in range(1, end_col_excl):
            # col_idx 1=B, 2=C, 3=D, 4=E, ...
            # Pair-start (B, D, F, ...) are odd; pair-end (C, E, G, ...)
            # are even.
            is_pair_start = (col_idx % 2 == 1)
            border_req: dict = {
                "updateBorders": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": first_row - 1,
                        "endRowIndex":   last_row,
                        "startColumnIndex": col_idx,
                        "endColumnIndex":   col_idx + 1,
                    },
                    "top": MED,
                    "bottom": MED,
                    "innerHorizontal": MED,
                    "left": THICK if is_pair_start else MED,
                }
            }
            if is_pair_start:
                border_req["updateBorders"]["right"] = MED
            requests.append(border_req)

    if dry_run:
        logfn(f"  (dry-run) would apply rep-row pair-border pattern "
              f"({len(requests)} requests across {len(sections)} sections)")
        return
    if requests:
        for i in range(0, len(requests), 500):
            ws.spreadsheet.batch_update({"requests": requests[i:i + 500]})
        logfn(f"  applied rep-row pair-border pattern "
              f"({len(requests)} requests, {len(sections)} sections)")


def _col_letter(idx: int) -> str:
    """Convert a 1-indexed column number (1=A, 2=B, …, 26=Z, 27=AA) into
    its A1 letter form."""
    letters = ""
    n = idx
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters



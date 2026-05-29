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


def insert_two_cols_at_b(ws, sections: Optional[dict] = None) -> None:
    """Insert 2 columns at position B+C (sheet-wide), then PASTE_NORMAL
    Eve's template formatting from the leftmost formatted col pair we
    can find. PASTE_NORMAL also brings over the merged-cell ranges,
    conditional formatting rules, and direct cell backgrounds — so the
    new B+C end up with Eve's exact template (orange section header,
    peach office avg, black rep header, white units, conditional %).

    Megan 2026-05-28: 'we should be copying formatting exactly on
    colors/bold/headers/lines'. PASTE_FORMAT didn't carry the merges or
    conditional rules; PASTE_NORMAL does. write_today then overwrites
    the duplicated values with our new today's data, so the visual
    end-state is Eve's template + our numbers.
    """
    last_row = ws.row_count
    paste_dst = {
        "sheetId": ws.id,
        "startRowIndex": 0,
        "endRowIndex": last_row,
        "startColumnIndex": 1,    # B
        "endColumnIndex": 3,      # through C
    }
    # Pass 1: insert the new B+C columns.
    ws.spreadsheet.batch_update({"requests": [{
        "insertDimension": {
            "range": {
                "sheetId": ws.id,
                "dimension": "COLUMNS",
                "startIndex": 1,    # col B (0-indexed)
                "endIndex": 3,
            },
            "inheritFromBefore": False,
        }
    }]})
    # Brief wait so the insert is fully committed server-side.
    time.sleep(1)
    # Pass 2: locate Eve's formatted template col pair and paste from
    # it. If prior --force-insert runs left unformatted duplicate cols
    # to the left of Eve's template, D+E may be one of THOSE — so we
    # scan past them to find the real template.
    # Use the 0-30 section's header row as the scan target (row 7 on
    # New Internet, row 1 on Wireless). Falls back to row 7 if no
    # sections supplied (legacy callers).
    scan_row = 7
    if sections:
        first_section = min(sections.values(), key=lambda s: s["header_row"])
        scan_row = first_section["header_row"]
    template_col = _find_formatted_template_col_after_insert(ws, scan_row)
    if template_col is None:
        # Fall back to D+E (which is the typical leftmost source for
        # a clean daily run where the previous day's fill IS Eve's
        # template). This is the happy path for production.
        template_col = 3   # col D (0-indexed)
    paste_src = {
        "sheetId": ws.id,
        "startRowIndex": 0,
        "endRowIndex": last_row,
        "startColumnIndex": template_col,
        "endColumnIndex": template_col + 2,
    }
    ws.spreadsheet.batch_update({"requests": [
        {"copyPaste": {"source": paste_src, "destination": paste_dst,
                       "pasteType": "PASTE_NORMAL"}},
    ]})
    # Wait for the paste to fully commit server-side before the next
    # values_batch_update fires. Megan's New Internet tab (~1200 rows ×
    # 380+ cols) had a write race where writes processed before the
    # insert+paste finished — writes landed on the OLD col B (which
    # became D after the insert settled), leaving the new B+C empty.
    # Wireless (~750 rows) was fast enough that the race didn't fire.
    # A short sync wait closes the window.
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



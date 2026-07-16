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
import os
import re
import time
from typing import Optional

from automations.new_internet_churn import pull
from automations.recruiting_report.fill import open_by_key, _retry

SHEET_ID = os.environ.get("CHURN_SHEET_ID", "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8")
TAB_LOCAL_OFFICE = "Local Office - New Internet Churn"

PERIOD_SECTION_LABELS = (
    # canonical period → marker substring (uppercase, whitespace-normalized)
    ("0-30", "0-30 DAYS"),
    ("30",   "30 DAYS"),
    ("60",   "60 DAYS"),
    ("90",   "90 DAYS"),
    ("120",  "120 DAYS"),   # B2B (Carlos / Eveliz) has a 5th 120-day bucket
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


def _has_pct(slot: Optional[dict]) -> bool:
    """True if `slot` carries ANY churn % value — including an explicit
    0%. Megan 2026-06-04 visibility rule: 0% is DATA (show the rep);
    only a missing/blank pct means 'no entry this bucket'."""
    if not slot:
        return False
    return bool((slot.get("pct") or "").strip())


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
    grid = _retry(ws.get_all_values)
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

        # Locate the avg row + rep-header row by their col-A LABELS, not by
        # assuming the fixed header+1 / header+2 offsets. A mid-cycle manual
        # row delete (e.g. Megan clearing duplicate rows) shifts the section
        # structure; the old positional offsets then pointed office_avg_row /
        # rep_header_row at REAL rep rows, and write_today clobbered them with
        # 'pct'/'units'/office data while the rep silently dropped out of the
        # roster. That was the 2026-05-29 Khalil 90-day corruption. Labels
        # survive row drift; offsets don't.
        #
        # avg row label is 'Office Avg' (Local Office tabs) or 'Captainship
        # Avg' (Captainship tabs) — both contain 'AVG'. rep-header is 'Rep'.
        office_avg_row = None
        rep_header_row = None
        for r in range(header_row + 1, end_row + 1):
            if r > n_rows:
                break
            norm = _norm(col_a[r - 1])
            if norm == "REP":
                rep_header_row = r
                break   # the rep-data block starts on the next row
            if office_avg_row is None and "AVG" in norm:
                office_avg_row = r
        # Fallback to the canonical offsets if a tab doesn't carry the labels
        # (keeps any non-conforming tab working exactly as before). On the
        # intact layout this is a no-op — AVG is at +1 and 'Rep' at +2.
        if rep_header_row is None:
            rep_header_row = header_row + 2
        if office_avg_row is None:
            office_avg_row = header_row + 1

        rep_rows: dict[str, int] = {}
        for r in range(rep_header_row + 1, end_row + 1):
            if r > n_rows:
                break
            name = col_a[r - 1].strip()
            if not name:
                continue
            # Belt + braces: never let a structural header row leak into the
            # rep-data map even if labels/offsets ever disagree.
            norm = _norm(name)
            if norm == "REP" or "AVG" in norm:
                continue
            rep_rows[name.lower()] = r
        sections[period] = {
            "header_row": header_row,
            "office_avg_row": office_avg_row,
            "rep_header_row": rep_header_row,
            "rep_rows": rep_rows,
        }
    return sections


def recent_active(values: list, row: int,
                  cols: tuple = (2, 4, 6, 8, 10, 12)) -> bool:
    """True if a rep row has ANY non-empty pct in the last ~6 day columns
    (B/D/F/H/J/L, read BEFORE today's column is inserted) — i.e. it was being
    filled until recently. Distinguishes a rep who just dropped off the pull
    (real 'went dark') from a long-stale roster leftover (blank for weeks)."""
    for c in cols:
        if len(values) >= row and len(values[row - 1]) >= c \
                and values[row - 1][c - 1].strip():
            return True
    return False


def detect_went_dark(values: list, sections: dict, parsed: dict) -> dict:
    """Roster reps ABSENT from today's pull for a tier they were RECENTLY ACTIVE
    in — the Eveliz-Roca failure: a rep dropped from a Tableau view's filter (or
    renamed past the alias) makes the pull 'succeed' minus her, so her row
    silently stops filling and the run still reads green. Returns
    {period: [display_name, ...]} (empty = clean).

    Read `values` (ws.get_all_values()) BEFORE today's column is inserted, so the
    recent-history columns + `sections['rep_rows']` indices are still valid.

    Presence is judged against the WHOLE pull, not per-bucket: a rep in today's
    pull with a pct in ANY period is present — an empty 0-30/30/60 bucket while
    her 90-day fills is a normal data gap (no activations that bucket), NOT a
    disappearance (Cordell Jones 2026-07-06). Only a rep absent from every
    bucket — dropped from the view's filter or renamed past the alias — is dark.

    A rep on the shared Terminated-ICDs list is NEVER dark: she's expected to
    drop out of the pull once she's let go (Selena Powers 2026-07-06). Flagging
    her as dark would block the run's retry and hold the Hub card red forever.
    Her stale row is surfaced separately (advisory) by the report's
    ti.alert_terminated() hook, not here."""
    reps = parsed.get("reps", {})
    present_lc = {nm.lower() for nm, pd in reps.items()
                  if isinstance(pd, dict)
                  and any(isinstance(v, dict) and v.get("pct")
                          for v in pd.values())}
    # Cross-reference the Terminated-ICDs list (single cached Sheet read for the
    # whole run) so a terminated rep's expected disappearance never reads as a
    # broken filter. Import lazily — terminated_icds pulls in gspread, which a
    # dry-run/offline unit test of this module shouldn't require.
    try:
        from automations.shared import terminated_icds as _ti
        _is_terminated = _ti.terminated_lookup()
    except Exception:  # noqa: BLE001 — advisory cross-check must never break fill
        _is_terminated = lambda _n: False
    out: dict = {}
    for period, sect in sections.items():
        dark = []
        for name_lc, row in sect["rep_rows"].items():
            if name_lc in present_lc:
                continue
            disp = (values[row - 1][0].strip()
                    if len(values) >= row and values[row - 1] else name_lc)
            if _is_terminated(disp):
                continue
            if recent_active(values, row):
                dark.append(disp)
        if dark:
            out[period] = sorted(set(dark))
    return out


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
        # Auto-insert any rep with a pct for THIS period — INCLUDING an
        # explicit 0% (Megan 2026-06-04 reversal of the 2026-05-28 skip
        # rule: "show everyone with a percentage, 0% included; hide only
        # reps with no percentage at all"). Reps with no pct this period
        # still don't get a row here — hide_blanks_today keeps them out.
        missing = [m for m in missing if _has_pct(reps[m].get(period))]
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
    # Let the row inserts commit server-side before writing names into
    # the new rows (mirrors the wait in insert_two_cols_at_b).
    time.sleep(1)

    # FINAL position of each request's inserted block: its original
    # anchor shifted DOWN by the deltas of every insert that happened
    # ABOVE it (lower anchor). The batch above applies bottom-up, so
    # each request's startIndex was correct AT APPLY TIME — but once
    # the whole batch lands, every lower section has moved down by the
    # upper sections' insert counts. Writing names at the ORIGINAL
    # anchors sprayed them N rows too high, onto OTHER reps' rows
    # (this was the 2026-05-29 'Khalil 90-day corruption', re-triggered
    # at scale on 2026-06-04 by the Local Office 0% inserts).
    def _shift_above(req) -> int:
        return sum(len(r["_names"]) for r in insert_requests
                   if r["_anchor"] < req["_anchor"])

    # Write the rep names into col A of the freshly-inserted rows,
    # at their FINAL (post-batch) positions.
    name_cells: list[dict] = []
    for req in insert_requests:
        base = req["_anchor"] + _shift_above(req)
        for i, name in enumerate(req["_names"]):
            name_cells.append({
                "range": f"{ws.title}!A{base + 1 + i}",
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
    # Add the freshly-inserted reps to their section's rep_rows map at
    # the same FINAL positions the names were written to.
    for req in insert_requests:
        base = req["_anchor"] + _shift_above(req)
        p = req["_period"]
        for i, name in enumerate(req["_names"]):
            sections[p]["rep_rows"][name.lower()] = base + 1 + i
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
    base = _CHURN_TIERS_PRESERVE_ROWS if "CHURN TIERS" in a1 else 0
    # Advance past any fully-empty spacer row(s) right after the preserved block.
    # Such a row can hold a wide B..G merge (a visual separator) that the B-C
    # column insert would only PARTIALLY intersect — which Sheets rejects with
    # "partially intersects a merge". Starting the insert at the first real
    # section row keeps that merge out of the insert range (Eve glitch
    # 2026-06-03).
    try:
        nxt = ws.get(f"A{base + 1}:H{base + 8}")
    except Exception:
        return base
    extra = 0
    for r in nxt:
        if any((c or "").strip() for c in r):
            break
        extra += 1
    return base + extra


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
    # Preserve EVERYTHING above the first section's date-header row, not
    # just the CHURN TIERS block. On Captainship/Owners tabs there's a
    # merged divider band on the row right below CHURN TIERS (e.g. row 4:
    # a B:G merge, plus the CHURN TIERS H:Q block spans down into it).
    # _detect_preserve_top_rows returns 3 (CHURN TIERS rows 1-3), which
    # left that row inside the insert band — the B:C insertRange split
    # the B:G merge and tore the H:Q block across the preserve boundary,
    # so Sheets rejected the request with APIError 400 (Eve 2026-06-03).
    # The first section header is found by label (find_sections), never
    # hardcoded, so this tracks template drift.
    if sections:
        preserve_top_rows = min(s["header_row"] for s in sections.values()) - 1
    else:
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

        # 3. Per-rep rows. Reps with data for THIS period (an explicit
        # 0% counts as data) get today's pct + units. Every OTHER roster
        # row gets B+C explicitly CLEARED — required because
        # insert_two_cols_at_b copies D+E onto the new B+C with
        # PASTE_NORMAL, which brings YESTERDAY'S VALUES along with the
        # formatting. Without the clear, a rep who dropped out of
        # Tableau's window still shows yesterday's number under today's
        # date label, and hide_blanks_today can't hide them (B isn't
        # blank). Megan 2026-06-04: Tomas Meza's stale 25% in the 60-day
        # bucket / Van's frozen 0% in the 90-day bucket.
        sect_summary = {"filled": 0, "cleared": 0, "unmatched": []}
        rep_rows = sect["rep_rows"]
        filled_rows: set = set()
        for rep_name, rep_periods in reps.items():
            pdata = rep_periods.get(period)
            if not pdata or not pdata.get("pct"):
                continue   # no pct this period → row cleared below
            row = rep_rows.get(rep_name.lower())
            if row is None:
                # Has a pct but no roster row. insert_missing_reps now
                # runs every run (incl. refresh) and inserts 0% reps
                # too, so this is genuinely exceptional — flag it.
                if _has_pct(pdata):
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
            filled_rows.add(row)
            sect_summary["filled"] += 1
        # 3b. Clear B+C on roster rows with NO data this period. A
        # legitimate 0% never lands here — it was written above
        # (pct '0.00%' is a non-empty string → filled).
        for row in rep_rows.values():
            if row in filled_rows:
                continue
            raw_cells.append({
                "range": f"{ws.title}!B{row}:C{row}",
                "values": [["", ""]],
            })
            sect_summary["cleared"] += 1
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
    "120":  (5.0, 8.0),   # B2B 120-day — same band as 30/60/90 until Megan corrects
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
    # A pct cell's row must fall inside the live grid. A reset / freshly
    # reconciling tab can momentarily hand find_sections a phantom rep row
    # past the grid edge (Wireless, Cyrus 7/15: a rep mapped to row 143 in a
    # 124-row grid). Sheets rejects the ENTIRE repeatCell batch on one
    # out-of-bounds range — voiding every color in it and leaving the whole
    # tab uncolored. Drop the out-of-range cell instead so the real reps
    # still get painted.
    max_row = ws.row_count

    def _in_grid(row: int) -> bool:
        if 1 <= row <= max_row:
            return True
        logfn(f"  color: skipping out-of-grid row {row} (grid {max_row})")
        return False

    for period, sect in sections.items():
        rep_rows = sect["rep_rows"]
        # Office Avg row.
        odata = office_total.get(period, {})
        bg = _pct_color_for(period, odata.get("pct", ""))
        if bg is not None and _in_grid(sect["office_avg_row"]):
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
            if not _in_grid(row):
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
        # A reset / freshly-set-up tab can leave a section's detected rep
        # rows BELOW the next section's header (stray blank rows read as
        # reps), making first_row-1 >= last_row. Sheets rejects an
        # inverted/empty ROWS range and the WHOLE batch fails — which
        # kills the tier-coloring step that runs right after, leaving the
        # tab stuck all-orange (Megan 2026-07-15, Cyrus fresh-office run;
        # same all-orange symptom the 2026-07-11 re-find guarded against,
        # but a mis-detected stray row slips past re-find). Skip the bad
        # range rather than crash — there is nothing to unhide on a fresh
        # tab anyway, and the colors then apply cleanly.
        if first_row - 1 >= last_row:
            logfn(f"  unhide: skipping inverted/empty row range "
                  f"[{first_row - 1}..{last_row}) (reset/fresh tab); "
                  f"colors still apply")
            continue
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
        # Use the STRUCTURAL boundary (rep_header_row + 1) as the floor, not
        # just the data-content boundary. min(rep_rows) is the topmost rep;
        # clamping it to never rise above rep_header_row+1 guarantees the sort
        # range can't swallow the office-avg / rep-header rows even if rep_rows
        # is ever stale. Belt-and-braces for the Khalil 90-day corruption.
        first_row = max(min(rep_rows.values()), sect["rep_header_row"] + 1)
        if idx + 1 < len(sorted_periods):
            last_row = sorted_periods[idx + 1][1]["header_row"] - 1
        else:
            last_row = max(rep_rows.values())
        # Clamp to the grid: a freshly cleared tab whose template headers
        # outrun a smaller inserted roster can make next_header-1 exceed the
        # grid, and sortRange would reject the whole batch (same fresh-office
        # class as the unhide / color / clear-backgrounds guards).
        last_row = min(last_row, ws.row_count)
        if last_row < first_row:
            continue
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
        first_row = max(min(rep_rows.values()), sect["rep_header_row"] + 1)
        last_row  = max(rep_rows.values())
        col_a = _retry(ws.range, f"A{first_row}:A{last_row}")
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
        # Clamp to the grid + skip empty/degenerate sections. On a small sheet
        # (young office — e.g. Rashad's 44-row churn tab) a section can land at
        # the last grid row, producing an out-of-grid / backwards range like
        # C45:C44 that gspread rejects ("exceeds grid limits"). The unhide/sort
        # passes already skip empty sections; this col-C range pass must too.
        last_row = min(last_row, ws.row_count)
        if first_row >= last_row:
            continue
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

    # If every section was empty/degenerate, `ranges` is empty — still run the
    # deletes (idempotency) but skip the add so we never send an empty-ranges rule.
    reqs = delete_requests + ([add_request] if ranges else [])
    if reqs:
        ws.spreadsheet.batch_update({"requests": reqs})


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
        # Structural floor — see sort_sections_via_sortrange. Never let the
        # sorted block start above the rep-header row.
        first_row = max(min(rep_rows.values()), sect["rep_header_row"] + 1)
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


def ungroup_all_rep_rows(ws, *, dry_run: bool = False, logfn=print) -> None:
    """Delete every existing ROW group on the tab. Run BEFORE re-sorting +
    re-grouping (mirrors unhide_all_rep_rows) so a rep that was collapsed
    yesterday but has data today isn't stuck inside a stale collapsed group."""
    meta = ws.spreadsheet.fetch_sheet_metadata(
        params={"fields": "sheets(properties(sheetId),rowGroups)"})
    groups = []
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] == ws.id:
            groups = s.get("rowGroups", []) or []
            break
    if not groups:
        return
    if dry_run:
        logfn(f"  (dry-run) would delete {len(groups)} existing row group(s)")
        return
    reqs = [{"deleteDimensionGroup": {"range": g["range"]}} for g in groups]
    ws.spreadsheet.batch_update({"requests": reqs})


def group_collapse_nodata_reps(ws, sections, *, dry_run: bool = False,
                               logfn=print) -> None:
    """REPLACES plain hiding (Megan 2026-06-28): after sort_sections_via_sortrange
    clusters blank-today reps at the TOP of each section, relocate that no-data
    block to the BOTTOM of the section and wrap it in a COLLAPSED Sheets row group
    (the +/- toggle). Reps with data stay visible + % desc; no-data reps collapse
    out of the way. Names never deleted. Sections processed BOTTOM-UP so row moves
    don't shift not-yet-processed sections.

    'No-data' here = blank today (col B), matching hide_blanks_today. (5-zero reps
    carry a 0% value so they already sort to the bottom of the DATA block; widen
    the classification below if they should also collapse.)

    ⚠ UNTESTED from a dev laptop — the moveDimension index math is verified only
    for the all-blank case (Rashad's empty template). MUST be dry-run on the mini
    against real mixed churn data before it touches Raf's live run.
    """
    if not sections:
        return
    for period, sect in sorted(sections.items(),
                               key=lambda kv: kv[1]["header_row"], reverse=True):
        rep_rows = sect.get("rep_rows") or {}
        if not rep_rows:
            continue
        first = max(min(rep_rows.values()), sect["rep_header_row"] + 1)
        last = max(rep_rows.values())
        block = ws.spreadsheet.values_get(
            f"{ws.title}!A{first}:B{last}").get("values", [])
        n = 0  # contiguous blank-today reps at the top (post desc-sort)
        for rd in block:
            name = (rd[0] if rd else "").strip()
            today = (rd[1] if len(rd) > 1 else "").strip()
            if name and not today:
                n += 1
            else:
                break
        if n == 0:
            continue
        if dry_run:
            logfn(f"  (dry-run) {period}: move+group+collapse {n} no-data reps")
            continue
        reqs = []
        if n < (last - first + 1):   # data reps below → move blanks to the bottom
            reqs.append({"moveDimension": {
                "source": {"sheetId": ws.id, "dimension": "ROWS",
                           "startIndex": first - 1, "endIndex": first - 1 + n},
                "destinationIndex": last}})
        g0, g1 = last - n, last   # 0-indexed bottom block after the move
        reqs.append({"addDimensionGroup": {"range": {
            "sheetId": ws.id, "dimension": "ROWS",
            "startIndex": g0, "endIndex": g1}}})
        reqs.append({"updateDimensionGroup": {"dimensionGroup": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": g0, "endIndex": g1},
            "depth": 1, "collapsed": True}, "fields": "collapsed"}})
        ws.spreadsheet.batch_update({"requests": reqs})
        logfn(f"  {period}: moved+grouped+collapsed {n} no-data reps at bottom")


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
            # Last section — cap at last named rep + 50-row buffer
            # so we cover bleed-prone empty rows below the section
            # without scanning the whole sheet (some tabs have 700+
            # rows; reading + emitting a clear request per empty row
            # would burn API quota for no visual gain).
            rep_rows = sect.get("rep_rows") or {}
            last_named = max(rep_rows.values()) if rep_rows else sect["header_row"]
            section_end_rows[period] = min(ws.row_count, last_named + 50)

    requests: list[dict] = []
    cleared_count = 0

    for period, sect in sections.items():
        rep_rows = sect.get("rep_rows") or {}
        if not rep_rows:
            continue
        first_row = min(rep_rows.values())
        last_row  = section_end_rows[period]
        # Clamp to the live grid. A middle section's end is the NEXT
        # section's header-1, computed from find_sections; on a freshly
        # cleared tab whose template headers outrun a smaller inserted
        # roster, that can land past the grid edge, and the pad-to-
        # expected-rows loop below would then emit a white-bg repeatCell
        # for a nonexistent row — Sheets rejects the WHOLE batch, killing
        # the cleanup (Wireless, Hammad 7/15: D88:AD88 in an 87-row grid).
        last_row = min(last_row, ws.row_count)
        if last_row < first_row:
            continue
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
            # FORMULA render option — returns underlying cell content
            # (formula text or literal value) without Sheets' default
            # number-format coercion. Distinguishes between a genuinely
            # empty cell (returns '') and a legitimate 0 (returns 0).
            # UNFORMATTED_VALUE returns 0 for both because Sheets reads
            # null + '0.00%' format → 0. FORMATTED_VALUE returns
            # '0.00%' literal which my code can't distinguish from a
            # written 0%.
            values = _retry(ws.get, rng, value_render_option="FORMULA")
        except Exception:
            continue

        # gspread.get_values truncates trailing empty rows — so empty
        # buffer rows between the last named rep and the next section
        # header (or the very bottom of a section for the last
        # section) are dropped from `values` and never processed.
        # Pad up to the requested row count so those rows get cleared.
        expected_rows = last_row - first_row + 1
        while len(values) < expected_rows:
            values.append([])

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
                # UNFORMATTED_VALUE returns numbers as numbers; only
                # None / "" / whitespace-only strings count as empty.
                is_empty = (
                    cell is None
                    or (isinstance(cell, str) and cell.strip() == "")
                )
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
        # UNFORMATTED_VALUE so number cells come back as numbers
        # (a real 0% pct returns 0.0, not the formatted string '0.00%')
        # and empty cells come back as '' regardless of number format
        # (a cell with '0.00%' number format applied to a null value
        # would otherwise look like a real zero in formatted output).
        rng = f"B{first_row}:J{last_row}"
        try:
            values = _retry(ws.get, rng, value_render_option="UNFORMATTED_VALUE")
        except Exception:
            continue

        for ri, row in enumerate(values):
            row_num = first_row + ri
            # Need at least 9 cols (B..J = 9 entries). Pad with "" so
            # missing trailing cells count as blank (rule: blank ≠ zero,
            # so a row with < 5 pulls of data won't trigger).
            padded = list(row) + [""] * (9 - len(row))
            pct_cells = [padded[i] for i in PCT_COL_OFFSETS]

            def _is_zero(c):
                if c == 0 or c == 0.0:
                    return True
                if isinstance(c, str) and c.strip() in _ZERO_PCT_LITERALS:
                    return True
                return False
            all_zero = all(_is_zero(c) for c in pct_cells)
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



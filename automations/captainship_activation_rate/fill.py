"""Destination-tab helpers for the Captainship Activation Rate fills.

Layout differs from the churn tabs in ONE structural way, which is why this
module exists instead of re-exporting `new_internet_churn.fill` wholesale:
each day is a SINGLE column (just the %), not a B+C pair (% + units). So the
column insert, the header merge and the writer are local; the row-level
operations (finding a box's rows, appending a missing rep) are identical and
are re-used from the shared module.

Per tab:

    A1  WAYNE RUDE                       <- owner name, never touched
    A2  ACTIVATION 0-30 DAYS      B2 date (real date, 'ddd m/d/yy')
    A3  Captainship Avg           B3 %   (PERCENT 0.00%)
    A4  Rep                       B4 '%'
    A5.. rep names                B5.. % (PERCENT 0.00%)
    ... blank spacer rows ...
    A15 ACTIVATION  RATE 30-60 DAYS  <- note the DOUBLE space; matched on
                                        'ACTIVATION' + '30-60 DAYS', never
                                        on the literal string
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Optional

from automations.new_internet_churn import fill as _shared

# "Captainship Metrics Report - Cancel/Activation Rate and ABP" workbook.
SHEET_ID = "1P95BxzlmLKkuvcL0gqjD9EfEHPLniGN-m4eE9UsPe_E"

# Report slug -> tab name. These tabs use the captains' SHORT names
# ('Starr', 'Chan'), unlike the Owners Metrics churn tabs which spell them out
# ('Starr Rodenhurst', 'Chan Park') — don't assume one from the other.
TABS = {
    "wayne": "Activation Rate - Wayne (ATT Fiber)",
    "starr": "Activation Rate - Starr (ATT Fiber)",
    "chan":  "Activation Rate - Chan (ATT Fiber)",
    "tony":  "Activation Rate - Tony (ATT Fiber)",
    "sahil": "Activation Rate - Sahil (ATT Fiber)",
}

# Box key -> marker substring in col A (uppercase, whitespace-normalized).
# '0-30 DAYS' is checked first so the '30-60 DAYS' probe can't eat it.
BOX_LABELS = (
    ("0-30",  "0-30 DAYS"),
    ("30-60", "30-60 DAYS"),
)

_norm = _shared._norm
_has_pct = _shared._has_pct
_date_label = _shared._date_label
# Row-level ops are column-layout agnostic — reuse them rather than fork.
insert_missing_reps = _shared.insert_missing_reps


def open_ws(slug: str):
    return _shared.open_by_key(SHEET_ID).worksheet(TABS[slug])


def find_boxes(ws) -> dict:
    """Locate each activation box by its col-A label. Returns the same dict
    shape the churn fills use — {box: {header_row, office_avg_row,
    rep_header_row, rep_rows}} — so the shared row helpers accept it unchanged.

    Everything is found by LABEL, never by row number: the two boxes sit at
    rows 2 and 15 today, but a rep insert moves the second one down.
    """
    grid = _shared._retry(ws.get_all_values)
    col_a = [(r[0] if r else "") for r in grid]
    n_rows = len(col_a)

    found: dict = {}
    for i, label in enumerate(col_a):
        norm = _norm(label)
        if "ACTIVATION" not in norm or "DAY" not in norm:
            continue
        for box, marker in BOX_LABELS:
            if box in found or marker not in norm:
                continue
            found[box] = i + 1          # 1-indexed sheet row
            break

    boxes: dict = {}
    ordered = sorted(found.items(), key=lambda kv: kv[1])
    for idx, (box, header_row) in enumerate(ordered):
        end_row = (ordered[idx + 1][1] - 1
                   if idx + 1 < len(ordered) else n_rows)

        # Avg row ('Captainship Avg') and rep-header row ('Rep') by LABEL —
        # a manual row insert breaks the +1/+2 offsets, and the churn tabs
        # taught us what that costs (write_today clobbering a real rep row).
        office_avg_row = None
        rep_header_row = None
        for r in range(header_row + 1, min(end_row, n_rows) + 1):
            norm = _norm(col_a[r - 1])
            if norm == "REP":
                rep_header_row = r
                break
            if office_avg_row is None and "AVG" in norm:
                office_avg_row = r
        if rep_header_row is None:
            rep_header_row = header_row + 2
        if office_avg_row is None:
            office_avg_row = header_row + 1

        rep_rows: dict = {}
        for r in range(rep_header_row + 1, min(end_row, n_rows) + 1):
            name = col_a[r - 1].strip()
            if not name:
                continue
            norm = _norm(name)
            if norm == "REP" or "AVG" in norm:
                continue
            rep_rows[name.lower()] = r
        boxes[box] = {
            "header_row": header_row,
            "office_avg_row": office_avg_row,
            "rep_header_row": rep_header_row,
            "rep_rows": rep_rows,
        }
    return boxes


def today_already_filled(ws, boxes: dict, today: dt.date) -> bool:
    """True if col B of any box header already shows today's date — a previous
    run (or Eve's manual setup) already opened today's column, so inserting
    another one would leave a blank duplicate."""
    want = _date_label(today)
    grid = _shared._retry(ws.get_all_values)
    for sect in boxes.values():
        r = sect["header_row"]
        if len(grid) >= r and len(grid[r - 1]) >= 2:
            if (grid[r - 1][1] or "").strip() == want:
                return True
    return False


def ensure_headroom(ws, *, dry_run: bool = False, logfn=print) -> None:
    """Guarantee at least 2 spare columns before shifting everything right.

    These tabs start 4 columns wide. `insertRange` shifts cells right WITHIN
    the sheet's existing width, so without headroom the right-most day would
    fall off the edge and be silently lost.
    """
    if ws.col_count - _last_used_col(ws) >= 2:
        return
    if dry_run:
        logfn("  (dry-run) would widen the tab by 12 columns for headroom")
        return
    ws.add_cols(12)
    logfn(f"  widened tab to {ws.col_count} columns (insert headroom)")


def _last_used_col(ws) -> int:
    grid = _shared._retry(ws.get_all_values)
    return max((len(r) for r in grid), default=0)


def insert_one_col_at_b(ws, boxes: dict, *, dry_run: bool = False,
                        logfn=print) -> None:
    """Open today's column: insert ONE blank column at B across the box rows,
    then copy yesterday's formatting (now at C) onto it.

    Rows above the first box header (the owner-name row) are left alone —
    insertRange with shiftDimension=COLUMNS respects the row bounds, so the
    title row never drifts right the way a whole-column insert would.
    """
    if dry_run:
        logfn("  (dry-run) would insert 1 column at B + copy yesterday's format")
        return
    preserve_top_rows = min(s["header_row"] for s in boxes.values()) - 1
    last_row = ws.row_count

    ws.spreadsheet.batch_update({"requests": [{
        "insertRange": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": preserve_top_rows,   # 0-indexed inclusive
                "endRowIndex": last_row,              # exclusive
                "startColumnIndex": 1,                # B
                "endColumnIndex": 2,                  # C exclusive
            },
            "shiftDimension": "COLUMNS",
        }
    }]})
    time.sleep(1)

    # Paste yesterday's column (now C) onto the new B so the date/percent
    # number formats and the header's orange band carry over. PASTE_NORMAL
    # brings values along too — write_today overwrites every cell it owns and
    # blanks the rest, so no stale number survives.
    ws.spreadsheet.batch_update({"requests": [{
        "copyPaste": {
            "source": {
                "sheetId": ws.id,
                "startRowIndex": preserve_top_rows, "endRowIndex": last_row,
                "startColumnIndex": 2, "endColumnIndex": 3,     # C
            },
            "destination": {
                "sheetId": ws.id,
                "startRowIndex": preserve_top_rows, "endRowIndex": last_row,
                "startColumnIndex": 1, "endColumnIndex": 2,     # B
            },
            "pasteType": "PASTE_NORMAL",
        }
    }]})
    # Let the paste commit before values_batch_update fires, or writes can
    # land on the OLD col B (which is C once the insert settles).
    time.sleep(3)


def write_today(ws, boxes: dict, today: dt.date, parsed: dict, *,
                dry_run: bool = False, logfn=print) -> dict:
    """Write today's column B for both boxes. Returns
    {box: {"filled": n, "cleared": n, "unmatched": [names]}}.

    Cell semantics:
      * B<header_row> — the DATE. Written as an ISO date via USER_ENTERED, not
        as the text 'Tue 7/28/26': these cells carry a real DATE number format
        ('ddd m/d/yy') and a string would sit in them as text and break the
        format. The tab renders the weekday itself.
      * B<avg/rep rows> — the % as Tableau printed it ('80.5%'). USER_ENTERED
        parses that to 0.805 for the PERCENT-formatted cell.
      * Every roster row with NO value today is explicitly BLANKED — the
        copyPaste in insert_one_col_at_b brings yesterday's numbers across, and
        without the clear a rep who dropped out of the view would show stale
        data under today's date.
    """
    office = parsed.get("office_total", {})
    reps = parsed.get("reps", {})
    cells: list = []
    summary: dict = {}

    for box, sect in boxes.items():
        cells.append({"range": f"{ws.title}!B{sect['header_row']}",
                      "values": [[today.isoformat()]]})
        cells.append({"range": f"{ws.title}!B{sect['rep_header_row']}",
                      "values": [["%"]]})
        cells.append({"range": f"{ws.title}!B{sect['office_avg_row']}",
                      "values": [[office.get(box, {}).get("pct", "")]]})

        s = {"filled": 0, "cleared": 0, "unmatched": []}
        rep_rows = sect["rep_rows"]
        filled_rows: set = set()
        for name, per_box in reps.items():
            pdata = per_box.get(box)
            if not _has_pct(pdata):
                continue
            row = rep_rows.get(name.lower())
            if row is None:
                s["unmatched"].append(name)
                continue
            cells.append({"range": f"{ws.title}!B{row}",
                          "values": [[pdata["pct"]]]})
            filled_rows.add(row)
            s["filled"] += 1
        for row in rep_rows.values():
            if row in filled_rows:
                continue
            cells.append({"range": f"{ws.title}!B{row}", "values": [[""]]})
            s["cleared"] += 1
        summary[box] = s

    if dry_run:
        logfn(f"  (dry-run) would write {len(cells)} cells")
        return summary

    ws.spreadsheet.values_batch_update({
        "valueInputOption": "USER_ENTERED",
        "data": cells,
    })
    return summary

"""Give a new owner a row on the Org Sales Board — in BOTH places that count.

A campaign on the board is two blocks, and a person who is only in one of them
is worse than absent: they'd show days with no week, or a week with no days.

  1. the WEEKLY leaderboard (rows 26-86 on the copy tab) — col-A campaign label,
     rank in A, name in B, C a name-keyed =SUMIF over the daily block, D.. the
     frozen week-ending history, then a 'TOTALS' row.
  2. the DAILY breakdown (rows 89+) — the same col-A label plus a 'RUNNING WEEK
     TOTALS' header, rank in A, name in B, Mon-Sun in C..I, J a =SUM of those,
     K/L last-week/prior-week history, M the Org Head.

WHERE THE ROW GOES: immediately BEFORE the block's last row, never after it.
That is not cosmetic. Every range that matters — the daily 'Totals' =SUM, the
leaderboard's =SUMIF, its 'TOTALS' =SUM, and the ALL TOTALS row that adds each
block's total — ends exactly at the last data row, and Google only auto-expands
a range when the insert lands INSIDE it. Appending after the last row would give
the new person a row whose numbers no total ever sees: the board would read low
and look perfect. (One-row blocks like Frontier can't have an interior insert at
all, so `repair_ranges` rewrites those ranges afterwards; it runs every time and
is a no-op when Google already did the right thing.)

FROZEN HISTORY IS NEVER COPIED — the leaderboard's D.. and the daily K/L are
left blank. Inheriting the neighbour's weeks would invent sales that never
happened, and those columns feed the vs-prior-week boxes.

Rank (col A) is written as the next number in the block and left at that: the
daily run's `sort.apply_sort` re-ranks every block by production right after the
fill, and someone who just started belongs wherever their numbers put them.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

from automations.recruiting_report.fill import _retry
from automations.org_sales_board import fill_section as fs

CAPTAIN_BLOCK_RE = re.compile(r"\bcaptain(?:ship)?\s+team\b", re.I)
TOTALS_LABELS = {"totals", "total", "all totals"}


def _cell(grid: List[List[str]], r1: int, c1: int) -> str:
    r0, c0 = r1 - 1, c1 - 1
    if 0 <= r0 < len(grid) and 0 <= c0 < len(grid[r0]):
        return (grid[r0][c0] or "").strip()
    return ""


def _a1(c: int) -> str:
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def captainship_boundary(grid: List[List[str]]) -> int:
    """1-indexed row where the captainship half of the board starts.

    Everything above it is org-wide campaign blocks; below, every block belongs
    to a captain. Found by the col-B '<NAME> CAPTAIN(SHIP) TEAM' marker — the
    same wording `captainship.discover_captainships` matches — so the split
    follows the board instead of a row number."""
    for i in range(len(grid)):
        if CAPTAIN_BLOCK_RE.search(_cell(grid, i + 1, 2)):
            return i + 1
    return len(grid) + 1


def campaign_labels(grid: List[List[str]]) -> List[str]:
    """The board's campaign section labels, top to bottom, read off the board.

    A daily section header (col A + a 'RUNNING WEEK TOTALS' column) above the
    captainship boundary. These are exactly the values the bank's Campaign
    dropdown offers, so the list can never drift from the board."""
    stop = captainship_boundary(grid)
    out: List[str] = []
    for i in range(min(stop, len(grid) + 1) - 1):
        row = grid[i]
        a = _cell(grid, i + 1, 1)
        if not a:
            continue
        if any((c or "").strip().lower() == fs.RUNNING_TOTAL_HDR for c in row):
            if a not in out:
                out.append(a)
    return out


# --------------------------------------------------------------- leaderboard

def find_campaign_leaderboard(grid: List[List[str]], label: str) -> dict:
    """The weekly leaderboard block for a campaign.

    Shape (see sort.plan_leaderboard_sorts, which reads the same structure):
    a col-A label row with col B empty, rank-numbered data rows under it, then
    a 'TOTALS' row. Only searched ABOVE the captainship boundary — the captain
    blocks reuse labels like 'Fiber - All Units' and must never be hit."""
    stop = captainship_boundary(grid)
    want = label.strip().lower()
    for i in range(min(stop, len(grid) + 1) - 1):
        r = i + 1
        if _cell(grid, r, 1).lower() != want or _cell(grid, r, 2):
            continue
        if not (_cell(grid, r + 1, 2) and _cell(grid, r + 1, 3)):
            continue                       # next row isn't a rank/name/value row
        rows: List[int] = []
        rr = r + 1
        while rr <= len(grid) and _cell(grid, rr, 1).isdigit():
            rows.append(rr)
            rr += 1
        if not rows:
            continue
        totals_row = rr if _cell(grid, rr, 1).lower() in TOTALS_LABELS else None
        last_col = max((c for row_ in rows
                        for c in range(1, len(grid[row_ - 1]) + 1)
                        if _cell(grid, row_, c)), default=3)
        return {"label_row": r, "data_rows": rows, "totals_row": totals_row,
                "last_col": last_col}
    raise ValueError(f"No campaign leaderboard block found for {label!r} "
                     f"above the captainship boundary.")


# ------------------------------------------------------------------- helpers

def already_on_board(grid: List[List[str]], label: str, name: str,
                     aliases) -> Optional[int]:
    """The daily row this person already occupies in that campaign, or None.
    Alias-aware, so a spelling variant counts as present (and we never create a
    second row for the same human)."""
    anchor = fs.find_daily_section(grid, label)
    cands = fs._candidates_for(name, aliases)
    for sheet_name, row in anchor.icd_rows.items():
        if fs._candidates_for(sheet_name, aliases) & cands:
            return row
    return None


def _insert_row(ws, at: int) -> None:
    _retry(ws.spreadsheet.batch_update, {"requests": [{
        "insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": at - 1, "endIndex": at},
            "inheritFromBefore": True}}]})


def _copy_row(ws, src: int, dst: int, c0: int, c1: int) -> None:
    """Clone a sibling row's formatting + formulas so Sheets re-points the
    relative references for the new position."""
    _retry(ws.spreadsheet.batch_update, {"requests": [{
        "copyPaste": {
            "source": {"sheetId": ws.id, "startRowIndex": src - 1,
                       "endRowIndex": src, "startColumnIndex": c0,
                       "endColumnIndex": c1},
            "destination": {"sheetId": ws.id, "startRowIndex": dst - 1,
                            "endRowIndex": dst, "startColumnIndex": c0,
                            "endColumnIndex": c1},
            "pasteType": "PASTE_NORMAL"}}]})


def _interior_insert_point(rows: List[int]) -> tuple:
    """(insert_at, sibling_row, interior) for a block's data rows.

    Interior insert (before the last row) whenever the block has 2+ rows — that
    is what makes every enclosing range grow by itself. A single-row block has
    no interior, so we insert after it and repair the ranges by hand."""
    if len(rows) >= 2:
        return rows[-1], rows[-1] - 1, True
    return rows[-1] + 1, rows[-1], False


# ---------------------------------------------------------------------- add

def _guard(ws) -> None:
    """Never the VA's own tab. Megan's standing rule for this workbook is that
    no automation writes the real board; the same hard guard roster_sync uses,
    stated positively so a renamed sandbox copy still passes."""
    from automations.org_sales_board.run import PROD_TAB
    if ws.title.strip().lower() == PROD_TAB.strip().lower():
        raise AssertionError(
            f"refusing to write the VA's real tab ({ws.title!r}) — new owners "
            f"are only ever added to the automation's copy tab.")


def add_owner(ws, label: str, name: str, *, org_head: str = "",
              aliases=None, today=None, dry_run: bool = False,
              logfn=print) -> dict:
    """Put `name` in the campaign's daily block AND its weekly leaderboard.

    Returns {'daily_row', 'leaderboard_row', 'org_head'}. The day cells are left
    at 0 — the caller re-runs that section's normal fill straight afterwards, so
    the real numbers land through the same engine as everyone else's rather than
    through a second, divergent write path."""
    import datetime as dt
    from automations.focus_office_att.aliases import load_aliases
    _guard(ws)
    aliases = aliases if aliases is not None else load_aliases()
    today = today or dt.date.today()

    grid = _retry(ws.get_all_values)
    existing = already_on_board(grid, label, name, aliases)
    if existing:
        return {"daily_row": existing, "leaderboard_row": None,
                "already": True}

    anchor = fs.find_daily_section(grid, label)
    drows = sorted(anchor.icd_rows.values())
    if not drows:
        raise ValueError(f"Section {label!r} has no ICD rows to clone from.")
    at, sib, interior = _interior_insert_point(drows)
    head_col = next((c for c in range(1, len(grid[anchor.header_row - 1]) + 1)
                     if _cell(grid, anchor.header_row, c).lower() == "org head"),
                    None)
    if dry_run:
        lb = find_campaign_leaderboard(grid, label)
        lat, _lsib, _li = _interior_insert_point(lb["data_rows"])
        logfn(f"    (dry-run) would insert {name!r} in {label}: daily row {at} "
              f"(clone of {sib}), leaderboard row {lat}")
        return {"daily_row": at, "leaderboard_row": lat, "dry_run": True}

    # ---- 1. daily breakdown ------------------------------------------------
    _insert_row(ws, at)
    time.sleep(1)
    last_c = max(anchor.running_total_col + 2, head_col or 0)
    _copy_row(ws, sib, at, 0, last_c)      # sib is always at-1, above the insert
    time.sleep(1)
    first_day, last_day = anchor.first_day_col, anchor.last_day_col
    rank = len(drows) if interior else len(drows) + 1
    data = [
        {"range": f"{ws.title}!A{at}", "values": [[rank]]},
        {"range": f"{ws.title}!B{at}", "values": [[name]]},
        {"range": f"{ws.title}!{_a1(anchor.running_total_col)}{at}",
         "values": [[f"=SUM({_a1(first_day)}{at}:{_a1(last_day)}{at})"]]},
    ]
    data.append({"range": f"{ws.title}!{_a1(first_day)}{at}:"
                          f"{_a1(last_day)}{at}",
                 "values": [[0] * (last_day - first_day + 1)]})
    # K/L — last week / previous week. BLANK, never the neighbour's history.
    data.append({"range": f"{ws.title}!{_a1(anchor.running_total_col + 1)}{at}:"
                          f"{_a1(anchor.running_total_col + 2)}{at}",
                 "values": [["", ""]]})
    if head_col:
        data.append({"range": f"{ws.title}!{_a1(head_col)}{at}",
                     "values": [[org_head or ""]]})
    _retry(ws.spreadsheet.values_batch_update,
           {"valueInputOption": "USER_ENTERED", "data": data})
    logfn(f"    daily block: row {at} (cloned {sib}, day cells 0, "
          f"K/L blank{'' if interior else ', ranges repaired'})")

    # ---- 2. weekly leaderboard --------------------------------------------
    grid = _retry(ws.get_all_values)
    lb = find_campaign_leaderboard(grid, label)
    lat, lsib, linterior = _interior_insert_point(lb["data_rows"])
    _insert_row(ws, lat)
    time.sleep(1)
    _copy_row(ws, lsib, lat, 0, lb["last_col"])   # lsib is always lat-1
    time.sleep(1)
    grid = _retry(ws.get_all_values)
    anchor = fs.find_daily_section(grid, label)          # rows moved again
    drows = sorted(anchor.icd_rows.values())
    jcol = _a1(anchor.running_total_col)
    ldata = [
        {"range": f"{ws.title}!A{lat}",
         "values": [[len(lb["data_rows"]) if linterior
                     else len(lb["data_rows"]) + 1]]},
        {"range": f"{ws.title}!B{lat}", "values": [[name]]},
        {"range": f"{ws.title}!C{lat}",
         "values": [[f"=SUMIF($B${drows[0]}:$B${drows[-1]},B{lat},"
                     f"${jcol}${drows[0]}:${jcol}${drows[-1]})"]]},
    ]
    if lb["last_col"] >= 4:                              # D.. frozen history
        ldata.append({"range": f"{ws.title}!D{lat}:{_a1(lb['last_col'])}{lat}",
                      "values": [[""] * (lb["last_col"] - 3)]})
    _retry(ws.spreadsheet.values_batch_update,
           {"valueInputOption": "USER_ENTERED", "data": ldata})
    logfn(f"    leaderboard: row {lat} (C re-pointed at the daily block, "
          f"history columns blank)")

    # ---- 3. make every enclosing range cover the new row -------------------
    repair_ranges(ws, label, logfn=logfn)
    # The leaderboard sits ABOVE the daily block, so its insert pushed the row we
    # just wrote down one. Report where the row actually IS — the bank note and
    # the log line quote these numbers.
    final_daily = at + 1 if lat <= at else at
    return {"daily_row": final_daily, "leaderboard_row": lat,
            "org_head": org_head}


def repair_ranges(ws, label: str, *, logfn=print) -> int:
    """Rewrite the ranges that must span the campaign's rep rows.

    Google expands them itself for an interior insert; this makes that true
    unconditionally (single-row blocks, or a block whose range was already short
    because someone once appended by hand). Idempotent — it writes the ranges
    the block should have, whatever they were."""
    _guard(ws)
    grid = _retry(ws.get_all_values)
    anchor = fs.find_daily_section(grid, label)
    drows = sorted(anchor.icd_rows.values())
    first, last = drows[0], drows[-1]
    jcol = anchor.running_total_col
    data = []
    for c in range(anchor.first_day_col, jcol + 1):      # daily 'Totals' row
        col = _a1(c)
        data.append({"range": f"{ws.title}!{col}{anchor.totals_row}",
                     "values": [[f"=SUM({col}{first}:{col}{last})"]]})
    lb = find_campaign_leaderboard(grid, label)
    for r in lb["data_rows"]:                            # every =SUMIF
        data.append({"range": f"{ws.title}!C{r}",
                     "values": [[f"=SUMIF($B${first}:$B${last},B{r},"
                                 f"${_a1(jcol)}${first}:${_a1(jcol)}${last})"]]})
    if lb["totals_row"]:
        data.append({"range": f"{ws.title}!C{lb['totals_row']}",
                     "values": [[f"=SUM(C{lb['data_rows'][0]}:"
                                 f"C{lb['data_rows'][-1]})"]]})
    # Col A is a plain 1..N sequence in both blocks (sort.apply_sort rewrites it
    # the same way). An insert leaves the number it displaced repeated — '…9, 10,
    # 10' — so renumber here rather than leaning on the sort that follows: an add
    # made outside a daily run would otherwise sit there looking broken.
    for rows_ in (drows, lb["data_rows"]):
        data.append({"range": f"{ws.title}!A{rows_[0]}:A{rows_[-1]}",
                     "values": [[i + 1] for i in range(len(rows_))]})
    _retry(ws.spreadsheet.values_batch_update,
           {"valueInputOption": "USER_ENTERED", "data": data})
    logfn(f"    ranges repaired for {label}: daily Totals C..{_a1(jcol)}, "
          f"{len(lb['data_rows'])} leaderboard =SUMIF(s)"
          + (", leaderboard TOTALS" if lb["totals_row"] else ""))
    return len(data)

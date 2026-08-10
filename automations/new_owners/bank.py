"""The 'New Owners' bank tab + the automation's own log tab.

THE BANK ('New Owners') is Eve's list and only Eve's list. One row per person
who is on a campaign but not yet on the Org Sales Board:

    Name | Campaign | Org Head | Captainship | Added On | Status | Activated On | Notes

She fills Name + Campaign (a dropdown of the board's real campaign labels, so a
typo can't quietly park someone forever) and, when she knows it, Org Head — the
board's col-M value, which a new row needs and which nothing else can infer.
The automation only ever writes the last three columns. Nobody is deleted from
the bank: the row stays as the record of when they went live.

THE LOG ('New Owners Log') is the automation's, and it exists because state has
to survive the machine. Two label-anchored blocks:

  * 'Key'  — the Slack thread anchors (one per year x kind). Kept HERE, not in a
    local JSON, because the Windows box and the mini both post; a per-machine
    file would open a second annual thread the first time the other machine ran.
  * 'Date' — an append-only line per add: who, where, what we did. It is also
    the idempotency record for the captainship side (which has no bank row to
    stamp), so a rep is never announced twice.

Both tabs are CREATED if missing and never rebuilt — an existing tab is read and
appended to, never cleared ([[don't touch user data]]).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional

from automations.recruiting_report.fill import _retry, open_by_key
from automations.org_sales_board.run import SHEET_ID

BANK_TAB = "New Owners"
LOG_TAB = "New Owners Log"

HEADERS = ["Name", "Campaign", "Org Head", "Captainship", "Added On",
           "Status", "Activated On", "Notes"]

# Status is the bank's only control. Blank == WAITING (so a row Eve just typed
# behaves right without her picking anything).
WAITING = "Waiting"
ADDED = "Added"
ALREADY = "Already on board"
SKIP = "Skip"                 # Eve's opt-out — the run never touches the row
UNKNOWN_CAMPAIGN = "Campaign?"

LOG_ANCHOR_HDR = ["Key", "Channel", "Thread TS", "Title"]
LOG_TABLE_HDR = ["Date", "Kind", "Name", "Campaign / Captainship", "Action",
                 "Notes"]

KIND_ORG = "Campaign"
KIND_CAPTAINSHIP = "Captainship"


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


@dataclass
class BankRow:
    row: int                  # 1-indexed sheet row
    name: str
    campaign: str
    org_head: str
    captainship: str
    added_on: str
    status: str
    activated_on: str
    notes: str

    @property
    def waiting(self) -> bool:
        s = _norm(self.status)
        return s in ("", _norm(WAITING), _norm(UNKNOWN_CAMPAIGN))


# ------------------------------------------------------------------ open/create

def _spreadsheet(ss=None):
    return ss if ss is not None else open_by_key(SHEET_ID)


def _find_tab(ss, title: str):
    for w in ss.worksheets():
        if _norm(w.title) == _norm(title):
            return w
    return None


def open_bank(ss=None, *, create: bool = True, campaigns: Optional[List[str]] = None,
              logfn=print):
    """The bank tab, created (with headers + dropdowns) the first time."""
    ss = _spreadsheet(ss)
    ws = _find_tab(ss, BANK_TAB)
    if ws is not None:
        return ws
    if not create:
        raise ValueError(f"'{BANK_TAB}' tab not found in the Org workbook.")
    logfn(f"  creating the '{BANK_TAB}' tab (first run)")
    ws = _retry(ss.add_worksheet, title=BANK_TAB, rows=200, cols=len(HEADERS) + 2)
    _retry(ws.update, [HEADERS], "A1")
    _format_bank(ws, campaigns or [])
    return ws


def _format_bank(ws, campaigns: List[str]) -> None:
    """Header styling + the two dropdowns. Dropdowns are the whole point of the
    7-year-old-simple rule here: Campaign has to match a board section label
    EXACTLY or the person waits forever, so it is picked, never typed."""
    gid = ws.id
    reqs: List[dict] = [
        {"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.85, "green": 0.89, "blue": 0.96}}},
            "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": gid,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
    ]
    if campaigns:
        reqs.append({"setDataValidation": {
            "range": {"sheetId": gid, "startRowIndex": 1,
                      "startColumnIndex": HEADERS.index("Campaign"),
                      "endColumnIndex": HEADERS.index("Campaign") + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": c}
                                              for c in campaigns]},
                     "showCustomUi": True, "strict": False}}})
    reqs.append({"setDataValidation": {
        "range": {"sheetId": gid, "startRowIndex": 1,
                  "startColumnIndex": HEADERS.index("Status"),
                  "endColumnIndex": HEADERS.index("Status") + 1},
        "rule": {"condition": {"type": "ONE_OF_LIST",
                               "values": [{"userEnteredValue": v}
                                          for v in (WAITING, SKIP, ADDED,
                                                    ALREADY)]},
                 "showCustomUi": True, "strict": False}}})
    _retry(ws.spreadsheet.batch_update, {"requests": reqs})


def refresh_campaign_dropdown(ws, campaigns: List[str]) -> None:
    """Re-point the Campaign dropdown at the board's CURRENT section labels.
    Cheap, idempotent, and it means a campaign added to the board shows up in
    the bank without a code edit."""
    if not campaigns:
        return
    _retry(ws.spreadsheet.batch_update, {"requests": [{"setDataValidation": {
        "range": {"sheetId": ws.id, "startRowIndex": 1,
                  "startColumnIndex": HEADERS.index("Campaign"),
                  "endColumnIndex": HEADERS.index("Campaign") + 1},
        "rule": {"condition": {"type": "ONE_OF_LIST",
                               "values": [{"userEnteredValue": c}
                                          for c in campaigns]},
                 "showCustomUi": True, "strict": False}}}]})


# ------------------------------------------------------------------ bank read

def _colmap(header_row: List[str]) -> Dict[str, int]:
    """Header label -> 1-indexed column. Label lookup, never a fixed index —
    someone will insert a column one day."""
    out: Dict[str, int] = {}
    for i, h in enumerate(header_row):
        key = _norm(h)
        if key:
            out[key] = i + 1
    return out


def read(ws) -> tuple:
    """(colmap, [BankRow]) — every non-empty Name row, in sheet order."""
    grid = _retry(ws.get_all_values)
    if not grid:
        return {}, []
    cmap = _colmap(grid[0])

    def cell(r: List[str], label: str) -> str:
        c = cmap.get(_norm(label))
        return (r[c - 1].strip() if c and c - 1 < len(r) else "")

    rows: List[BankRow] = []
    for i in range(1, len(grid)):
        r = grid[i]
        name = cell(r, "Name")
        if not name:
            continue
        rows.append(BankRow(
            row=i + 1, name=name, campaign=cell(r, "Campaign"),
            org_head=cell(r, "Org Head"), captainship=cell(r, "Captainship"),
            added_on=cell(r, "Added On"), status=cell(r, "Status"),
            activated_on=cell(r, "Activated On"), notes=cell(r, "Notes")))
    return cmap, rows


def _a1col(c: int) -> str:
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def mark(ws, cmap: Dict[str, int], row: int, *, status: str,
         activated_on: Optional[dt.date] = None, notes: Optional[str] = None,
         dry_run: bool = False, logfn=print) -> None:
    """Stamp ONE bank row. Only ever the three automation columns — Name,
    Campaign, Org Head and Captainship are Eve's and are never rewritten."""
    data = []
    if cmap.get(_norm("Status")):
        data.append({"range": f"{ws.title}!{_a1col(cmap[_norm('Status')])}{row}",
                     "values": [[status]]})
    if activated_on and cmap.get(_norm("Activated On")):
        data.append({"range": f"{ws.title}!"
                              f"{_a1col(cmap[_norm('Activated On')])}{row}",
                     "values": [[activated_on.strftime("%m/%d/%Y")]]})
    if notes is not None and cmap.get(_norm("Notes")):
        data.append({"range": f"{ws.title}!{_a1col(cmap[_norm('Notes')])}{row}",
                     "values": [[notes]]})
    if not data:
        return
    if dry_run:
        logfn(f"    (dry-run) bank row {row} -> {status}"
              + (f" | {notes}" if notes else ""))
        return
    _retry(ws.spreadsheet.values_batch_update,
           {"valueInputOption": "USER_ENTERED", "data": data})


# ------------------------------------------------------------------ log tab

def open_log(ss=None, *, create: bool = True, logfn=print):
    ss = _spreadsheet(ss)
    ws = _find_tab(ss, LOG_TAB)
    if ws is not None:
        return ws
    if not create:
        raise ValueError(f"'{LOG_TAB}' tab not found in the Org workbook.")
    logfn(f"  creating the '{LOG_TAB}' tab (first run)")
    ws = _retry(ss.add_worksheet, title=LOG_TAB, rows=500, cols=8)
    _retry(ws.spreadsheet.values_batch_update, {
        "valueInputOption": "USER_ENTERED",
        "data": [
            {"range": f"{ws.title}!A1",
             "values": [["New Owners — automation log. Written by "
                         "automations/new_owners. Safe to read, don't edit."]]},
            {"range": f"{ws.title}!A3", "values": [["Slack thread anchors"]]},
            {"range": f"{ws.title}!A4", "values": [LOG_ANCHOR_HDR]},
            {"range": f"{ws.title}!A9", "values": [["Log"]]},
            {"range": f"{ws.title}!A10", "values": [LOG_TABLE_HDR]},
        ]})
    _retry(ws.spreadsheet.batch_update, {"requests": [
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 3, "endRowIndex": 4},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 9, "endRowIndex": 10},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat"}},
    ]})
    return ws


def _header_row(grid: List[List[str]], first_label: str) -> Optional[int]:
    """1-indexed row of the block whose col A is `first_label` (label-anchored,
    so the blocks can move down the tab without breaking)."""
    for i, r in enumerate(grid):
        if r and _norm(r[0]) == _norm(first_label):
            return i + 1
    return None


def _block_rows(grid: List[List[str]], hdr_row: int) -> List[int]:
    """Data rows under a header row: contiguous non-empty col-A rows."""
    out = []
    for i in range(hdr_row, len(grid)):
        if not (grid[i] and (grid[i][0] or "").strip()):
            break
        out.append(i + 1)
    return out


def thread_anchor(ws, key: str) -> Optional[dict]:
    """{channel, ts, title} for a thread key ('2026-campaign'), or None."""
    grid = _retry(ws.get_all_values)
    hdr = _header_row(grid, LOG_ANCHOR_HDR[0])
    if hdr is None:
        return None
    for r in _block_rows(grid, hdr):
        row = grid[r - 1]
        if _norm(row[0]) == _norm(key):
            return {"row": r,
                    "channel": (row[1] if len(row) > 1 else "").strip(),
                    "ts": (row[2] if len(row) > 2 else "").strip(),
                    "title": (row[3] if len(row) > 3 else "").strip()}
    return None


def save_thread_anchor(ws, key: str, channel: str, ts: str, title: str) -> None:
    """Record a freshly created annual thread. Written IMMEDIATELY after the
    parent post so a crash mid-run can't strand it."""
    grid = _retry(ws.get_all_values)
    hdr = _header_row(grid, LOG_ANCHOR_HDR[0])
    if hdr is None:                      # tab hand-edited into an odd shape
        raise ValueError(f"'{LOG_TAB}': no '{LOG_ANCHOR_HDR[0]}' header row.")
    rows = _block_rows(grid, hdr)
    at = (rows[-1] + 1) if rows else hdr + 1
    # Two anchors a year eat down the gap towards the 'Log' block below. If the
    # next slot is already something else, make room instead of writing over it.
    occupied = at - 1 < len(grid) and (grid[at - 1] or [""])[0].strip()
    if occupied:
        _retry(ws.spreadsheet.batch_update, {"requests": [{
            "insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "ROWS",
                          "startIndex": at - 1, "endIndex": at},
                "inheritFromBefore": True}}]})
    # RAW, not USER_ENTERED: a Slack ts ("1700000000.000002") is a STRING that
    # looks like a number, and USER_ENTERED stores it as one — Sheets then hands
    # back "1700000000" and the thread can never be found again.
    _retry(ws.spreadsheet.values_batch_update, {
        "valueInputOption": "RAW",
        "data": [{"range": f"{ws.title}!A{at}",
                  "values": [[key, channel, ts, title]]}]})


def log_entries(ws) -> List[dict]:
    """Every logged add: {date, kind, name, scope, action, notes}."""
    grid = _retry(ws.get_all_values)
    hdr = _header_row(grid, LOG_TABLE_HDR[0])
    if hdr is None:
        return []
    out = []
    for r in _block_rows(grid, hdr):
        row = (grid[r - 1] + [""] * 6)[:6]
        out.append({"row": r, "date": row[0].strip(), "kind": row[1].strip(),
                    "name": row[2].strip(), "scope": row[3].strip(),
                    "action": row[4].strip(), "notes": row[5].strip()})
    return out


def already_logged(entries: List[dict], kind: str, name: str,
                   scope: str) -> bool:
    """Has this (kind, person, captainship/campaign) already been handled?

    The captainship side has no bank row to stamp, so THIS is what stops a rep
    being announced again every single morning."""
    k, n, s = _norm(kind), _norm(name), _norm(scope)
    return any(_norm(e["kind"]) == k and _norm(e["name"]) == n
               and _norm(e["scope"]) == s for e in entries)


def update_log(ws, row: int, *, action: Optional[str] = None,
               notes: Optional[str] = None, dry_run: bool = False,
               logfn=print) -> None:
    """Rewrite one log line's Action / Notes — how a pending approval becomes a
    done one without a second line saying the same thing twice."""
    data = []
    if action is not None:
        data.append({"range": f"{ws.title}!E{row}", "values": [[action]]})
    if notes is not None:
        data.append({"range": f"{ws.title}!F{row}", "values": [[notes]]})
    if not data:
        return
    if dry_run:
        logfn(f"    (dry-run) log row {row} -> {action or ''} | {notes or ''}")
        return
    _retry(ws.spreadsheet.values_batch_update,
           {"valueInputOption": "RAW", "data": data})     # ts stays text


def append_log(ws, rows: List[List[str]], *, dry_run: bool = False,
               logfn=print) -> None:
    """Append lines to the log table (never overwrite — the block below the
    'Date' header only grows)."""
    if not rows:
        return
    if dry_run:
        for r in rows:
            logfn(f"    (dry-run) log += {r}")
        return
    grid = _retry(ws.get_all_values)
    hdr = _header_row(grid, LOG_TABLE_HDR[0])
    if hdr is None:
        raise ValueError(f"'{LOG_TAB}': no '{LOG_TABLE_HDR[0]}' header row.")
    used = _block_rows(grid, hdr)
    at = (used[-1] + 1) if used else hdr + 1
    if at + len(rows) > ws.row_count:
        _retry(ws.add_rows, len(rows) + 50)
    _retry(ws.spreadsheet.values_batch_update, {
        "valueInputOption": "RAW",          # the Notes column carries Slack ts
        "data": [{"range": f"{ws.title}!A{at}", "values": rows}]})

"""The send ledger -- our own tab, so nobody gets Blue Ink twice.

Lives in the same workbook (not a local file) on purpose: the Hub runs from any
machine and Lucy 2 runs it on a schedule, so the "already sent" record has to be
somewhere both can see. We create and own this tab; we never write into the
recruiting team's own OBCL columns.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

import gspread

from automations.blueink_docs import config
from automations.blueink_docs.roster import NewStart, _norm

HEADER = ["Sent At", "Week Tab", "Name", "Email", "Bundle ID",
          "Status", "Last Checked", "Note"]

COL_WEEK, COL_NAME, COL_EMAIL = 1, 2, 3
COL_BUNDLE, COL_STATUS, COL_CHECKED = 4, 5, 6


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def open_ledger(workbook):
    """The ledger tab, created with its header the first time we ever send."""
    try:
        return workbook.worksheet(config.LEDGER_TAB)
    except gspread.WorksheetNotFound:
        ws = workbook.add_worksheet(config.LEDGER_TAB, rows=500, cols=len(HEADER))
        ws.update("A1", [HEADER])
        return ws


def read(workbook) -> List[List[str]]:
    try:
        return workbook.worksheet(config.LEDGER_TAB).get_all_values()[1:]
    except gspread.WorksheetNotFound:
        return []


def already_sent(workbook) -> Dict[str, str]:
    """{person key: bundle id} for everyone who has ever been sent.

    Keyed by normalized name AND by email, because a name gets respelled
    between tabs more often than an address does -- either hit is enough to
    hold fire. A row with no bundle id was a failure, not a send.
    """
    out: Dict[str, str] = {}
    for row in read(workbook):
        row = (row + [""] * len(HEADER))[:len(HEADER)]
        bundle = row[COL_BUNDLE].strip()
        if not bundle:
            continue
        name = row[COL_NAME].strip()
        email = row[COL_EMAIL].strip().lower()
        parts = name.split()
        if len(parts) >= 2:
            out[f"{_norm(parts[-1])}|{_norm(' '.join(parts[:-1]))}"] = bundle
        if email:
            out[email] = bundle
    return out


def seen(sent_map: Dict[str, str], person: NewStart) -> str:
    return sent_map.get(person.key) or sent_map.get(person.email.strip().lower(), "")


def record(workbook, rows: List[list]) -> None:
    """Append every send in ONE call.

    A per-row append loop burns through the Sheets write quota and 429s the
    next report as well as this one, so the whole batch goes up together.
    """
    if not rows:
        return
    open_ledger(workbook).append_rows(rows, value_input_option="RAW")


def row_for(person: NewStart, bundle_id: str, status: str, note: str = "") -> list:
    return [_now(), person.tab, person.name, person.email,
            bundle_id, status, _now(), note]


def update_statuses(workbook, updates: Dict[int, str]) -> None:
    """{sheet row number: new status} -> one batched write."""
    if not updates:
        return
    ws = open_ledger(workbook)
    now = _now()
    ws.batch_update([
        {"range": gspread.utils.rowcol_to_a1(r, COL_STATUS + 1)
                  + ":" + gspread.utils.rowcol_to_a1(r, COL_CHECKED + 1),
         "values": [[status, now]]}
        for r, status in sorted(updates.items())
    ], value_input_option="RAW")

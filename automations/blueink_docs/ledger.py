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

COL_SENT_AT = 0
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


def already_sent(workbook, rows: List[List[str]] = None) -> Dict[str, str]:
    """{person key: bundle id} for everyone who has ever been sent.

    Keyed by normalized name AND by email, because a name gets respelled
    between tabs more often than an address does -- either hit is enough to
    hold fire. A row with no bundle id was a failure, not a send.

    `rows` lets a caller that already read the tab hand them in, so asking two
    questions of the ledger in one run costs one Sheets read, not two.
    """
    out: Dict[str, str] = {}
    for row in (read(workbook) if rows is None else rows):
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


def sent_when(rows: List[List[str]]) -> Dict[str, str]:
    """{person key / email: 'M/D/YY'} for the LAST send we logged for them.

    Same keys as `already_sent`, so the same person is found the same way; the
    value is the date instead of the bundle, because that is the half a reader
    needs. A carried-over row on the sheet says nothing on its own -- "sent" and
    "nobody has touched this" look identical -- so the date is what tells whoever
    reads Slack whether to chase a signature or leave it alone.

    Rows are appended in time order, so a later send simply overwrites an
    earlier one and the newest date wins.
    """
    out: Dict[str, str] = {}
    for row in (rows or []):
        row = (row + [""] * len(HEADER))[:len(HEADER)]
        if not row[COL_BUNDLE].strip():
            continue                      # a failure row is not a send
        when = _sent_on(row[COL_SENT_AT])
        if not when:
            continue
        stamp = "%d/%d/%s" % (when.month, when.day, when.strftime("%y"))
        name = row[COL_NAME].strip()
        email = row[COL_EMAIL].strip().lower()
        parts = name.split()
        if len(parts) >= 2:
            out[f"{_norm(parts[-1])}|{_norm(' '.join(parts[:-1]))}"] = stamp
        if email:
            out[email] = stamp
    return out


def when(when_map: Dict[str, str], person: NewStart) -> str:
    """The date we last sent this person, '' if we never did."""
    return (when_map.get(person.key)
            or when_map.get(person.email.strip().lower(), ""))


def a_recent_send(rows: List[List[str]], within_days: int,
                  today: dt.date = None) -> str:
    """One address this report sent and logged RECENTLY -- the address the
    pre-send duplicate check uses as its positive canary.

    Newest first, and preferring something inside `within_days`: the canary
    proves Blue Ink's search still finds our own sends, so it should ask about
    a packet the app is certainly still listing, not the oldest row we ever
    wrote. Falls back to the newest logged address whatever its age -- an
    imperfect canary still tests the search, and NO canary is what lets a
    search that has stopped finding anything sail through and mail everybody a
    second packet.

    Empty only when the ledger holds no send at all (the first-ever run).
    """
    today = today or dt.date.today()
    newest, fallback = "", ""
    for row in reversed(rows or []):
        row = (row + [""] * len(HEADER))[:len(HEADER)]
        email = row[COL_EMAIL].strip().lower()
        if not email or "@" not in email or not row[COL_BUNDLE].strip():
            continue
        fallback = fallback or email
        when = _sent_on(row[COL_SENT_AT])
        if when and 0 <= (today - when).days <= within_days:
            newest = email
            break
    return newest or fallback


def _sent_on(stamp: str):
    """The date out of a 'Sent At' cell, or None if it can't be read."""
    try:
        return dt.datetime.strptime(str(stamp or "").strip()[:10],
                                    "%Y-%m-%d").date()
    except ValueError:
        return None


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

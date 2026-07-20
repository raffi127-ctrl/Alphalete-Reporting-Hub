"""Read the week's new starts out of the D2D OBCL workbook.

Source path (spell it out, per house rule):
  workbook  https://docs.google.com/spreadsheets/d/1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4
  tab       "D2D OBCL <M>.<D>"  (the tab whose A1 holds the Monday start date)
  header    row 2
  columns   B "2ND Round Interviewer", D "Name", E "Last Name", H "Phone",
            J "Final Status"
  rows      3..end, one per scheduled new start

Tab and column are BOTH found by label, never by index -- Aisha renames the tab
every week and inserts columns mid-season.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

from automations.recruiting_report import fill

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"

HEADER_ROW = 2  # 1-indexed; row 1 is the week date banner
INTERVIEWER_HEADER = "2ND Round Interviewer"
FIRST_NAME_HEADER = "Name"
LAST_NAME_HEADER = "Last Name"
PHONE_HEADER = "Phone"
STATUS_HEADER = "Final Status"

# Statuses that mean "this person is not actually starting Monday", so their
# interviewer shouldn't be counted as owing them a text.
DROPPED_STATUSES = {"declined", "cancelled", "canceled", "no show", "rescheduled"}


class NewStart:
    """One scheduled new start."""

    def __init__(self, interviewer: str, name: str, phone: str, status: str, row: int):
        self.interviewer = interviewer
        self.name = name
        self.phone = phone
        self.status = status
        self.row = row

    @property
    def dropped(self) -> bool:
        return self.status.strip().lower() in DROPPED_STATUSES

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "NewStart({!r}, {!r}, {!r})".format(self.interviewer, self.name, self.status)


def upcoming_monday(today: Optional[dt.date] = None) -> dt.date:
    """The Monday these new starts begin.

    The cycle runs Fri->Sun for the FOLLOWING Monday, so from any of Fri/Sat/Sun
    (and Mon itself, for a same-day re-run) we want the next Monday on or after
    today.
    """
    today = today or dt.date.today()
    ahead = (0 - today.weekday()) % 7  # 0 = Monday
    return today + dt.timedelta(days=ahead)


def _tab_date(title: str) -> Optional[tuple]:
    """'D2D OBCL 7.20' -> (7, 20). None if the title isn't a dated OBCL tab."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\s*$", title.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def find_week_tab(sheet, monday: dt.date):
    """The OBCL tab for `monday`, matched on the date in its title.

    Raises if there's no tab for that week -- silently falling back to the
    newest tab would text last week's leaders about last week's new starts.
    """
    want = (monday.month, monday.day)
    candidates = []
    for ws in sheet.worksheets():
        if not ws.title.upper().startswith("D2D OBCL"):
            continue
        got = _tab_date(ws.title)
        if got is None:
            continue
        candidates.append((got, ws))
        if got == want:
            return ws
    seen = ", ".join(sorted(ws.title for _, ws in candidates)) or "(none)"
    raise RuntimeError(
        "No OBCL tab for the week of {}. Expected a tab named 'D2D OBCL {}.{}'. "
        "Tabs found: {}".format(monday.isoformat(), monday.month, monday.day, seen)
    )


def _col(header_row: List[str], label: str) -> int:
    """Index of `label` in the header row. Tolerates stray whitespace/newlines
    (column K's header is literally '\\nBG Status : Last Checked ')."""
    norm = [re.sub(r"\s+", " ", (h or "")).strip().lower() for h in header_row]
    want = re.sub(r"\s+", " ", label).strip().lower()
    if want in norm:
        return norm.index(want)
    raise RuntimeError(
        "OBCL column {!r} not found. Headers on row {}: {}".format(
            label, HEADER_ROW, [h for h in header_row if h]
        )
    )


def read_new_starts(monday: Optional[dt.date] = None, sheet_id: str = SHEET_ID):
    """-> (monday, tab_title, [NewStart, ...]) for the week starting `monday`."""
    monday = monday or upcoming_monday()
    sheet = fill.open_by_key(sheet_id)
    ws = find_week_tab(sheet, monday)
    grid = ws.get_all_values()
    if len(grid) < HEADER_ROW + 1:
        raise RuntimeError("OBCL tab {!r} is empty.".format(ws.title))

    header = grid[HEADER_ROW - 1]
    i_int = _col(header, INTERVIEWER_HEADER)
    i_first = _col(header, FIRST_NAME_HEADER)
    i_last = _col(header, LAST_NAME_HEADER)
    i_phone = _col(header, PHONE_HEADER)
    i_status = _col(header, STATUS_HEADER)

    def cell(row: List[str], idx: int) -> str:
        return (row[idx] if idx < len(row) else "").strip()

    starts = []
    for n, row in enumerate(grid[HEADER_ROW:], start=HEADER_ROW + 1):
        interviewer = cell(row, i_int)
        first = cell(row, i_first)
        last = cell(row, i_last)
        if not interviewer and not first:
            continue
        name = " ".join(p for p in (first, last) if p)
        starts.append(
            NewStart(
                interviewer=interviewer,
                name=name,
                phone=cell(row, i_phone),
                status=cell(row, i_status),
                row=n,
            )
        )
    return monday, ws.title, starts


def counts_by_interviewer(starts: List[NewStart]) -> Dict[str, int]:
    """How many new starts each interviewer owes a text, dropped ones excluded."""
    out = {}  # type: Dict[str, int]
    for s in starts:
        if s.dropped or not s.interviewer:
            continue
        out[s.interviewer] = out.get(s.interviewer, 0) + 1
    return out

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
from automations.shared import new_start_eligibility as eligibility

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"

# The rolling all-history tab (every new start ever), as opposed to the dated
# weekly tabs. No longer read here — its only user was phone_book(), removed
# 2026-08-23 (see the tombstone below). Kept for reference.
ROLLING_TAB = "D2D OBCL"

HEADER_ROW = 2  # 1-indexed; row 1 is the week date banner
INTERVIEWER_HEADER = "2ND Round Interviewer"
FIRST_NAME_HEADER = "Name"
LAST_NAME_HEADER = "Last Name"
PHONE_HEADER = "Phone"
STATUS_HEADER = "Final Status"
# The columns that ACTUALLY carry a decline. "Final Status" is the one this
# module read for months and it is empty on every row — the live signal is
# "Friday Confirmation" (red "Declined" / "Failed Background") with
# "BG Status : Last Checked" beside it. Aisha's weekly screenshot is a picture
# of THIS tab, so the sheet has always held it; we were reading the wrong
# column (Megan 2026-09-13: "the OBCL is what she's taking a screenshot of so
# it's def on there"). Both are optional — an older tab may not have them.
CONFIRMATION_HEADER = "Friday Confirmation"
BG_STATUS_HEADER = "BG Status : Last Checked"

# DROPPED_STATUSES REMOVED 2026-09-26. "Not actually starting Monday" is a
# FAMILY-WIDE rule and lives in automations/shared/new_start_eligibility
# (`not_starting`). This module used to carry its own set of six exact Final
# Status values while Blue Ink and Digi Docs used a longer substring list, so
# somebody Terminated / Quit / Backed Out / Adverse Action was skipped for
# documents while their interviewer was still counted as owing them a text.
#
# Don't reintroduce a bare list here: the old code tested every status cell
# against every list, which let a Final Status word block on a Friday
# Confirmation cell. `not_starting` checks each column against its own rule.


class NewStart:
    """One scheduled new start."""

    def __init__(self, interviewer: str, name: str, phone: str, status: str,
                 row: int, confirmation: str = "", bg_status: str = ""):
        self.interviewer = interviewer
        self.name = name
        self.phone = phone
        self.status = status
        self.row = row
        self.confirmation = confirmation
        self.bg_status = bg_status

    @property
    def self_assigned(self) -> bool:
        """The interviewer cell holds the NEW START'S own name.

        Nobody is their own 2nd-round interviewer. The OBCL tab carries a
        second block below the real table (rows 68+ on the 9/7 tab) where each
        person is listed against themselves; read as real assignments they
        became interviewers nobody could tag, and 8 new starts were posted in
        Slack as "needs a manual reach-out" (2026-09-06).
        """
        from automations.new_start_followup.roster import _norm
        a, b = _norm(self.interviewer or ""), _norm(self.name or "")
        if not a or not b:
            return False
        # Either direction, because the two cells spell it differently:
        # 'Anibal Delgado' against 'Anibal Delgado Rivadeneira'.
        return a == b or a.startswith(b) or b.startswith(a)

    @property
    def drop_reason(self) -> str:
        """Why they are not starting (naming the column), or "" if they are.

        The shared family rule, so this module, Blue Ink, Digi Docs and the
        Slack/Skool email all agree about who counts. Each column is checked as
        the column it is -- the old code folded all three together and tested
        every value against every list, which let a Final Status word block on
        a Friday Confirmation cell and vice versa.
        """
        return eligibility.not_starting(final_status=self.status,
                                        bg_status=self.bg_status,
                                        friday=self.confirmation)

    @property
    def dropped(self) -> bool:
        """Not actually starting Monday, so their interviewer owes no text."""
        return bool(self.drop_reason)

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

    def _optional_col(label):
        """Newer columns — absent on an older tab, and their absence must not
        take the read down."""
        try:
            return _col(header, label)
        except RuntimeError:
            print("[obcl] no {!r} column on this tab.".format(label))
            return -1

    i_conf = _optional_col(CONFIRMATION_HEADER)
    i_bg = _optional_col(BG_STATUS_HEADER)

    def cell(row: List[str], idx: int) -> str:
        return (row[idx] if idx < len(row) else "").strip()

    starts = []
    for n, row in enumerate(grid[HEADER_ROW:], start=HEADER_ROW + 1):
        interviewer = cell(row, i_int)
        first = cell(row, i_first)
        last = cell(row, i_last)
        if not interviewer and not first:
            # END OF THE TABLE, not a row to skip. The 9.7 tab runs to row 65
            # and then, after one blank row, carries a leftover block where
            # each person is listed against THEMSELVES in the interviewer
            # column. Walking past the blank read those as real assignments:
            # 27 names — last week's people, and leaders like Tadana
            # Manyangadze who aren't new starts at all — were posted to Raf as
            # "new starts needing a leader assigned" (Megan 2026-09-06).
            # A blank row is a boundary everywhere else in this repo; it is one
            # here too. Verified on the 9.7 tab: the first blank is row 66, and
            # the real table above it has none.
            break
        if interviewer.lower() == INTERVIEWER_HEADER.lower():
            # A repeated header row pasted into the data area (week of 8/24) —
            # not a person, and it leaked into the posted "unable to tag" list.
            continue
        name = " ".join(p for p in (first, last) if p)
        starts.append(
            NewStart(
                interviewer=interviewer,
                name=name,
                phone=cell(row, i_phone),
                status=cell(row, i_status),
                row=n,
                confirmation=cell(row, i_conf) if i_conf >= 0 else "",
                bg_status=cell(row, i_bg) if i_bg >= 0 else "",
            )
        )
    return monday, ws.title, starts


# phone_book() REMOVED 2026-08-23 (Megan): the Phone column on the OBCL is
# the NEW START'S number, not the interviewer's. The old "leaders were new
# starts once, so their number is on the rolling tab" name-match was a
# foot-gun — a name collision or stale row texts a brand-new hire a leader
# chase message. NEVER text a number read off this sheet. Leader numbers come
# only from the machine-local overlay (roster.load_phones — hand-entered, or
# filled from Lucy 1's Contacts via contacts.py).


def counts_by_interviewer(starts: List[NewStart]) -> Dict[str, int]:
    """How many new starts each interviewer owes a text, dropped ones excluded."""
    out = {}  # type: Dict[str, int]
    for s in starts:
        if s.dropped or s.self_assigned or not s.interviewer:
            continue
        out[s.interviewer] = out.get(s.interviewer, 0) + 1
    return out

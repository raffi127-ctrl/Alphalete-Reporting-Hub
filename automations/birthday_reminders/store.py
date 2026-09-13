"""Read and write the 'DOB LUCY' tab -- the birthday store for Raf's office.

APPEND-ONLY, DELIBERATELY (Megan, asked directly 2026-09-13: does a terminated
rep come off this tab? No).

  * Rehires would lose their birthday. 64 names on 'Terminated Reps' hold more
    than one row -- Miles Williams has three -- so pruning on termination means
    every rehire comes back with no DOB and has to be re-pulled from Blue Ink.
  * Automations append or overwrite MAPPED cells; they never delete filled data.
    [[don't touch user data without confirming]]
  * Storage and liveness are different questions. This tab answers "when is
    their birthday", a fact that never changes. Whether to TEXT them is decided
    at send time (see liveness.py). Keep them apart and a bug in the terminated
    read cannot destroy data.
  * A pruned tab hides its own mistakes: a wrongly-deleted rep is invisible,
    where a wrongly-skipped one shows up in the run's skip list.

So nothing here deletes a row. The only column a person owns is `Skip` -- typed
by hand to opt somebody out -- and this module reads it and never writes it.

A BIRTHDAY IS STORED AS MM/DD, NOT A FULL DATE. The year is PII we have no
reason to keep in a Sheet, and the reminder only ever asks "is it tomorrow".
`mmdd()` throws the year away on the way in.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from automations.birthday_reminders import config as C
from automations.recruiting_report.fill import open_by_key
from automations.terminated_reps.board import base_name, norm_name


class StoreError(RuntimeError):
    """The tab is missing, or its headers are not the ones we write."""


# '6/28/2004', '06-28-04', '2004-06-28' -- the shapes blueink_data lets through.
_SLASHED = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def mmdd(value) -> str:
    """A DOB in any shape Blue Ink or Apex produces -> 'MM/DD'. '' if unusable.

    The YEAR IS DROPPED HERE and never written anywhere. Day and month are
    range-checked, so a transposed '28/06/2004' comes back empty rather than
    being stored as a month of 28 -- a birthday quietly landing on the wrong
    day is worse than one we admit we don't have.
    """
    s = str(value or "").strip()
    if not s:
        return ""
    m = _ISO.match(s)
    if m:
        _y, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _SLASHED.match(s)
        if not m:
            return ""
        mo, da = int(m.group(1)), int(m.group(2))
    try:
        # 2024 is a leap year, so 02/29 validates -- a real birthday we must keep.
        dt.date(2024, mo, da)
    except ValueError:
        return ""
    return "%02d/%02d" % (mo, da)


def today_mmdd(day: dt.date) -> str:
    return "%02d/%02d" % (day.month, day.day)


@dataclass
class Entry:
    """One row of the tab."""
    name: str
    mmdd: str
    source: str = ""
    added: str = ""
    skip: str = ""
    notes: str = ""
    row: int = 0

    @property
    def opted_out(self) -> bool:
        """Anything typed in Skip means don't text them. A person put it there;
        we don't interpret it beyond 'not empty'."""
        return bool((self.skip or "").strip())

    @property
    def key(self) -> str:
        return base_name(self.name)


def _open(sheet_id: str = C.STORE_SHEET_ID, tab: str = C.STORE_TAB):
    import gspread
    sh = open_by_key(sheet_id)
    try:
        return sh, sh.worksheet(tab)
    except gspread.WorksheetNotFound as e:  # noqa: PERF203
        raise StoreError(
            "no %r tab in that workbook. Create it once with "
            "`python -m automations.birthday_reminders.run --init`." % tab) from e


def _columns(header: list) -> dict:
    """{label: 0-based index} for the headers we know, found BY LABEL.

    Extra columns somebody added are ignored, not an error -- the tab belongs to
    the office, not to this report.
    """
    got = {str(h).strip().lower(): i for i, h in enumerate(header)}
    cols = {}
    for want in C.HEADERS:
        i = got.get(want.strip().lower())
        if i is not None:
            cols[want] = i
    missing = [w for w in (C.COL_NAME, C.COL_MMDD) if w not in cols]
    if missing:
        raise StoreError(
            "the %r tab is missing the %s column(s). Found: %s"
            % (C.STORE_TAB, ", ".join(repr(m) for m in missing),
               ", ".join(repr(str(h)) for h in header if str(h).strip())))
    return cols


def load(sheet_id: str = C.STORE_SHEET_ID, tab: str = C.STORE_TAB) -> list[Entry]:
    """Every filled row. Blank names skipped; the rest come back as typed."""
    _sh, ws = _open(sheet_id, tab)
    grid = ws.get_all_values()
    if not grid:
        raise StoreError("the %r tab is empty -- not even headers." % tab)
    cols = _columns(grid[0])

    def cell(row, label):
        i = cols.get(label)
        return str(row[i]).strip() if i is not None and i < len(row) else ""

    out = []
    for n, row in enumerate(grid[1:], start=2):
        name = cell(row, C.COL_NAME)
        if not name:
            continue
        out.append(Entry(name=name, mmdd=cell(row, C.COL_MMDD),
                         source=cell(row, C.COL_SOURCE),
                         added=cell(row, C.COL_ADDED),
                         skip=cell(row, C.COL_SKIP),
                         notes=cell(row, C.COL_NOTES), row=n))
    return out


def birthdays_on(entries, day_mmdd: str) -> list[Entry]:
    """Everyone whose stored MM/DD is `day_mmdd`, opt-outs already removed."""
    return [e for e in entries
            if e.mmdd.strip() == day_mmdd and not e.opted_out]


def index(entries) -> dict:
    """{folded name: Entry} so a caller can ask 'do we already have them'."""
    return {e.key: e for e in entries if e.key}


def append(new: list, *, sheet_id: str = C.STORE_SHEET_ID,
           tab: str = C.STORE_TAB, dry_run: bool = True) -> dict:
    """Add rows for people we don't already hold. Never updates, never deletes.

    A name already on the tab is SKIPPED, not overwritten: if the stored MM/DD
    disagrees with a fresh read, that is a question for a person, not something
    to silently resolve. It comes back in `conflicts`.
    """
    _sh, ws = _open(sheet_id, tab)
    grid = ws.get_all_values()
    cols = _columns(grid[0])
    have = index(load(sheet_id, tab))

    added, skipped, conflicts = [], [], []
    rows = []
    for e in new:
        if not e.mmdd:
            skipped.append((e.name, "no usable birthday"))
            continue
        seen = have.get(base_name(e.name))
        if seen is not None:
            if seen.mmdd and seen.mmdd != e.mmdd:
                conflicts.append((e.name, seen.mmdd, e.mmdd))
            else:
                skipped.append((e.name, "already on the tab"))
            continue
        width = max(len(grid[0]), max(cols.values()) + 1)
        row = [""] * width
        row[cols[C.COL_NAME]] = e.name
        row[cols[C.COL_MMDD]] = e.mmdd
        for label, value in ((C.COL_SOURCE, e.source), (C.COL_ADDED, e.added),
                             (C.COL_NOTES, e.notes)):
            if label in cols:
                row[cols[label]] = value
        rows.append(row)
        added.append(e.name)
        have[base_name(e.name)] = e          # dedupe within this batch too

    if rows and not dry_run:
        # append_row/append_rows lands after the last NON-EMPTY row, which is
        # what we want here: unlike 'Terminated Reps', this tab is not seeded
        # with thousands of pre-formatted blanks.
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    return {"added": added, "skipped": skipped, "conflicts": conflicts,
            "dry_run": dry_run, "wrote": len(rows) if not dry_run else 0}


def create_tab(*, sheet_id: str = C.STORE_SHEET_ID, tab: str = C.STORE_TAB,
               dry_run: bool = True) -> dict:
    """Create the tab with its headers. Refuses if it already exists.

    Creating is the only structural write this report ever makes, and it is
    behind an explicit --init rather than happening on a normal run: a report
    that conjures tabs on its own is one bad sheet id away from littering
    somebody's workbook.
    """
    import gspread
    sh = open_by_key(sheet_id)
    try:
        sh.worksheet(tab)
        return {"created": False, "why": "already exists", "dry_run": dry_run}
    except gspread.WorksheetNotFound:
        pass
    if dry_run:
        return {"created": False, "why": "dry run", "dry_run": True,
                "headers": list(C.HEADERS)}
    ws = sh.add_worksheet(title=tab, rows=500, cols=max(8, len(C.HEADERS)))
    ws.update([list(C.HEADERS)], "A1")
    ws.freeze(rows=1)
    return {"created": True, "dry_run": False, "headers": list(C.HEADERS)}

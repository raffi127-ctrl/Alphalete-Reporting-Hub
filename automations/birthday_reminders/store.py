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
from automations.terminated_reps.board import base_name, norm_name, to_date


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
    start: str = ""
    staff: str = ""

    @property
    def is_staff(self) -> bool:
        """Typed by a person: not a rep, so the sales board can't vouch for them."""
        return bool((self.staff or "").strip())

    @property
    def start_date(self):
        return to_date(self.start)

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
                         notes=cell(row, C.COL_NOTES), row=n,
                         start=cell(row, C.COL_START),
                         staff=cell(row, C.COL_STAFF)))
    return out


def birthdays_on(entries, day_mmdd: str) -> list[Entry]:
    """Everyone whose stored MM/DD is `day_mmdd`, opt-outs already removed."""
    return [e for e in entries
            if e.mmdd.strip() == day_mmdd and not e.opted_out]


def anniversaries_on(entries, day: dt.date) -> list:
    """[(Entry, years)] for everyone who started on this month/day in an
    EARLIER year. A start date of today is a first day, not an anniversary.
    Feb 29 starters are celebrated Feb 28 in other years rather than skipped."""
    out = []
    for e in entries:
        start = e.start_date
        if e.opted_out or not start or start.year >= day.year:
            continue
        mo, da = start.month, start.day
        if (mo, da) == (2, 29) and not _is_leap(day.year):
            da = 28
        if (mo, da) == (day.month, day.day):
            out.append((e, day.year - start.year))
    return out


def _is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


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
        # A rep with no birthday on file still gets a row when we know their
        # start date: the anniversary needs it, and the blank birthday cell is
        # where a person types it in later.
        if not e.mmdd and not e.start:
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
                             (C.COL_NOTES, e.notes), (C.COL_START, e.start),
                             (C.COL_STAFF, e.staff)):
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


def _a1_col(i: int) -> str:
    """0-based column index -> 'A', 'B', ... 'AA'."""
    s, n = "", i + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def ensure_columns(*, sheet_id: str = C.STORE_SHEET_ID, tab: str = C.STORE_TAB,
                   dry_run: bool = True) -> list:
    """Add any of our headers row 1 lacks, AFTER the last used column.

    Only ever writes into empty header cells to the right of what is there --
    never moves or renames a column somebody else relies on.
    """
    _sh, ws = _open(sheet_id, tab)
    grid = ws.get_all_values()
    header = grid[0] if grid else []
    have = {str(h).strip().lower() for h in header}
    missing = [h for h in C.HEADERS if h.strip().lower() not in have]
    if missing and not dry_run:
        last = max((i for i, h in enumerate(header) if str(h).strip()), default=-1)
        start = last + 1
        rng = "%s1:%s1" % (_a1_col(start), _a1_col(start + len(missing) - 1))
        if ws.col_count < start + len(missing):
            ws.add_cols(start + len(missing) - ws.col_count)
        ws.update([missing], rng)
    return missing


def fill_blank(label: str, values: dict, *, sheet_id: str = C.STORE_SHEET_ID,
               tab: str = C.STORE_TAB, dry_run: bool = True) -> list:
    """{sheet row: value} -> written into `label`'s column ONLY where the cell
    is empty now. A value already there -- typed by a person or by us -- wins.
    Returns the rows actually (or, on a dry run, would-be) written."""
    _sh, ws = _open(sheet_id, tab)
    grid = ws.get_all_values()
    cols = _columns(grid[0])
    i = cols.get(label)
    if i is None or not values:
        return []
    updates, wrote = [], []
    for row, value in sorted(values.items()):
        cur = grid[row - 1][i] if row - 1 < len(grid) and i < len(grid[row - 1]) else ""
        if str(cur).strip() or not str(value).strip():
            continue
        updates.append({"range": "%s%d" % (_a1_col(i), row), "values": [[value]]})
        wrote.append(row)
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    return wrote


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

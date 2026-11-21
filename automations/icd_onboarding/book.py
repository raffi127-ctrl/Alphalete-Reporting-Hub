"""Each ICD's OWN onboarding workbook, and a tab for each week in it.

Megan, 2026-11-21: "Every ICD who launches in LucyECO Onboarding should get
their own workbook and a new tab created each week where all this data can
live but it still shows in the extension", and "we should be creating our own
NEW OBCL for Raf and not editing anything existing".

WHAT THIS REPLACES. The board was one `Onboarding` tab with the weeks stacked
in it, living inside a workbook the office already owned -- their metrics
book, or for Alphalete the All in One. Two things were wrong with that: we
were writing into somebody else's sheet, and a week could only be told from
another by a column.

WHY TAB-PER-WEEK IS RIGHT NOW AND WAS NOT BEFORE. `board.WEEK` carries the
note that tabs-per-week "would put 52 a year into somebody's own workbook".
That objection was about THEIR book. In a workbook that exists only for
onboarding, 52 tabs a year is the filing, not clutter -- and it is the same
shape the D2D OBCL already uses ("D2D OBCL 11.23"), which is what the office
is used to reading.

THE EXTENSION STILL SEES EVERYTHING. It asks for a week and gets that week's
tab; the week picker lists the tabs rather than the distinct values of a
column. `weeks_in` is what it reads.

WHERE THE ID LIVES: the `Onboarding Sheet` column of the `Office Settings`
tab, which already exists for exactly this. One place, so there is no second
list of sheet ids to drift -- the same reason `fillers.workbook_for` resolved
from `office_metrics.offices` rather than keeping its own.

NOTHING HERE DELETES OR MOVES AN EXISTING TAB. A board that is already on an
office's own workbook stays where it is until somebody moves it on purpose:
this creates, finds and reads, and that is all.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

from automations.icd_onboarding import board as B

# "OBCL 11.23" -- the D2D OBCL's own shape, minus the "D2D" that said whose
# it was. Matched loosely enough to survive somebody typing it by hand.
TAB_RE = re.compile(r"^\s*OBCL\s+(\d{1,2})\.(\d{1,2})\s*$", re.I)

#: What a new workbook is called. The owner's name, so it is findable in a
#: Drive full of sheets nobody named.
BOOK_NAME = "LucyECO Onboarding - %s"

SETTINGS_TAB = "Office Settings"
ID_COLUMN = "Onboarding Sheet"


def tab_name(week_start: dt.date) -> str:
    """The tab for a week, named for its MONDAY the way the OBCL names its."""
    monday = week_start - dt.timedelta(days=week_start.weekday())
    return "OBCL %d.%d" % (monday.month, monday.day)


def week_of(title: str, year: int) -> Optional[dt.date]:
    """'OBCL 11.23' -> the Monday it stands for, or None if not one of ours."""
    m = TAB_RE.match(str(title or ""))
    if not m:
        return None
    try:
        return dt.date(year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def weeks_in(titles: List[str], year: int) -> Dict[dt.date, str]:
    """{Monday: tab title} for every week tab. What the picker lists."""
    out: Dict[dt.date, str] = {}
    for t in titles:
        when = week_of(t, year)
        if when:
            out[when] = t
    return out


# ------------------------------------------------------- where the book is

def sheet_id(office_key: str) -> str:
    """That office's own onboarding workbook id, or "" if they have none yet.

    Read from the `Office Settings` tab, never cached: an office enrolled an
    hour ago has to be findable by a run that started before they were.
    """
    from automations.office_admin import sheets as OS
    try:
        row = OS.office_settings(OS.settings_tab(), office_key) or {}
    except Exception:                                   # noqa: BLE001
        return ""
    return str(row.get(ID_COLUMN) or "").strip()


def open_book(office_key: str, owner: str = "", *, create: bool = False):
    """The office's own onboarding workbook.

    `create=False` by default and deliberately: making a Google Sheet is not
    something a read should do by accident, and an office with no book is a
    question for whoever enrolled them, not a thing to paper over.
    """
    from automations.recruiting_report.fill import open_by_key

    sid = sheet_id(office_key)
    if sid:
        return open_by_key(sid)
    if not create:
        return None
    return _make_book(office_key, owner)


def _make_book(office_key: str, owner: str = ""):
    """Create the workbook and record its id, in that order.

    THE ID IS WRITTEN BACK BEFORE ANYTHING IS PUT IN IT. A book created and
    not recorded is a book the next run cannot find, so it makes a second one
    -- and two half-filled onboarding sheets for one office is worse than
    none, because each looks complete on its own.
    """
    from automations.office_admin import sheets as OS
    from automations.recruiting_report.fill import _client

    ws = OS.settings_tab()
    rows = OS.records(OS._retry(ws.get_all_values))
    at = None
    for i, r in enumerate(rows, 2):           # row 1 is the header
        if (r.get("Office Key") or "").strip().lower() == \
                str(office_key).strip().lower():
            at = i
            break
    if at is None:
        raise RuntimeError(
            "office %r has no row on the %r tab, so there is nowhere to "
            "record the workbook id. Enrol them first: a book nobody can "
            "find is a book the next run makes again."
            % (office_key, SETTINGS_TAB))

    title = BOOK_NAME % (owner.strip() or office_key)
    book = _client().create(title)
    OS._set_cells(ws, at, {ID_COLUMN: book.id})
    return book


# ------------------------------------------------------------ the week tab

def open_week(book, week_start: dt.date, *, create: bool = True):
    """This week's tab in that book, laid with the board's headers if new."""
    from automations.icd_onboarding import sheet as S
    from automations.shared import sheets_retry

    want = tab_name(week_start)
    tabs = sheets_retry.call(book.worksheets, tries=6)
    for ws in tabs:
        if ws.title.strip().lower() == want.lower():
            return ws
    if not create:
        return None

    # A NEW WEEK IS A COPY OF THE LAST ONE, not a fresh grid. That is how a
    # metrics sheet is made -- `office_onboarding.schema` copies each tab
    # from the Master Templates workbook rather than writing headers into an
    # empty sheet -- and for the same reason: the formatting, the column
    # widths, the frozen row and anything the office added by hand come with
    # it. A hand-built grid looks subtly different every week, and the office
    # is the one who notices.
    #
    # The previous week IS the template here, so there is no separate asset
    # to keep in step with `board.COLUMNS`. The very first week has nothing
    # to copy and is laid from the columns themselves.
    newest = _newest_week(tabs, week_start.year)
    if newest is not None:
        ws = book.duplicate_sheet(newest.id, new_sheet_name=want)
        _clear_rows(ws)
        return ws

    ws = book.add_worksheet(title=want, rows=200,
                            cols=len(B.COLUMNS) + len(S.PAST_THE_CHART) + 2)
    ws.update(values=[list(B.COLUMNS) + list(S.PAST_THE_CHART)],
              range_name="A1")
    ws.freeze(rows=S.HEADER_ROW)
    return ws


def _newest_week(tabs, year: int):
    """The latest week tab in the book, or None if it has none yet."""
    best, best_when = None, None
    for ws in tabs:
        when = week_of(ws.title, year)
        if when and (best_when is None or when > best_when):
            best, best_when = ws, when
    return best


def _clear_rows(ws) -> None:
    """Everything below the header, so a copied week starts empty.

    The HEADER stays: it is what was being copied for. Cleared rather than
    deleted so the sheet keeps its size and formatting -- deleting the rows
    would take the formatting with them, which is the thing the copy exists
    to carry.
    """
    from automations.icd_onboarding import sheet as S
    last = getattr(ws, "row_count", 0) or 0
    if last > S.HEADER_ROW:
        ws.batch_clear(["A%d:%s%d" % (S.HEADER_ROW + 1,
                                      S._a1(getattr(ws, "col_count", 26) or 26),
                                      last)])

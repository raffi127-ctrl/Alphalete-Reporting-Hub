"""1st to 2nd Below the Mark -- the HR alert tab (Eve, 2026-09-17).

Fills the '1st to 2nd below the mark' tab of the 'ARS Management 2.0' workbook
so HR can see which owners are under the bar on
"Retention first showed up booked second", and -- because it runs twice a day --
whether that number MOVED since the morning.

Two pickers on row 1 drive the whole tab: A1 the week, B1 the day.

WHERE EACH COLUMN COMES FROM
    A  Owner Name      'Interviewers Retention (Interviewer)' col A
                       (headed 'INTERVIEWER'; it holds the OWNER)
    F  Goal            same tab, col 'Goal For 1st to 2nd booked %'
    B  Inteviewer Name the owner's ARS REPORT tab -> QUALIFIED RETENTION block
                       -> the selected week's box -> the selected day -> whoever
                       actually has numbers that day
    G  Qualified       \
    H  Disqualified     >  same box, the day's Q | Di | De | QR | DR cells
    I  Declined        /
    J  Qualified Retention
    K  Declined Retention
    L  Qualified      \
    M  Booked          >  ANSWERED / BOOKED RETENTION block, Q | B | NC | BR | NCR
    N  Not Contacted  /
    O  Booked Retention
    P  Not Contacted Retention
    C  1st interviews showed up     ] ApplicantStream, Reports -> Retention
    D  1st showed up booked 2nd     ] Details, the selected day's column.
    E  Retention first showed up    ] NOT WIRED UP YET -- see APPSTREAM below.
       booked second                ]

APPSTREAM (still to do): automations/recruiting_report/fetch_office.py already
scrapes exactly these three off p=701 per office
('First Interviews Showed Up', 'Total Second Interviews',
 'Retention First Showed Up Booked Second'). What is missing is an office id for
each of the 41 owners -- only 26 of them appear on a Daily Focus tab today, so
15 have no mapping to reuse.

THE TWO WEEK LABELS ARE SEVEN DAYS APART. 'Interviewers Retention (Interviewer)'
names a week by the Sunday that STARTS it (9/13); the ARS REPORT files name the
same week by the Sunday that ENDS it (9/20). ars_reports.ars_week_label converts.

COLOURS ARE THE TAB'S OWN. The purple QUALIFIED RETENTION group, the orange
ANSWERED / BOOKED group and the green retention header are Eve's, and this
report never repaints them: on the first run it copies row 1's formats down to
the new header row and row 2's down to the data rows, and after that every run
tiles the first data row's format over the rest. Change a colour by hand on the
header row or the first data row and the next run spreads it.

Colour rule on 'Retention first showed up booked second':
    <= 40%  red        (red is listed first, so exactly 40% reads red)
    >= 40%  yellow

Run (the default target is the SANDBOX-suffixed tab, which is the live one --
see the note on SANDBOX_TAB):
    python -m automations.first_to_second_below_mark.run
    python -m automations.first_to_second_below_mark.run --week 9/6 --day Tuesday
    python -m automations.first_to_second_below_mark.run --list-weeks
    python -m automations.first_to_second_below_mark.run --dry-run
    python -m automations.first_to_second_below_mark.run --only "Kash Rai"
    python -m automations.first_to_second_below_mark.run --production   # real tab
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

try:                                   # accents are safe on the Windows console
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill
from automations.first_to_second_below_mark import appstream as apst
from automations.first_to_second_below_mark import ars_reports as ars
from automations.first_to_second_below_mark import columns as cols
from automations.first_to_second_below_mark import source as src

SHEET_ID = "1l4Q0SreuddKZrgXwb9MytF-EdPZH-H1hLsa69epq-n8"   # ARS Management 2.0
# The ORIGINAL tab, renamed '(old)' on 2026-09-18 when the two-week board took
# the plain name '1st to 2nd below the mark' (board.BOARD_TAB). It must never
# point at that name again: `--production` here would overwrite the board.
TARGET_TAB = "1st to 2nd below the mark (old)"
# THE LIVE TAB, despite the name. This report is new -- nothing depended on it
# before -- so Eve made the tab that was being built the real one and kept the
# SANDBOX suffix on it until Rafael signs off (2026-09-17). It carries her
# layout: group banners in row 2, her header colours, her column widths.
# When he approves, rename it to TARGET_TAB; the old '1st to 2nd below the mark'
# still holds her original header row and the hand-typed sample row.
SANDBOX_TAB = "1st to 2nd below the mark SANDBOX"

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"

# Row layout. This report owns EXACTLY two rows, the top two: the pickers and
# the status line. Everything below them is the tab's own -- Eve's group banners
# ('QUALIFIED RETENTION' over G-K, 'ANSWERED / BOOKED RETENTION' over L-P), her
# column headers, her colours. The first run INSERTS these two rows rather than
# writing over row 1, so her design slides down untouched and keeps its
# formatting. It cost her that row twice before it worked this way (2026-09-17).
PICKER_ROW = 1
STATUS_ROW = 2
OWN_ROWS = 2                 # how many rows at the top belong to this report
BANNER_TITLE = "1ST TO 2ND BELOW THE MARK"

# Kept so older call sites and tests keep meaning the same thing on a migrated
# tab; run() uses the values it actually finds.
HEADER_ROW = 3
FIRST_DATA_ROW = 4

# The mark. An office at or under this in the day's retention is what the tab
# exists to surface; Eve's colour rule calls exactly 40% red, so the listing
# uses the same boundary.
#
# Column E keeps this flat 40% floor and does NOT use the goal-dependent bands
# from Camila's sheet: those bands are for J, K, O and P, and the floor is what
# Rafael asked for on the headline number (Eve, 2026-09-17).
THRESHOLD = 0.40

# Which columns are percentages and which are counts, by FIELD name so the
# formats follow a column if the tab is ever reordered.
PERCENT_FIELDS = ("retention", "goal", "qualified_ret", "declined_ret",
                  "booked_ret", "not_contacted_ret")
COUNT_FIELDS = ("first_showed", "booked_2nd", "qualified", "disqualified",
                "declined", "ab_qualified", "booked", "not_contacted")

OWNER_HEADER = "Owner Name"
PCT_HEADER = "Retention first showed up booked second"

# Fallback header row, used only if the tab is ever found empty. Verbatim from
# the tab as Eve built it, typos and line breaks included.
DEFAULT_HEADERS = [
    "Owner Name", "Inteviewer Name", "1st interviews showed up",
    "1st showed up booked 2nd", "Retention first showed up booked second",
    "Goal", "Qualified", "Disqualified", "Declined", "Qualified Retention",
    "Declined Retention", "Qualified", "Booked", "Not Contacted",
    "Booked\nRetention", "Not Contacted\nRetention",
    "Office to Fill out report for (MUST MATCH APP STREAM NAME)",
]

# Megan's Daily Focus Report palette, for the two rows this report owns. The
# header row and the data rows keep the tab's OWN colours -- see the docstring.
BANNER_BG = {"red": 0.4, "green": 0.4, "blue": 0.4}
BANNER_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}
STATUS_BG = {"red": 0.937, "green": 0.937, "blue": 0.937}
INPUT_BG = {"red": 1.0, "green": 0.898, "blue": 0.6}      # the cells you type in
# The alert colours. Deliberately vibrant rather than the pale Sheets defaults
# (Eve, 2026-09-17): this tab is scanned quickly and the row has to jump out.
# Red carries white text, yellow keeps black, so both stay readable.
CF_RED = {"red": 0.918, "green": 0.263, "blue": 0.208}      # #EA4335
CF_RED_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}
CF_YELLOW = {"red": 0.984, "green": 0.737, "blue": 0.016}   # #FBBC04
CF_YELLOW_FG = {"red": 0.0, "green": 0.0, "blue": 0.0}
FONT = "Arial"

CT = ZoneInfo("America/Chicago")          # the reports' clock, not the machine's


# --------------------------------------------------------------------- helpers
def _a1col(n: int) -> str:
    return ars.a1col(n)


def _norm(s: str) -> str:
    return src._norm(s)


def find_header_row(values: List[List[str]]) -> Optional[int]:
    """1-indexed row holding the tab's column headers, found by the owner label."""
    want = OWNER_HEADER.lower()
    for i, row in enumerate(values[:20], 1):
        if any(_norm(c).lower() == want for c in row):
            return i
    return None


def is_migrated(values: List[List[str]]) -> bool:
    """True once this report's two rows are in place at the top.

    Detected by the banner this report writes into row 1 every run, plus the
    pickers themselves -- so a tab that still holds only Eve's own layout is
    never mistaken for a migrated one, and a migrated tab is never given a
    second pair of rows."""
    if not values or not values[0]:
        return False
    row1 = [_norm(c) for c in values[0]]
    if any(c.upper() == BANNER_TITLE for c in row1):
        return True
    return bool(row1 and row1[0]) and len(row1) > 1 and row1[1] in ars.DAYS


def selected_week_label(values: List[List[str]], header_row: Optional[int]) -> Optional[str]:
    """Whatever is in A1, so a re-run repaints the week HR picked.

    Only trusted once the tab is in this report's layout (headers on row 3). On
    a tab still in its original shape A1 is the 'Owner Name' header, which is
    not a week -- the first run migrates the layout and defaults to newest."""
    if not is_migrated(values) or not values or not values[0]:
        return None
    return _norm(values[0][0]) or None


def selected_day(values: List[List[str]], header_row: Optional[int]) -> Optional[str]:
    """Whatever is in B1, same rule as the week."""
    if not is_migrated(values) or not values or len(values[0]) < 2:
        return None
    want = _norm(values[0][1]).lower()
    for d in ars.DAYS:
        if d.lower() == want:
            return d
    return None


def default_day(today: Optional[dt.date] = None) -> str:
    """Today, or Friday over the weekend -- these boxes only have Mon-Fri."""
    d = today or dt.datetime.now(dt.timezone.utc).astimezone(CT).date()
    return ars.DAYS[d.weekday()] if d.weekday() < len(ars.DAYS) else ars.DAYS[-1]


def selectable_weeks(weeks: List[src.Week]) -> List[str]:
    """Labels for the A1 dropdown.

    'Goal For 1st to 2nd booked %' was only added to the source tab's weekly box
    on the week of 6/7 -- every block older than that has no goal column at all,
    so offering those weeks would just hand HR a table with an empty Goal
    column. They stay reachable from the command line with --week.
    """
    with_goal = [w.label for w in weeks if any(o.goal is not None for o in w.owners)]
    return with_goal or [w.label for w in weeks]


# ------------------------------------------------------------------- the build
def build_rows(week: src.Week, day: str, headers: List[str], *,
               only: Optional[str] = None, refresh_index: bool = False,
               use_appstream: bool = True, logfn=print) -> tuple:
    """One row per owner. Built in the source tab's order and sorted by run()
    afterwards -- worst retention first.

    Returns (rows, notes) where notes lists the owners whose ARS REPORT tab or
    weekly box could not be found, so the run reports them instead of writing a
    silently blank line."""
    col = cols.resolve(headers)
    gone = cols.missing(col)
    if gone:
        logfn(f"  !! header row is missing: {', '.join(gone)}")

    index = ars._index(logfn=logfn, refresh=refresh_index)
    aliases = ars.load_aliases()
    ars_week = ars.ars_week_label(week.label)
    logfn(f"  ARS REPORT week box: {ars_week}  (retention tab calls it {week.label})")

    wanted_owners = [o.name for o in week.owners
                     if not only or _norm(only).lower() in _norm(o.name).lower()]

    # ApplicantStream first: it is one login for the whole sweep, and columns
    # C/D/E are what the alert actually keys on.
    as_rows: Dict[str, Dict[str, Optional[float]]] = {}
    notes: List[str] = []
    if use_appstream and wanted_owners:
        try:
            as_rows, as_gaps = apst.fetch_days(wanted_owners, week.label, day, logfn=logfn)
            notes.extend(as_gaps)
            logfn(f"  AppStream returned {len(as_rows)} of {len(wanted_owners)} offices")
        except Exception as exc:                          # noqa: BLE001
            # A session that will not open must not take the rest of the tab
            # down with it -- the ARS columns still fill and the run says why
            # C/D/E are blank.
            notes.append(f"AppStream unavailable: {type(exc).__name__}: {exc}")
            logfn(f"  !! AppStream unavailable ({type(exc).__name__}: {exc}); "
                  "C/D/E will be blank this run")
    elif not use_appstream:
        logfn("  --no-appstream: C/D/E left blank")

    books: Dict[str, object] = {}
    rows = []
    for owner in week.owners:
        if only and _norm(only).lower() not in _norm(owner.name).lower():
            continue
        row = [""] * len(headers)
        if "owner" in col:
            row[col["owner"]] = owner.name
        if "goal" in col and owner.goal is not None:
            row[col["goal"]] = owner.goal          # a number, not '50%' text

        def put(field, value):
            if field in col and value is not None:
                row[col[field]] = value

        for field, value in (as_rows.get(owner.name) or {}).items():
            put(field, value)

        hit = ars.find_tab(owner.name, index, aliases)
        if hit is None:
            notes.append(f"{owner.name}: no ARS REPORT tab")
            rows.append(row)
            continue
        workbook, tab = hit
        try:
            if workbook not in books:
                books[workbook] = fill.open_by_key(ars.ARS_WORKBOOKS[workbook])
            day_data = ars.read_owner_day(books[workbook], tab, owner.name,
                                          workbook, ars_week, day)
        except LookupError as exc:
            notes.append(str(exc))
            rows.append(row)
            continue

        put("interviewer", day_data.interviewer_label or None)
        put("qualified", day_data.qualified)
        put("disqualified", day_data.disqualified)
        put("declined", day_data.declined)
        put("qualified_ret", day_data.qualified_ret)
        put("declined_ret", day_data.declined_ret)
        put("ab_qualified", day_data.ab_qualified)
        put("booked", day_data.booked)
        put("not_contacted", day_data.not_contacted)
        put("booked_ret", day_data.booked_ret)
        put("not_contacted_ret", day_data.not_contacted_ret)
        rows.append(row)
    return rows, notes


def worst_first(rows: List[List], headers: List[str]) -> List[List]:
    """Lowest retention at the top, so the office HR has to look at first is the
    first line on the tab (Eve, 2026-09-17).

    Rows without a retention number sort to the bottom rather than to 0%: no
    reading is not the same as a bad reading, and they must not push a real
    alert down the list."""
    col = cols.resolve(headers)
    pct_i = col.get("retention")
    owner_i = col.get("owner", 0)
    if pct_i is None:
        return rows

    def key(row):
        pct = row[pct_i] if pct_i < len(row) else None
        name = str(row[owner_i]) if owner_i < len(row) else ""
        if isinstance(pct, (int, float)):
            return (0, pct, name.lower())
        return (1, 0.0, name.lower())      # no number: last, then alphabetical
    return sorted(rows, key=key)


def below_the_mark(rows: List[List], headers: List[str],
                   threshold: float = THRESHOLD) -> List[List]:
    """Only the offices at or under the mark -- the tab is an ALERT, not a roster.

    An office with no interviews that day is left off rather than shown at 0%:
    its retention is undefined, not bad, and flagging it would bury the offices
    that really are under the bar."""
    col = cols.resolve(headers)
    pct_i, shown_i = col.get("retention"), col.get("first_showed")
    if pct_i is None:
        return rows
    keep = []
    for row in rows:
        shown = row[shown_i] if shown_i is not None and shown_i < len(row) else None
        pct = row[pct_i] if pct_i < len(row) else None
        if not isinstance(shown, (int, float)) or not shown:
            continue                       # no interviews that day: nothing to judge
        if isinstance(pct, (int, float)) and pct <= threshold:
            keep.append(row)
    return keep


def _fmt_requests(sid: int, headers: List[str], n_rows: int, week_labels: List[str],
                  *, first_data_row: int = FIRST_DATA_ROW,
                  clear_to_row: Optional[int] = None) -> List[dict]:
    """Rows 1 and 2 are this report's. Everything from the header row down keeps
    the tab's own formatting: the header row is never restyled, and the data
    rows are tiled from the first one so a colour changed there spreads."""
    ncols = len(headers)
    last_row = first_data_row - 1 + max(n_rows, 1)
    reqs: List[dict] = []

    def rng(r0, r1, c0, c1):
        return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def copy_format(src_rng, dst_rng):
        return {"copyPaste": {"source": src_rng, "destination": dst_rng,
                              "pasteType": "PASTE_FORMAT"}}

    # NOTHING is copied down on a first run any more. The old version pasted row
    # 1's formats onto the new header row, which meant this report decided what
    # the header looked like. Inserting rows carries every format down with the
    # cells, so the tab keeps its own.

    # Row 1 -- the two pickers and the banner.
    picker = {"backgroundColor": INPUT_BG, "horizontalAlignment": "CENTER",
              "verticalAlignment": "MIDDLE",
              "borders": {s: {"style": "SOLID_THICK"}
                          for s in ("top", "bottom", "left", "right")},
              "textFormat": {"fontFamily": FONT, "fontSize": 12, "bold": True}}
    reqs.append({"repeatCell": {"range": rng(0, 1, 0, 2),
                                "cell": {"userEnteredFormat": picker},
                                "fields": "userEnteredFormat(backgroundColor,"
                                          "horizontalAlignment,verticalAlignment,"
                                          "borders,textFormat)"}})
    # The title styles ONLY C1. Row 1 past that column is not touched: Eve puts
    # her group banners there ('QUALIFIED RETENTION', 'ANSWERED / BOOKED
    # RETENTION') and a band across the whole row would erase them.
    reqs.append({"repeatCell": {"range": rng(0, 1, 2, 3), "cell": {"userEnteredFormat": {
        "backgroundColor": BANNER_BG, "horizontalAlignment": "LEFT",
        "verticalAlignment": "MIDDLE", "wrapStrategy": "OVERFLOW_CELL",
        "textFormat": {"fontFamily": FONT, "fontSize": 14, "bold": True,
                       "foregroundColor": BANNER_FG}}},
        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                  "verticalAlignment,wrapStrategy,textFormat)"}})

    # Row 2 -- the status line, styled on A2 ALONE. The text overflows right
    # across the empty cells on its own; painting the whole row erased the group
    # banners Eve keeps in G2 and L2.
    reqs.append({"repeatCell": {"range": rng(STATUS_ROW - 1, STATUS_ROW, 0, 1),
        "cell": {"userEnteredFormat": {
            "backgroundColor": STATUS_BG, "horizontalAlignment": "LEFT",
            "wrapStrategy": "OVERFLOW_CELL",
            "textFormat": {"fontFamily": FONT, "fontSize": 10, "italic": True,
                           "bold": False}}},
        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                  "wrapStrategy,textFormat)"}})

    # Data rows -- tile the FIRST data row's formatting over the rest, so the
    # tab's colours and number formats spread instead of being overwritten.
    if last_row > first_data_row:
        reqs.append(copy_format(rng(first_data_row - 1, first_data_row, 0, ncols),
                                rng(first_data_row, last_row, 0, ncols)))

    # Wipe the FORMATTING below the data too, not just the values. A shorter
    # fill left the purple / orange / green bands running on down the tab to
    # wherever the longest previous fill reached, so the table looked like it
    # still had 30 empty offices under it (Eve, 2026-09-17). Clearing the whole
    # userEnteredFormat returns those rows to a plain sheet.
    if clear_to_row and clear_to_row > last_row:
        reqs.append({"repeatCell": {
            "range": rng(last_row, clear_to_row, 0, ncols),
            "cell": {"userEnteredFormat": {}},
            "fields": "userEnteredFormat"}})

    # Number formats, set explicitly and by FIELD, never by colour: the template
    # row Eve left behind has no format on Goal, so an inherited 0.5 rendered as
    # "0.5" instead of "50%". This touches numberFormat only -- the backgrounds
    # above stay the tab's own.
    col = cols.resolve(headers)
    for field in PERCENT_FIELDS:
        i = col.get(field)
        if i is not None:
            reqs.append({"repeatCell": {
                "range": rng(first_data_row - 1, last_row, i, i + 1),
                "cell": {"userEnteredFormat": {
                    "numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                "fields": "userEnteredFormat.numberFormat"}})
    for field in COUNT_FIELDS:
        i = col.get(field)
        if i is not None:
            reqs.append({"repeatCell": {
                "range": rng(first_data_row - 1, last_row, i, i + 1),
                "cell": {"userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": "0"}}},
                "fields": "userEnteredFormat.numberFormat"}})

    # The two dropdowns.
    reqs.append({"setDataValidation": {"range": rng(0, 1, 0, 1), "rule": {
        "condition": {"type": "ONE_OF_LIST",
                      "values": [{"userEnteredValue": w} for w in week_labels[:500]]},
        "showCustomUi": True, "strict": False,
        "inputMessage": "Week. Pick one, then re-run the report to repaint the tab."}}})
    reqs.append({"setDataValidation": {"range": rng(0, 1, 1, 2), "rule": {
        "condition": {"type": "ONE_OF_LIST",
                      "values": [{"userEnteredValue": d} for d in ars.DAYS]},
        "showCustomUi": True, "strict": False,
        "inputMessage": "Day. Pick one, then re-run the report to repaint the tab."}}})

    # Column widths: names need room, the metric columns do not.
    # Only row 1's height, because row 1 is ours. Column widths are the tab's
    # own too -- this report used to set them and that is how C/D/E ended up
    # re-sized under someone else's header.
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 44}, "fields": "pixelSize"}})

    # Freeze down to the header row so the list scrolls under it.
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid,
                       "gridProperties": {"frozenRowCount": first_data_row - 1}},
        "fields": "gridProperties.frozenRowCount"}})
    return reqs


# The colour bands from Camila's "Qualify Color Goals" sheet. They depend on the
# OFFICE'S OWN GOAL -- an office on a 50% goal and one on 60% are judged
# differently -- so every rule is a custom formula that reads the Goal column on
# the same row rather than a flat number.
#
#   Qualify % (column J)          50% goal        60% goal
#     green                       60 - 70%        65 - 80%
#     grey                        55 - 59.9%      60 - 64.9%
#     red                         <=54.9% or >70% <=59.9% or >80%
#
#   Answer/book ratio (cols O, P) green 80%+, grey 75-79.9%, red <=74.9%
#
# Column P (Not Contacted Retention) gets that same band because Rafael's own
# ARS REPORT (5) workbook already applies it to the matching NCR columns -- the
# rule there spans BG:BN, which covers AR, BR and NCR (Eve, 2026-09-17). Note
# what that means in practice: every office sits at 0% Not Contacted today, and
# 0% is below 74.9%, so P reads red across the board.
#
# Red at BOTH ends on qualify is deliberate: over-qualifying just pushes the bad
# candidates into the second round and sinks that retention instead.
CF_GREEN = {"red": 0.576, "green": 0.769, "blue": 0.490}     # the tab's own green
CF_GREY = {"red": 0.718, "green": 0.718, "blue": 0.718}
CF_DARK_FG = {"red": 0.0, "green": 0.0, "blue": 0.0}

# Goals only ever read 50% or 60%, so the two bands are told apart by a midpoint
# rather than by equality -- 0.6 is not exactly representable as a float and
# `=0.6` in a formula is a coin toss.
GOAL_LOW = "<0.55"          # the 50% offices
GOAL_HIGH = ">=0.55"        # the 60% offices


def _qualify_rules(cell: str, goal: str, present: Optional[str] = None) -> List[tuple]:
    """Green / grey / red for a qualify-% column, as (formula, bg, fg).

    `present` is the cell to test for emptiness, which is not always `cell`:
    Declined Retention is judged through `(1-K4)`, and `(1-K4)<>""` is true even
    on a blank row, which would paint every empty row red."""
    green = (f'OR(AND({goal}{GOAL_LOW},{cell}>=0.6,{cell}<=0.7),'
             f'AND({goal}{GOAL_HIGH},{cell}>=0.65,{cell}<=0.8))')
    grey = (f'OR(AND({goal}{GOAL_LOW},{cell}>=0.55,{cell}<0.6),'
            f'AND({goal}{GOAL_HIGH},{cell}>=0.6,{cell}<0.65))')
    # Red is "has a value and is in neither band", so nothing can fall through
    # uncoloured and quietly look fine.
    in_band = (f'OR(AND({goal}{GOAL_LOW},{cell}>=0.55,{cell}<=0.7),'
               f'AND({goal}{GOAL_HIGH},{cell}>=0.6,{cell}<=0.8))')
    red = f'AND({present or cell}<>"",NOT({in_band}))'
    return [(f"={green}", CF_GREEN, CF_DARK_FG),
            (f"={grey}", CF_GREY, CF_DARK_FG),
            (f"={red}", CF_RED, CF_RED_FG)]


def _answer_book_rules(cell: str) -> List[tuple]:
    """Green / grey / red for the answer-to-book ratio. No goal dependency."""
    return [(f"={cell}>=0.8", CF_GREEN, CF_DARK_FG),
            (f"=AND({cell}>=0.75,{cell}<0.8)", CF_GREY, CF_DARK_FG),
            (f'=AND({cell}<>"",{cell}<0.75)', CF_RED, CF_RED_FG)]


def _alert_rules(cell: str) -> List[tuple]:
    """The retention column: <=40% red, >=40% yellow. Red is listed first, so a
    cell sitting exactly on 40% takes the red -- the 'below the mark' side."""
    return [(f'=AND({cell}<>"",{cell}<=0.4)', CF_RED, CF_RED_FG),
            (f"={cell}>=0.4", CF_YELLOW, CF_YELLOW_FG)]


def cf_plan(headers: List[str], first_data_row: int) -> List[tuple]:
    """[(column index, [(formula, bg, fg), ...]), ...] for every coloured column."""
    col = cols.resolve(headers)
    goal_i = col.get("goal")
    if goal_i is None:
        return []
    goal = f"${_a1col(goal_i + 1)}{first_data_row}"

    def at(field):
        i = col.get(field)
        return i, (f"{_a1col(i + 1)}{first_data_row}" if i is not None else None)

    plan = []
    for field, build in (("retention", _alert_rules),
                         ("qualified_ret", None),
                         ("declined_ret", None),
                         ("booked_ret", _answer_book_rules),
                         ("not_contacted_ret", _answer_book_rules)):
        i, cell = at(field)
        if i is None:
            continue
        if field == "qualified_ret":
            plan.append((i, _qualify_rules(cell, goal)))
        elif field == "declined_ret":
            # Declined Retention is exactly 1 - Qualified Retention (the three
            # counts behind them add up to the day's interviews), so it is
            # judged on the same band, read through its complement. Colouring it
            # on its own numbers would need a second set of thresholds nobody
            # has written down.
            plan.append((i, _qualify_rules(f"(1-{cell})", goal, present=cell)))
        else:
            plan.append((i, build(cell)))
    return plan


def _cf_requests(sid: int, existing: List[dict], headers: List[str],
                 n_rows: int, *, first_data_row: int = FIRST_DATA_ROW) -> List[dict]:
    """Rebuild this report's conditional formatting.

    Only rules that live entirely inside one of OUR columns are dropped first:
    any other conditional formatting on this tab belongs to someone else and is
    left alone."""
    plan = cf_plan(headers, first_data_row)
    if not plan:
        return []
    mine = {i for i, _ in plan}
    drop = []
    for idx, rule in enumerate(existing):
        ranges = rule.get("ranges", [])
        if ranges and all(r.get("endColumnIndex", 0) - r.get("startColumnIndex", 0) == 1
                          and r.get("startColumnIndex") in mine for r in ranges):
            drop.append(idx)
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
            for i in sorted(drop, reverse=True)]

    last_row = first_data_row - 1 + max(n_rows, 1)
    index = 0
    for column, rules in plan:
        rng = {"sheetId": sid, "startRowIndex": first_data_row - 1,
               "endRowIndex": last_row,
               "startColumnIndex": column, "endColumnIndex": column + 1}
        for formula, bg, fg in rules:
            reqs.append({"addConditionalFormatRule": {"index": index, "rule": {
                "ranges": [rng],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue": formula}]},
                    "format": {"backgroundColor": bg,
                               "textFormat": {"bold": True,
                                              "foregroundColor": fg}}}}}})
            index += 1
    return reqs


# --------------------------------------------------------------------- the run
def run(*, week_label: Optional[str] = None, day: Optional[str] = None,
        production: bool = False, dry_run: bool = False,
        only: Optional[str] = None, refresh_index: bool = False,
        show_all: bool = False, use_appstream: bool = True,
        tab: Optional[str] = None, now: bool = False, logfn=print) -> dict:
    sh = fill.open_by_key(SHEET_ID)
    tab = tab or (TARGET_TAB if production else SANDBOX_TAB)
    ws = fill.worksheet_ci(sh, tab)
    target = ws.get_all_values()

    # First run on this tab: push everything down by two rows and take only the
    # two rows that opened up. insertDimension moves Eve's banners, headers,
    # colours and column widths down with the cells -- nothing is rewritten, so
    # nothing can be lost. Every later run finds the tab already migrated and
    # writes only rows 1-2 and the data block.
    migrating = not is_migrated(target)
    if migrating and not dry_run:
        sh.batch_update({"requests": [{"insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": 0, "endIndex": OWN_ROWS},
            "inheritFromBefore": False}}]})
        target = [[""], [""]] + target
        logfn(f"  inserted {OWN_ROWS} rows at the top; the tab's own layout "
              "moved down untouched")
    elif migrating:
        target = [[""], [""]] + target

    hrow = find_header_row(target)
    if hrow is None:
        raise SystemExit(
            f"{tab!r}: no {OWNER_HEADER!r} header found in the first 20 rows. "
            "Nothing was written -- this report never guesses where the table is.")
    if hrow <= OWN_ROWS:
        raise SystemExit(
            f"{tab!r}: the header row is at {hrow}, inside the two rows this "
            "report owns. Nothing was written.")
    first_data_row = hrow + 1

    sws = fill.worksheet_ci(sh, src.SOURCE_TAB)
    weeks = src.parse_blocks(sws.get_all_values())
    logfn(f"  source: {src.SOURCE_TAB!r} -> {len(weeks)} weekly blocks "
          f"({weeks[0].label} .. {weeks[-1].label})")

    # Which week / day: the flags win, else whatever the pickers hold, else the
    # current week and today.
    #
    # --now IGNORES the pickers, and the two scheduled runs use it. Without it a
    # look-back would stick: someone sets B1 to Monday to check a past day, and
    # every run from then on keeps refilling Monday, so the tab quietly stops
    # being about today while still looking live.
    if now:
        wanted = f"{apst.current_week_start():%-m/%-d}" if os.name != "nt" else                  "{d.month}/{d.day}".format(d=apst.current_week_start())
        the_day = default_day()
        logfn(f"  --now: ignoring the pickers, using {wanted} / {the_day}")
    else:
        wanted = week_label or selected_week_label(target, hrow)
        the_day = day or selected_day(target, hrow) or default_day()
    week = src.pick_week(weeks, wanted)
    if the_day not in ars.DAYS:
        raise SystemExit(f"day {the_day!r} is not one of {', '.join(ars.DAYS)}")
    logfn(f"  week:   {week.label} ({'picked' if wanted else 'newest'})"
          f"   day: {the_day} ({'picked' if (day or selected_day(target, hrow)) else 'today'})")

    headers = list(target[hrow - 1]) if hrow else []
    while headers and not _norm(headers[-1]):
        headers.pop()
    if not headers:
        headers = list(DEFAULT_HEADERS)
    # Self-heal a truncated header row. get_all_values drops trailing empty
    # columns, so a run whose last column happened to be blank everywhere can
    # read back one header short and then write that shorter row -- losing the
    # column for good. If what we read is a strict prefix of the known header
    # row, put the tail back.
    if len(headers) < len(DEFAULT_HEADERS):
        known = [_norm(h).lower() for h in DEFAULT_HEADERS]
        if [_norm(h).lower() for h in headers] == known[:len(headers)]:
            logfn(f"  header row was {len(headers)} wide, restoring "
                  f"{len(DEFAULT_HEADERS) - len(headers)} trailing column(s)")
            headers = headers + list(DEFAULT_HEADERS[len(headers):])
    ncols = len(headers)

    if only:
        # A one-owner run builds one row, and writing it would clear every other
        # owner off the tab. Preview only -- the repair for one owner is a full run.
        dry_run = True
        logfn(f"  --only {only!r}: preview, nothing will be written")
    rows, notes = build_rows(week, the_day, headers, only=only,
                             refresh_index=refresh_index,
                             use_appstream=use_appstream, logfn=logfn)
    int_i = cols.resolve(headers).get("interviewer", 1)
    filled = sum(1 for r in rows if int_i < len(r) and _norm(str(r[int_i])))
    scanned = len(rows)
    if not show_all:
        rows = below_the_mark(rows, headers)
    rows = worst_first(rows, headers)
    logfn(f"  scanned {scanned} owners, {filled} with ARS numbers, {len(notes)} gaps"
          + ("" if show_all else
             f"  ->  {len(rows)} at or under {THRESHOLD:.0%}"))
    for n in notes:
        logfn(f"    - {n}")

    stamp = dt.datetime.now(dt.timezone.utc).astimezone(CT).strftime("%Y-%m-%d %H:%M CT")
    headline = ("every office" if show_all
                else f"offices at or under {THRESHOLD:.0%}")
    status = (f"{the_day} of the week of {week.label}  ·  {headline}: "
              f"{len(rows)} of {scanned}  ·  ARS REPORT box "
              f"{ars.ars_week_label(week.label)}  ·  filled {stamp}")

    if dry_run:
        logfn("  DRY RUN - nothing written. First rows:")
        for r in rows[:5]:
            logfn("    " + " | ".join(str(c) for c in r[:9]))
        return {"week": week.label, "day": the_day, "owners": len(rows),
                "notes": notes, "written": False}

    # Values: the two rows this report owns, then the data block. The header row
    # is NOT rewritten -- it is Eve's, and so is everything between it and row 2.
    #
    # How far down to clear is decided by a FRESH read of the owner column, not
    # by the snapshot taken at the top of the run. The AppStream sweep takes
    # minutes, and sizing the wipe off a stale read left 21 owners from the
    # previous fill sitting under a shorter one (2026-09-17).
    owner_col = _a1col(cols.resolve(headers).get("owner", 0) + 1)
    below = ws.get(f"{owner_col}{first_data_row}:{owner_col}{first_data_row + 999}")
    last_used = first_data_row - 1
    for i, cell in enumerate(below or []):
        if cell and _norm(cell[0] if cell else ""):
            last_used = first_data_row + i
    blank_below = max(0, last_used - (first_data_row - 1 + len(rows)))
    # Only the three cells this report fills; the rest of row 1 is left alone so
    # a group banner typed up there survives.
    picker = [[week.label, the_day, BANNER_TITLE]]
    data = [
        {"range": f"{tab}!A{PICKER_ROW}:C{PICKER_ROW}", "values": picker},
        # Only A2. Row 2 past column A is Eve's too: she puts the group banners
        # there ('QUALIFIED RETENTION' in G2, 'ANSWERED / BOOKED RETENTION' in
        # L2) and a full-width status row blanked them.
        {"range": f"{tab}!A{STATUS_ROW}", "values": [[status]]},
    ]
    if rows:
        last = first_data_row - 1 + len(rows)
        data.append({"range": f"{tab}!A{first_data_row}:{_a1col(ncols)}{last}",
                     "values": rows})
    if blank_below:
        start = first_data_row + len(rows)
        data.append({"range": f"{tab}!A{start}:{_a1col(ncols)}{start + blank_below - 1}",
                     "values": [[""] * ncols for _ in range(blank_below)]})
    # RAW, not USER_ENTERED: a week label like '9/13' typed as USER_ENTERED is
    # parsed into a DATE serial, and the A1 picker then holds a date while the
    # dropdown offers strings. RAW keeps the label literal; the numbers we write
    # are already floats and the percent display comes from the tab's own number
    # format, which the template row carries.
    sh.values_batch_update({"valueInputOption": "RAW", "data": data})

    meta = sh.fetch_sheet_metadata()
    existing_cf: List[dict] = []
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == ws.id:
            existing_cf = s.get("conditionalFormats", [])
    # How far down to strip old formatting: past whatever the last fill reached,
    # with headroom for a fill that was longer still.
    clear_to = max(last_used, first_data_row - 1 + len(rows)) + 60
    reqs = _fmt_requests(ws.id, headers, len(rows), selectable_weeks(weeks),
                         first_data_row=first_data_row, clear_to_row=clear_to)
    reqs += _cf_requests(ws.id, existing_cf, headers, len(rows),
                         first_data_row=first_data_row)
    sh.batch_update({"requests": reqs})

    logfn(f"  wrote {len(rows)} owner rows to {tab!r} at row {first_data_row} "
          f"(cleared {blank_below} stale rows below"
          + (", inserted the two control rows" if migrating else "") + ")")
    return {"week": week.label, "day": the_day, "listed": len(rows),
            "scanned": scanned, "notes": notes, "written": True, "tab": tab}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="first_to_second_below_mark")
    ap.add_argument("--week", default=None,
                    help="week label as the retention tab writes it, e.g. 9/13. "
                         "Default: cell A1, else the newest week.")
    ap.add_argument("--day", default=None, choices=ars.DAYS + [d.lower() for d in ars.DAYS],
                    help="Default: cell B1, else today (Friday over the weekend).")
    ap.add_argument("--only", default=None,
                    help="preview ONE owner and write nothing. It never writes: "
                         "a one-owner write would blank the other 40 rows, and "
                         "repairing a single owner is just a full re-run.")
    ap.add_argument("--now", action="store_true",
                    help="ignore the A1/B1 pickers and use the current week and "
                         "today. What the two scheduled runs pass, so a look-back "
                         "left in the pickers cannot freeze the tab on an old day.")
    ap.add_argument("--tab", default=None,
                    help="write this tab instead of the sandbox (for trying a "
                         "layout change on a scratch copy)")
    ap.add_argument("--no-appstream", dest="use_appstream", action="store_false",
                    help="skip the ApplicantStream pull and leave C/D/E blank "
                         "(for working on the rest without a browser session)")
    ap.add_argument("--all", dest="show_all", action="store_true",
                    help="list every office instead of only those at or under "
                         f"{THRESHOLD:.0%} -- for checking the numbers")
    ap.add_argument("--refresh-index", action="store_true",
                    help="re-scan the six ARS REPORT workbooks for owner tabs "
                         "(do this after someone adds or renames one)")
    ap.add_argument("--production", action="store_true",
                    help="write the real tab instead of the sandbox copy")
    ap.add_argument("--dry-run", action="store_true", help="read and report, write nothing")
    ap.add_argument("--list-weeks", action="store_true",
                    help="print the weeks on the source tab")
    args = ap.parse_args(argv)

    if args.list_weeks:
        sh = fill.open_by_key(SHEET_ID)
        weeks = src.parse_blocks(fill.worksheet_ci(sh, src.SOURCE_TAB).get_all_values())
        for w in weeks:
            print(f"  {w.label:<10} -> ARS box {ars.ars_week_label(w.label):<7} "
                  f"row {w.header_row:<5} owners {len(w.owners)}")
        return 0

    day = args.day.title() if args.day else None
    res = run(week_label=args.week, day=day, production=args.production,
              dry_run=args.dry_run, only=args.only,
              refresh_index=args.refresh_index, show_all=args.show_all,
              use_appstream=args.use_appstream, tab=args.tab, now=args.now)
    print(f"OK - {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

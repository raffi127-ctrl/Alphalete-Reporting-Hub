"""1st to 2nd Below the Mark -- the two-week board (Rafael, 2026-09-18).

Rafael's ask, after the single-day tab went live: lay it out like the Daily
Focus Report -- THIS week on the left, LAST week on the right, Monday to Friday
down the page -- so there is a record of who was under the bar on each day of
both weeks. Each day lists different people, because a different office slips
under 40% on a different day.

    row 1   THIS WEEK (week of 9/13)          |   LAST WEEK (week of 9/6)
    row 2   status: what this is, when it was last checked, what moved
    row 3   the tab's group banners           |   the same, again
    row 4   the tab's column headers          |   the same, again
            MONDAY 9/14 . 3 of 29 ...         |   MONDAY 9/7 . 2 of 31 ...
            <offices at or under 40%>         |   <offices at or under 40%>
            TUESDAY 9/15 ...                  |   TUESDAY 9/8 ...
            ...

Monday on the left sits on the same row as Monday on the right, so the two
weeks read across.

EVERY DAY IS RE-CHECKED ON EVERY RUN. An applicant the recruiter called on
Thursday can call back and book on Friday, which moves THURSDAY's number after
Thursday is over. So each run pulls all five days of both weeks fresh from
AppStream and the ARS REPORT files -- nothing is carried over from the last
fill. When a number did move, the board says so:
    - a note on the retention cell: "Was 33% at the Thu 9/17 18:30 check"
    - a note on the owner cell for an office that is NEW on a day's list
    - the day's band names anyone who climbed back ABOVE 40% and so dropped off
    - the status line counts how many moved
The "last check" is read back off this tab itself before it is rewritten, so it
works the same from the mini or from Windows -- there is no state file.

WHERE THE LOOK COMES FROM. This tab is generated end to end and is rebuilt on
every run -- do not format it by hand, it will not survive. Its look is copied
from the live single-day tab (rep.SANDBOX_TAB): the group banner row, the header
row, the first data row's colours, and the column widths. Restyle THAT tab and
the next board run picks it up. The live tab itself is only read, never written.

Run:
    python -m automations.first_to_second_below_mark.board --dry-run
    python -m automations.first_to_second_below_mark.board             # writes the PREVIEW tab
    python -m automations.first_to_second_below_mark.board --all       # every office, for checking
    python -m automations.first_to_second_below_mark.board --week 9/13 # which week is "this week"
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill
from automations.first_to_second_below_mark import appstream as apst
from automations.first_to_second_below_mark import ars_reports as ars
from automations.first_to_second_below_mark import columns as cols
from automations.first_to_second_below_mark import run as rep
from automations.first_to_second_below_mark import source as src

# Kept apart from the live tab until Rafael and Eve sign off on the look.
BOARD_TAB = "1st to 2nd below the mark PREVIEW"
TEMPLATE_TAB = rep.SANDBOX_TAB           # the live tab: read for its look only

TITLE_ROW, STATUS_ROW, BANNER_ROW, HEADER_ROW = 1, 2, 3, 4
FIRST_BODY_ROW = 5
GAP_COLS = 1                              # blank column between the two weeks

DAY_BG = {"red": 0.263, "green": 0.263, "blue": 0.263}
WEEK_BG = {"red": 0.4, "green": 0.4, "blue": 0.4}
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
MUTED = {"red": 0.4, "green": 0.4, "blue": 0.4}


# ------------------------------------------------------------------ the dates
def week_label(d: dt.date) -> str:
    return f"{d.month}/{d.day}"


def this_week_start(today: dt.date) -> dt.date:
    """The Sunday that starts the week the board calls THIS week.

    On a Sunday the new week has no weekday in it yet, so the board keeps the
    week that just ended on the left rather than showing five empty days."""
    if today.weekday() == 6:
        today -= dt.timedelta(days=1)
    return apst.current_week_start(today)


def day_date(week_start: dt.date, day: str) -> dt.date:
    return week_start + dt.timedelta(days=ars.DAYS.index(day) + 1)


# ----------------------------------------------------------- one day's result
@dataclass
class DayResult:
    day: str
    date: dt.date
    rows: List[list] = field(default_factory=list)       # listed, worst first
    all_rows: List[list] = field(default_factory=list)   # every office, unfiltered
    interviewed: int = 0                                 # offices with interviews
    future: bool = False
    risen: List[str] = field(default_factory=list)       # climbed back above the mark


@dataclass
class WeekResult:
    label: str
    start: dt.date
    days: Dict[str, DayResult] = field(default_factory=dict)
    missing: Optional[str] = None                        # why the week is blank


# ----------------------------------------------------------------- the pull
def _assemble(owner: src.Owner, headers: List[str], as_row: Optional[dict],
              day_data: Optional[ars.OwnerDay]) -> list:
    col = cols.resolve(headers)
    row = [""] * len(headers)

    def put(fld, value):
        if fld in col and value is not None:
            row[col[fld]] = value

    put("owner", owner.name)
    put("goal", owner.goal)
    for fld, value in (as_row or {}).items():
        put(fld, value)
    if day_data is not None:
        put("interviewer", day_data.interviewer_label or None)
        for fld in ("qualified", "disqualified", "declined", "qualified_ret",
                    "declined_ret", "ab_qualified", "booked", "not_contacted",
                    "booked_ret", "not_contacted_ret"):
            put(fld, getattr(day_data, fld))
    return row


def pull(weeks: List[src.Week], starts: List[dt.date], headers: List[str], *,
         today: dt.date, use_appstream: bool = True, show_all: bool = False,
         refresh_index: bool = False, logfn=print) -> Tuple[List[WeekResult], List[str]]:
    """Every day of every week, from scratch."""
    notes: List[str] = []
    labels = [w.label for w in weeks]

    owner_weeks: Dict[str, List[str]] = {}
    for w in weeks:
        for o in w.owners:
            owner_weeks.setdefault(o.name, []).append(w.label)

    as_data: Dict[str, Dict[str, Dict[str, dict]]] = {}
    if use_appstream and owner_weeks:
        try:
            as_data, gaps = apst.fetch_weeks(owner_weeks, logfn=logfn)
            notes.extend(gaps)
        except Exception as exc:                          # noqa: BLE001
            notes.append(f"AppStream unavailable: {type(exc).__name__}: {exc}")
            logfn(f"  !! AppStream unavailable ({type(exc).__name__}: {exc})")
    elif not use_appstream:
        logfn("  --no-appstream: C/D/E left blank")

    # ARS REPORT: one read per owner covers both weeks and all five days.
    index = ars._index(logfn=logfn, refresh=refresh_index)
    aliases = ars.load_aliases()
    to_ars = {lab: ars.ars_week_label(lab, year_hint=s.year) for lab, s in zip(labels, starts)}
    ars_data: Dict[Tuple[str, str], Dict[str, ars.OwnerDay]] = {}
    books: Dict[str, object] = {}
    tabs: Dict[str, Dict[str, object]] = {}      # workbook -> {tab title: worksheet}
    for owner, wks in owner_weeks.items():
        hit = ars.find_tab(owner, index, aliases)
        if hit is None:
            notes.append(f"{owner}: no ARS REPORT tab")
            continue
        workbook, tab = hit
        try:
            if workbook not in books:
                books[workbook] = fill.open_by_key(ars.ARS_WORKBOOKS[workbook])
                tabs[workbook] = {w.title.strip().lower(): w
                                  for w in books[workbook].worksheets()}
            got = ars.read_owner_weeks(books[workbook], tab, owner, workbook,
                                       [to_ars[w] for w in wks],
                                       ws=tabs[workbook].get(tab.strip().lower()))
        except LookupError as exc:
            notes.append(str(exc))
            continue
        for w in wks:
            if to_ars[w] in got:
                ars_data[(owner, w)] = got[to_ars[w]]
            else:
                notes.append(f"{owner}: no {to_ars[w]} box in {tab!r}")

    results = []
    col = cols.resolve(headers)
    shown_i = col.get("first_showed")
    for w, start in zip(weeks, starts):
        wr = WeekResult(label=w.label, start=start)
        for day in ars.DAYS:
            d = day_date(start, day)
            dr = DayResult(day=day, date=d, future=d > today)
            if not dr.future:
                for o in w.owners:
                    as_row = ((as_data.get(w.label) or {}).get(day) or {}).get(o.name)
                    ars_day = (ars_data.get((o.name, w.label)) or {}).get(day)
                    dr.all_rows.append(_assemble(o, headers, as_row, ars_day))
                dr.interviewed = sum(
                    1 for r in dr.all_rows
                    if shown_i is not None and isinstance(r[shown_i], (int, float)) and r[shown_i])
                listed = dr.all_rows if show_all else rep.below_the_mark(dr.all_rows, headers)
                dr.rows = rep.worst_first(listed, headers)
            wr.days[day] = dr
        results.append(wr)
    return results, notes


# ------------------------------------------------------- what the last fill said
@dataclass
class PriorFill:
    stamp: str = ""                                     # 'Thu 9/17 18:30'
    # (week label, day) -> {owner: retention} for the offices that were listed
    listed: Dict[Tuple[str, str], Dict[str, Optional[float]]] = field(default_factory=dict)


_STAMP_RE = re.compile(r"checked (\w{3} \d{1,2}/\d{1,2} \d{1,2}:\d{2})")
_WEEK_RE = re.compile(r"week of (\d{1,2}/\d{1,2})", re.I)


def read_prior(values: List[List], width: int, headers: List[str]) -> PriorFill:
    """Parse the board as the last run left it. Blank tab -> nothing to compare."""
    prior = PriorFill()
    if not values:
        return prior
    status = str(values[STATUS_ROW - 1][0]) if len(values) >= STATUS_ROW and values[STATUS_ROW - 1] else ""
    m = _STAMP_RE.search(status)
    prior.stamp = m.group(1) if m else ""
    col = cols.resolve(headers)
    owner_i, pct_i = col.get("owner", 0), col.get("retention")
    for c0 in (0, width + GAP_COLS):
        title = str(values[0][c0]) if len(values[0]) > c0 else ""
        wm = _WEEK_RE.search(title)
        if not wm:
            continue
        wk, day = wm.group(1), None
        for row in values[FIRST_BODY_ROW - 1:]:
            first = str(row[c0]) if len(row) > c0 else ""
            head = first.split(" ", 1)[0]
            if head.isupper() and head.title() in ars.DAYS:
                day = head.title()
                continue
            if not day or not first.strip() or pct_i is None:
                continue
            if first.startswith("No office"):
                continue                     # the "nobody under the mark" line
            pct = row[c0 + pct_i] if len(row) > c0 + pct_i else ""
            prior.listed.setdefault((wk, day), {})[first.strip()] = \
                pct if isinstance(pct, (int, float)) else ars._as_number(str(pct))
    return prior


def _pct(x) -> str:
    return f"{round(x * 100)}%" if isinstance(x, (int, float)) else "blank"


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(a * 100) == round(b * 100)
    return a == b


def compare(results: List[WeekResult], prior: PriorFill, headers: List[str]
            ) -> Dict[Tuple[str, str, str], Tuple[str, str]]:
    """{(week, day, owner): (field, note)} for everything that moved.

    Also fills DayResult.risen with the offices that were listed last time and
    are now above the mark. Days the last check never saw (they had not happened
    yet) are not compared: everything on them is new by definition."""
    notes: Dict[Tuple[str, str, str], Tuple[str, str]] = {}
    if not prior.stamp:
        return notes
    col = cols.resolve(headers)
    owner_i, pct_i = col.get("owner", 0), col.get("retention")
    if pct_i is None:
        return notes
    for wr in results:
        for day, dr in wr.days.items():
            before = prior.listed.get((wr.label, day))
            if before is None or dr.future:
                continue
            now_all = {str(r[owner_i]): r[pct_i] for r in dr.all_rows}
            now_listed = {str(r[owner_i]) for r in dr.rows}
            for owner in now_listed:
                if owner in before:
                    if not _same(before[owner], now_all.get(owner)):
                        notes[(wr.label, day, owner)] = (
                            "retention", f"Was {_pct(before[owner])} at the {prior.stamp} check.")
                else:
                    notes[(wr.label, day, owner)] = (
                        "owner", f"Not on this day's list at the {prior.stamp} check -- "
                                 f"the day's numbers moved since.")
            for owner, was in before.items():
                if owner not in now_listed:
                    dr.risen.append(f"{owner} ({_pct(was)} -> {_pct(now_all.get(owner))})")
    return notes


# ------------------------------------------------------------------ the layout
def _band_text(dr: DayResult, show_all: bool) -> str:
    head = f"{dr.day.upper()} {dr.date.month}/{dr.date.day}"
    if dr.future:
        return f"{head}  ·  not yet"
    if not dr.interviewed and not dr.rows:
        return f"{head}  ·  no interviews recorded"
    if show_all:
        text = f"{head}  ·  every office ({dr.interviewed} interviewed)"
    else:
        text = (f"{head}  ·  {len(dr.rows)} of {dr.interviewed} offices that "
                f"interviewed at or under {rep.THRESHOLD:.0%}")
    if dr.risen:
        text += f"  ·  back above {rep.THRESHOLD:.0%} since last check: " + ", ".join(dr.risen)
    return text


def _empty_text(dr: DayResult) -> str:
    if dr.future or not dr.interviewed:
        return ""
    return f"No office at or under {rep.THRESHOLD:.0%} this day."


@dataclass
class Layout:
    values: List[list]                                  # the whole grid
    band_rows: List[int]                                # 1-indexed
    data_rows: List[Tuple[int, int]]                    # (row, block start col 0-idx)
    message_rows: List[Tuple[int, int]]
    last_row: int
    cell_notes: List[Tuple[int, int, str]]              # (row, col 0-idx, note)


def lay_out(results: List[WeekResult], headers: List[str], status: str,
            notes: Dict[Tuple[str, str, str], Tuple[str, str]],
            show_all: bool) -> Layout:
    width = len(headers)
    total = width * len(results) + GAP_COLS * (len(results) - 1)
    col = cols.resolve(headers)
    owner_i = col.get("owner", 0)
    grid: List[list] = []

    def blank():
        return [""] * total

    titles = blank()
    for k, wr in enumerate(results):
        which = "THIS WEEK" if k == 0 else "LAST WEEK"
        mon, fri = day_date(wr.start, "Monday"), day_date(wr.start, "Friday")
        t = (f"{which}  ·  week of {wr.label}  ·  Mon {mon.month}/{mon.day} – "
             f"Fri {fri.month}/{fri.day}")
        if wr.missing:
            t += f"  ·  {wr.missing}"
        titles[k * (width + GAP_COLS)] = t
    grid.append(titles)
    st = blank()
    st[0] = status
    grid.append(st)
    grid.append(blank())                 # banners: pasted from the template
    grid.append(blank())                 # headers: pasted from the template

    bands, data, msgs, cell_notes = [], [], [], []
    for day in ars.DAYS:
        band = blank()
        for k, wr in enumerate(results):
            band[k * (width + GAP_COLS)] = _band_text(wr.days[day], show_all)
        grid.append(band)
        bands.append(len(grid))
        height = max([len(wr.days[day].rows) for wr in results] + [1])
        for i in range(height):
            line = blank()
            for k, wr in enumerate(results):
                c0 = k * (width + GAP_COLS)
                dr = wr.days[day]
                if i < len(dr.rows):
                    line[c0:c0 + width] = dr.rows[i]
                    data.append((len(grid) + 1, c0))
                    hit = notes.get((wr.label, day, str(dr.rows[i][owner_i])))
                    if hit:
                        fld, note = hit
                        cell_notes.append((len(grid) + 1, c0 + col.get(fld, owner_i), note))
                elif i == 0 and _empty_text(dr):
                    line[c0] = _empty_text(dr)
                    msgs.append((len(grid) + 1, c0))
            grid.append(line)
    return Layout(values=grid, band_rows=bands, data_rows=data, message_rows=msgs,
                  last_row=len(grid), cell_notes=cell_notes)


# --------------------------------------------------------------- the requests
def _rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def format_requests(sid: int, tsid: int, t_hrow: int, headers: List[str],
                    layout: Layout, n_blocks: int, widths: List[Optional[int]]) -> List[dict]:
    width = len(headers)
    total = width * n_blocks + GAP_COLS * (n_blocks - 1)
    starts = [k * (width + GAP_COLS) for k in range(n_blocks)]
    reqs: List[dict] = []

    # A clean slate: this tab is generated, every run rebuilds it.
    reqs.append({"unmergeCells": {"range": {"sheetId": sid}}})
    reqs.append({"updateCells": {"range": {"sheetId": sid},
                                 "fields": "userEnteredFormat,note"}})

    # The template's banner and header rows, once per week. Banners start at
    # column C: A of that row holds the live tab's own status line.
    for c0 in starts:
        reqs.append({"copyPaste": {
            "source": _rng(tsid, t_hrow - 2, t_hrow - 1, 2, width),
            "destination": _rng(sid, BANNER_ROW - 1, BANNER_ROW, c0 + 2, c0 + width),
            "pasteType": "PASTE_NORMAL"}})
        reqs.append({"copyPaste": {
            "source": _rng(tsid, t_hrow - 1, t_hrow, 0, width),
            "destination": _rng(sid, HEADER_ROW - 1, HEADER_ROW, c0, c0 + width),
            "pasteType": "PASTE_NORMAL"}})
    # Office rows wear the template's first data row.
    for r, c0 in layout.data_rows:
        reqs.append({"copyPaste": {
            "source": _rng(tsid, t_hrow, t_hrow + 1, 0, width),
            "destination": _rng(sid, r - 1, r, c0, c0 + width),
            "pasteType": "PASTE_FORMAT"}})

    def band(row, c0, c1, bg, size, italic=False, fg=WHITE):
        reqs.append({"mergeCells": {"range": _rng(sid, row - 1, row, c0, c1),
                                    "mergeType": "MERGE_ALL"}})
        reqs.append({"repeatCell": {"range": _rng(sid, row - 1, row, c0, c1),
            "cell": {"userEnteredFormat": {
                "backgroundColor": bg, "verticalAlignment": "MIDDLE",
                "horizontalAlignment": "LEFT", "wrapStrategy": "CLIP",
                "textFormat": {"fontFamily": rep.FONT, "fontSize": size, "bold": not italic,
                               "italic": italic, "foregroundColor": fg}}},
            "fields": "userEnteredFormat(backgroundColor,verticalAlignment,"
                      "horizontalAlignment,wrapStrategy,textFormat)"}})

    for c0 in starts:
        band(TITLE_ROW, c0, c0 + width, rep.BANNER_BG, 14)
    band(STATUS_ROW, 0, total, rep.STATUS_BG, 10, italic=True, fg={"red": 0, "green": 0, "blue": 0})
    for r in layout.band_rows:
        for c0 in starts:
            band(r, c0, c0 + width, DAY_BG, 11)
    for r, c0 in layout.message_rows:
        reqs.append({"repeatCell": {"range": _rng(sid, r - 1, r, c0, c0 + 1),
            "cell": {"userEnteredFormat": {"wrapStrategy": "OVERFLOW_CELL",
                "textFormat": {"fontFamily": rep.FONT, "italic": True,
                               "foregroundColor": MUTED}}},
            "fields": "userEnteredFormat(wrapStrategy,textFormat)"}})

    # The coloured columns start WHITE. The template row carries a fixed fill
    # under them (green under Qualified Retention, yellow under the retention),
    # so a blank cell read as a good number. Every real value gets its colour
    # from the conditional rules instead -- each band has a red catch-all, so
    # nothing with a number can stay white.
    col = cols.resolve(headers)
    cf_cols = [col[f] for f in ("retention", "qualified_ret", "declined_ret",
                                "booked_ret", "not_contacted_ret") if f in col]
    for r, c0 in layout.data_rows:
        for i in cf_cols:
            reqs.append({"repeatCell": {"range": _rng(sid, r - 1, r, c0 + i, c0 + i + 1),
                "cell": {"userEnteredFormat": {"backgroundColor": WHITE}},
                "fields": "userEnteredFormat.backgroundColor"}})

    # Number formats by field, on office rows only.
    for r, c0 in layout.data_rows:
        for fields_, pattern, kind in ((rep.PERCENT_FIELDS, "0%", "PERCENT"),
                                       (rep.COUNT_FIELDS, "0", "NUMBER")):
            for f in fields_:
                i = col.get(f)
                if i is None:
                    continue
                reqs.append({"repeatCell": {"range": _rng(sid, r - 1, r, c0 + i, c0 + i + 1),
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
                    "fields": "userEnteredFormat.numberFormat"}})

    for r, c, note in layout.cell_notes:
        reqs.append({"updateCells": {"range": _rng(sid, r - 1, r, c, c + 1),
                                     "rows": [{"values": [{"note": note}]}], "fields": "note"}})

    # Widths: the template's, both weeks; the gap column narrow.
    for k, c0 in enumerate(starts):
        for i, px in enumerate(widths[:width]):
            if px:
                reqs.append({"updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "COLUMNS",
                              "startIndex": c0 + i, "endIndex": c0 + i + 1},
                    "properties": {"pixelSize": px}, "fields": "pixelSize"}})
        if k:
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS",
                          "startIndex": c0 - GAP_COLS, "endIndex": c0},
                "properties": {"pixelSize": 24}, "fields": "pixelSize"}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 36}, "fields": "pixelSize"}})
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": HEADER_ROW}},
        "fields": "gridProperties.frozenRowCount"}})
    return reqs


def cf_requests(sid: int, existing: List[dict], headers: List[str],
                n_blocks: int, last_row: int) -> List[dict]:
    """The single-day tab's colour rules, once per week. Every rule on this tab
    is ours, so the old ones all go first."""
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
            for i in reversed(range(len(existing)))]
    width = len(headers)
    index = 0
    for k in range(n_blocks):
        shifted = [""] * (k * (width + GAP_COLS)) + list(headers)
        for column, rules in rep.cf_plan(shifted, FIRST_BODY_ROW):
            rng = _rng(sid, FIRST_BODY_ROW - 1, last_row, column, column + 1)
            for formula, bg, fg in rules:
                reqs.append({"addConditionalFormatRule": {"index": index, "rule": {
                    "ranges": [rng],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA",
                                      "values": [{"userEnteredValue": formula}]},
                        "format": {"backgroundColor": bg,
                                   "textFormat": {"bold": True, "foregroundColor": fg}}}}}})
                index += 1
    return reqs


# ------------------------------------------------------------------- the run
def _template(sh, logfn=print):
    """(worksheet, header row, headers, column widths) from the live tab."""
    tws = fill.worksheet_ci(sh, TEMPLATE_TAB)
    top = tws.get("A1:AZ25")
    hrow = rep.find_header_row(top)
    if hrow is None:
        raise SystemExit(f"{TEMPLATE_TAB!r}: no {rep.OWNER_HEADER!r} header row")
    headers = list(top[hrow - 1])
    while headers and not rep._norm(headers[-1]):
        headers.pop()
    # The board stops before 'Office to Fill out report for': a working column
    # the report never fills, and wide enough to crowd everything else out.
    office = cols.resolve(headers).get("office")
    if office is not None:
        headers = headers[:office]
    meta = sh.fetch_sheet_metadata({
        "ranges": [f"'{TEMPLATE_TAB}'!A1:{ars.a1col(len(headers))}1"],
        "fields": "sheets(properties.sheetId,data.columnMetadata.pixelSize)"})
    widths: List[Optional[int]] = []
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] == tws.id:
            for d in s.get("data", []):
                widths = [c.get("pixelSize") for c in d.get("columnMetadata", [])]
    logfn(f"  template: {TEMPLATE_TAB!r}, headers on row {hrow}, {len(headers)} columns")
    return tws, hrow, headers, widths


def _board_ws(sh, tab: str, rows: int, cols_: int):
    try:
        ws = fill.worksheet_ci(sh, tab)
    except Exception:                                     # noqa: BLE001
        ws = sh.add_worksheet(title=tab, rows=max(rows, 300), cols=max(cols_, 40))
        return ws, True
    if ws.row_count < rows or ws.col_count < cols_:
        ws.resize(rows=max(ws.row_count, rows), cols=max(ws.col_count, cols_))
    return ws, False


def run(*, week_label_: Optional[str] = None, tab: str = BOARD_TAB,
        dry_run: bool = False, show_all: bool = False, use_appstream: bool = True,
        refresh_index: bool = False, today: Optional[dt.date] = None,
        logfn=print) -> dict:
    now = dt.datetime.now(dt.timezone.utc).astimezone(rep.CT)
    today = today or now.date()
    sh = fill.open_by_key(rep.SHEET_ID)
    tws, t_hrow, headers, widths = _template(sh, logfn)
    width = len(headers)

    if week_label_:
        start = apst.week_start_for(week_label_)
    else:
        start = this_week_start(today)
    starts = [start, start - dt.timedelta(days=7)]

    all_weeks = src.parse_blocks(fill.worksheet_ci(sh, src.SOURCE_TAB).get_all_values())
    weeks, missing = [], []
    for s in starts:
        try:
            weeks.append(src.pick_week(all_weeks, week_label(s)))
            missing.append(None)
        except SystemExit:
            # The source tab has no block for this week yet (Monday morning, say):
            # show the week empty and say why, rather than failing the whole board.
            weeks.append(src.Week(label=week_label(s), header_row=0, owners=[]))
            missing.append(f"not on {src.SOURCE_TAB!r} yet")
    logfn(f"  this week {weeks[0].label} ({len(weeks[0].owners)} owners), "
          f"last week {weeks[1].label} ({len(weeks[1].owners)} owners)")

    results, notes = pull(weeks, starts, headers, today=today, use_appstream=use_appstream,
                          show_all=show_all, refresh_index=refresh_index, logfn=logfn)
    for wr, why in zip(results, missing):
        wr.missing = why

    board_exists = True
    try:
        bws = fill.worksheet_ci(sh, tab)
        before = bws.get(f"A1:{ars.a1col(2 * width + GAP_COLS)}400",
                         value_render_option="UNFORMATTED_VALUE")
    except Exception:                                     # noqa: BLE001
        board_exists, before = False, []
    prior = read_prior(before, width, headers)
    moved = compare(results, prior, headers)

    stamp = f"{now:%a} {now.month}/{now.day} {now:%H:%M}"
    what = ("every office" if show_all else
            f"offices at or under {rep.THRESHOLD:.0%} on 'Retention first showed up booked second'")
    status = (f"{what}  ·  every day of both weeks re-checked this run  ·  "
              f"checked {stamp} CT")
    if prior.stamp:
        status += (f"  ·  {len(moved)} moved since the {prior.stamp} check"
                   + (" (see the notes on the cells)" if moved else ""))
    layout = lay_out(results, headers, status, moved, show_all)

    for wr in results:
        for day, dr in wr.days.items():
            logfn(f"    {wr.label} {_band_text(dr, show_all)}")
    logfn(f"  {len(notes)} gaps" + "".join(f"\n    - {n}" for n in notes[:40]))
    if moved:
        logfn(f"  {len(moved)} moved since {prior.stamp}:")
        for (wk, day, owner), (_, note) in moved.items():
            logfn(f"    {wk} {day} {owner}: {note}")

    if dry_run:
        logfn(f"  DRY RUN - nothing written ({layout.last_row} rows would be)")
        return {"written": False, "rows": layout.last_row, "moved": len(moved),
                "notes": notes}

    total_cols = 2 * width + GAP_COLS
    bws, created = _board_ws(sh, tab, layout.last_row + 60, total_cols)
    if not created and board_exists:
        bws.batch_clear([f"A1:{ars.a1col(max(bws.col_count, total_cols))}{bws.row_count}"])
    bws.update(f"A1:{ars.a1col(total_cols)}{layout.last_row}", layout.values,
               value_input_option="RAW")
    sh.batch_update({"requests": format_requests(bws.id, tws.id, t_hrow, headers, layout,
                                                 len(results), widths)})
    meta = sh.fetch_sheet_metadata()
    existing = next((s.get("conditionalFormats", []) for s in meta["sheets"]
                     if s["properties"]["sheetId"] == bws.id), [])
    sh.batch_update({"requests": cf_requests(bws.id, existing, headers, len(results),
                                             layout.last_row)})
    logfn(f"  wrote {layout.last_row} rows to {tab!r}")
    return {"written": True, "tab": tab, "rows": layout.last_row,
            "moved": len(moved), "notes": notes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_to_second_below_mark.board")
    ap.add_argument("--week", default=None,
                    help="the week to show as THIS week, e.g. 9/13 (default: the current one)")
    ap.add_argument("--tab", default=BOARD_TAB)
    ap.add_argument("--all", dest="show_all", action="store_true",
                    help="list every office, not only those at or under the mark")
    ap.add_argument("--no-appstream", dest="use_appstream", action="store_false")
    ap.add_argument("--refresh-index", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    res = run(week_label_=args.week, tab=args.tab, dry_run=args.dry_run,
              show_all=args.show_all, use_appstream=args.use_appstream,
              refresh_index=args.refresh_index)
    print(f"OK - { {k: v for k, v in res.items() if k != 'notes'} }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

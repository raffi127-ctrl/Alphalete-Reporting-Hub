"""Write the BOX Order Log into the Vantura Master Sales Board.

Two tabs, the same shape as Carlos's churn report — which is what he asked
for ("it just has multiple tabs hidden, and then it's pulling from those
tabs"):

  * "Lucy Box Data"      — hidden. The collapsed rows, one per sale, six
                           weeks deep. Rewritten in full on every run.
  * "Lucy Box Order Log" — what Carlos looks at. A rep dropdown, a
                           count-by-week-ending summary, and the log itself.
                           Everything below the dropdown is FORMULAS reading
                           the hidden tab, so changing the rep repaints
                           instantly without re-running anything.

GOLDEN RULE, inherited from automations/vantura_churn/fill.py: this is the
LIVE board. We touch ONLY our own two tabs. In particular "Box Order Log"
(no "Lucy") is Carlos's hand-built sheet — it is the ground truth this
report's rules were derived from, and it is never read-modified or cleared.
"""
from __future__ import annotations

import collections
import datetime as dt
from typing import Dict, List, Optional, Sequence

from automations.recruiting_report.fill import _retry, open_by_key

from . import clean

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
TAB_VIEW = "Lucy Box Order Log"
TAB_DATA = "Lucy Box Data"

# Tabs this module must never write to, whatever else changes.
PROTECTED_TABS = ("Box Order Log", "Churn", "Churn - Atef", "Activations",
                  "Sales Board", "WeekData")

WEEKS = 6

# What the view shows — the FILTER pulls exactly this slice (A:L), so the
# order here is load-bearing.
DISPLAY_HEADERS = (
    "Week Ending", "Rep Name", "Sale Date", "Business Name", "Contract ID",
    "Status", "Contr. Sub-status", "Secondary Status", "Accepted Date",
    "BF Tier", "Complete Sales", "Sales (All) kWH+Therms",
)

# The hidden tab carries two more columns past the display slice:
#   Account Id   — half the sale key, needed to merge runs (Contract ID alone
#                  is not unique; see clean.SALE_KEY_COLUMNS).
#   Last Updated — the run date this row's status last CHANGED. Lets us say
#                  what actually moved today rather than re-reporting the lot.
#   Filter Week  — the week again, but present on SPACER rows too. The log is
#                  one spilling FILTER, so blank separator rows between reps
#                  have to come from the source data; keying the filter off
#                  this column instead of the visible Week Ending lets a
#                  spacer pass the filter while rendering completely empty.
DATA_HEADERS = DISPLAY_HEADERS + ("Account Id", "Last Updated", "Filter Week")

_COL_CONTRACT = DISPLAY_HEADERS.index("Contract ID")
_COL_STATUS = DISPLAY_HEADERS.index("Status")
_COL_WEEK = DISPLAY_HEADERS.index("Week Ending")
_COL_REP = DISPLAY_HEADERS.index("Rep Name")
_COL_ACCOUNT = DATA_HEADERS.index("Account Id")
_COL_UPDATED = DATA_HEADERS.index("Last Updated")
_COL_FILTER_WEEK = DATA_HEADERS.index("Filter Week")
_FILTER_WEEK_COL = "O"                         # A=0 … O=14

# Summary block: which coarse statuses get a column, left to right.
SUMMARY_STATUSES = (
    "Ready For Booking", "Accepted by Supplier", "Submitted to Supplier",
    "Verification", "Incomplete", "Cancelled by Broker", "Rejected",
)

# Row anchors on the view tab (1-based). The summary block is one row per REP
# and the roster changes, so everything below it is computed from that count
# rather than hard-coded.
ROW_TITLE = 1
ROW_WEEK = 2                                   # the dropdown lives here
ROW_NOTE = 3
ROW_SUM_HEAD = 5
ROW_SUM_FIRST = 6
LOG_LAST = 600                                 # conditional-format ceiling

ALL_WEEKS = "All Weeks"

CELL_WEEK = "B{}".format(ROW_WEEK)             # for acell() reads
# Fully absolute in formulas: every count and the FILTER point at the one
# dropdown, and must keep pointing there if a row is ever inserted above.
REF_WEEK = "$B${}".format(ROW_WEEK)

# The dropdown cell can hold EITHER a real date (Sheets parses "07/18/2026" on
# entry, which is what a USER_ENTERED write and a picked dropdown item both
# produce) or literal text, depending on the cell's number format at the time.
# Comparing the wrong one silently returns zero everywhere — every count read 0
# and the log said "No sales in this week" (2026-07-18). Coerce, don't assume.
_WEEK_VALUE = "IF(ISTEXT({w}),DATEVALUE({w}),{w})".format(w=REF_WEEK)


def _anchors(n_reps: int) -> Dict[str, int]:
    """Where each block starts, given how many reps are in the roster."""
    total = ROW_SUM_FIRST + n_reps             # the TOTAL row
    log_head = total + 2
    return {"sum_first": ROW_SUM_FIRST, "sum_total": total,
            "log_head": log_head, "log_first": log_head + 1}


_STATUS_COL = "F"          # Status, on the VIEW tab
_SECONDARY_COL = "H"       # Secondary Status, on the VIEW tab
_LAST_COL = "L"

# Hidden helper block for the rep summary, starting at column R. It sits well
# clear of the 12-column log so the FILTER spill can never collide with it.
HELPER_COL0 = 17           # R


def _col_letter(index0: int) -> str:
    """0-based column index -> A1 letter (handles past Z)."""
    letters = ""
    n = index0 + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters

WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}


def _rgb(hex_str: str) -> Dict[str, float]:
    h = hex_str.lstrip("#")
    return {"red": int(h[0:2], 16) / 255.0,
            "green": int(h[2:4], 16) / 255.0,
            "blue": int(h[4:6], 16) / 255.0}


def _fmt_date(d: Optional[dt.date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


def _stamp(now: dt.datetime) -> str:
    """'Jul 18, 2026 3:05 PM' — built without %-I/%-d, which are glibc/BSD
    only and raise on Windows. Every report here has to run on both."""
    hour = now.hour % 12 or 12
    return "{} {}, {} {}:{:02d} {}".format(
        now.strftime("%b"), now.day, now.year, hour, now.minute,
        "AM" if now.hour < 12 else "PM")


def _open():
    return open_by_key(SHEET_ID)


def _ensure_tab(sh, title: str, *, hidden: bool = False, rows: int = 1000,
                cols: int = 14):
    import gspread
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = _retry(lambda: sh.add_worksheet(title=title, rows=rows, cols=cols))
    if hidden and not ws._properties.get("hidden"):
        _retry(lambda: sh.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "hidden": True},
            "fields": "hidden"}}]}))
    return ws


def _sale_row(s, updated: str) -> List[str]:
    f = s.fields
    return [
        _fmt_date(s.week_ending),
        (f.get("Rep Name") or "").strip(),
        _fmt_date(s.sale_date),
        (f.get("Business Name") or "").strip(),
        (f.get("Contract ID") or "").strip(),
        s.status,
        s.sub_status,
        s.secondary,
        (f.get("Accepted Date") or "").strip(),
        (f.get("BF Tier") or "").strip(),
        (f.get("Complete Sales") or "").strip(),
        (f.get("Sales (All) kWH+Therms") or "").strip(),
        (f.get("Account Id") or "").strip(),
        updated,
    ]


def _norm_id(value: str) -> str:
    """Normalise an ID for key comparison.

    Sheets stores these as numbers, so a value we WRITE as "267770" can come
    back as "267,770" once the column picks up a thousands separator — which
    silently broke the merge key and duplicated every row on the second run
    (2026-07-18). Strip anything that isn't a digit so the key survives
    whatever display format the column drifts into.
    """
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _row_key(row: Sequence[str]) -> tuple:
    """Sale identity for merging: Contract ID + Account Id."""
    def at(i):
        return _norm_id(row[i]) if len(row) > i else ""
    return (at(_COL_CONTRACT), at(_COL_ACCOUNT))


def _sort_rows(rows: List[List[str]]) -> List[List[str]]:
    """Newest week first, then rep, then most-urgent status."""
    def key(r):
        wk = clean._parse_date(r[_COL_WEEK]) if len(r) > _COL_WEEK else None
        rep = r[1] if len(r) > 1 else ""
        status = r[_COL_STATUS] if len(r) > _COL_STATUS else ""
        return (-(wk.toordinal() if wk else 0), rep, clean._status_rank(status))
    return sorted(rows, key=key)


def build_data_rows(sales: Sequence, updated: str) -> List[List[str]]:
    """The hidden tab's body from a single pull — one row per sale."""
    return _sort_rows([_sale_row(s, updated) for s in sales])


def with_spacers(rows: Sequence[Sequence[str]]) -> List[List[str]]:
    """Insert one blank row between reps, and stamp the Filter Week column.

    The log on the view tab is a single FILTER, which spills a contiguous
    block — there is no way to inject a gap from the formula side. So the gap
    lives in the source: a row that is blank in every visible column but
    carries the week in `Filter Week`, which is what the FILTER actually
    tests. It passes the week filter, renders as an empty line, and is skipped
    on read-back because merge_rows ignores rows with no Week Ending.

    Rows must already be sorted by (week desc, rep, status) — a rep's sales
    are contiguous, so a change of rep is a section break.
    """
    out: List[List[str]] = []
    prev = None
    for row in rows:
        row = list(row) + [""] * (len(DATA_HEADERS) - len(row))
        week = row[_COL_WEEK]
        rep = row[_COL_REP]
        if prev is not None and (week, rep) != prev:
            spacer = [""] * len(DATA_HEADERS)
            # Same week as the block we just closed, so the gap travels with
            # it when Carlos filters to that week.
            spacer[_COL_FILTER_WEEK] = prev[0]
            # The spacer also carries the week in the VISIBLE Week Ending
            # column. That looks wrong until you see the color rule: the
            # spacer is painted dark-on-dark, so the text is invisible and the
            # row reads as a solid divider bar. It needs *some* visible value
            # so a conditional-format rule can tell a spacer (A filled, Rep
            # blank) from the empty rows below the spill (both blank).
            spacer[_COL_WEEK] = prev[0]
            out.append(spacer)
        row[_COL_FILTER_WEEK] = week
        out.append(row)
        prev = (week, rep)
    return out


def merge_rows(existing: Sequence[Sequence[str]], sales: Sequence,
               *, today: dt.date, weeks: int = WEEKS,
               stamp: Optional[str] = None) -> Dict[str, object]:
    """Fold today's pull into what's already on the sheet.

    Carlos asked for a six-week log that gains "new order updates as they come
    in", which means this cannot be a blind overwrite:

      * A sale already on the sheet but NOT in today's pull is KEPT. The
        Tableau view is a rolling ~44-day window with only about three days of
        slack over six weeks, so rows age out of the source before they age
        out of the report. Overwriting would silently drop the oldest week.
      * A sale in both is REPLACED by today's version — the fresh pull carries
        the sale's whole transition history, so its collapsed status is
        authoritative. Last Updated only moves when the status actually
        changed, so it means "this moved", not "we ran again".
      * Anything older than the six-week window is dropped, which is the
        "every new week, the oldest log would delete" half of the ask.
    """
    stamp = stamp or _fmt_date(today)
    merged: "collections.OrderedDict[tuple, List[str]]" = collections.OrderedDict()

    for row in existing:
        if not row:
            continue
        row = list(row) + [""] * (len(DATA_HEADERS) - len(row))
        # Skip separator rows. Testing the KEY (Contract ID + Account Id)
        # rather than "is column A blank" — spacers now carry a week in
        # column A so a color rule can find them, and a blank-A test would
        # let them through as if they were sales.
        if not any(_row_key(row)):
            continue
        merged[_row_key(row)] = row

    added = changed = 0
    for s in sales:
        fresh = _sale_row(s, stamp)
        key = _row_key(fresh)
        prior = merged.get(key)
        if prior is None:
            added += 1
        elif prior[_COL_STATUS].strip() == fresh[_COL_STATUS].strip():
            # Nothing moved — keep the ORIGINAL Last Updated so the column
            # keeps meaning "when this last changed".
            fresh[_COL_UPDATED] = prior[_COL_UPDATED] or stamp
        else:
            changed += 1
        merged[key] = fresh

    oldest = clean.week_ending(today) - dt.timedelta(weeks=weeks - 1)
    kept, aged, purged = [], 0, 0
    for row in merged.values():
        # Carried rows are re-tested against the CURRENT rules. Merge only
        # ever adds, updates or ages out, so without this a sale that stopped
        # counting (Carlos ruled TPV Failed out on 2026-07-18) would sit on
        # the sheet forever — it isn't in the new pull, so nothing would
        # replace it, and it isn't old, so nothing would age it out.
        if clean.level(row[_COL_STATUS], row[_COL_STATUS + 1]) in clean.DEAD_LEVELS:
            purged += 1
            continue
        wk = clean._parse_date(row[_COL_WEEK])
        if wk and wk < oldest:
            aged += 1
            continue
        kept.append(row)

    return {"rows": _sort_rows(kept), "added": added, "changed": changed,
            "aged_out": aged, "purged": purged, "carried": len(kept) - added}


def _summary_formula(rep_cell: str, status_cell: str) -> str:
    """Count for one (rep, status) pair inside the SELECTED week.

    The week test is folded into COUNTIFS rather than kept in a helper column,
    so the view stays self-contained — click any number and you can see where
    it came from. DATEVALUE because the dropdown hands back text while the
    data tab's Week Ending column holds real dates; it sits in the branch that
    only runs when a specific week is picked.
    """
    wk = "'{}'!$A:$A".format(TAB_DATA)
    st = "'{}'!$F:$F".format(TAB_DATA)
    rp = "'{}'!$B:$B".format(TAB_DATA)
    return ('=IF({w}="{all}",'
            'COUNTIFS({rp},${rc},{st},{sc}),'
            'COUNTIFS({rp},${rc},{st},{sc},{wk},{wv}))').format(
        w=REF_WEEK, all=ALL_WEEKS, wk=wk, st=st, rp=rp,
        wv=_WEEK_VALUE, rc=rep_cell, sc=status_cell)


def build_view_values(weeks: Sequence[dt.date], reps: Sequence[str],
                      generated: str,
                      selected: Optional[str] = None) -> List[List[str]]:
    """Everything on the view tab: labels, formulas, the FILTER.

    Carlos picks a WEEK at the top. Under it, that week broken down one row
    per rep sorted busiest-first; under that, the week's log with a blank row
    between reps.

    The rep block is built in two pieces. A hidden helper block (columns R:Y)
    holds one static rep name per row plus its COUNTIFS, and the visible block
    is a single SORT() over that helper. It has to work this way because the
    counts change with the selected week — sorting the rows in Python would
    freeze the order to whatever week happened to be picked at write time.
    """
    n_status = len(SUMMARY_STATUSES)
    width = HELPER_COL0 + n_status + 2
    a = _anchors(len(reps))

    def row(*cells):
        c = list(cells)
        return c + [""] * (width - len(c))

    blank = [""] * width
    grid: List[List[str]] = []
    grid.append(row("BOX Order Log"))
    grid.append(row("Week Ending:", selected or (
        _fmt_date(weeks[0]) if weeks else ALL_WEEKS)))
    grid.append(row("Last {} weeks kept · updated {}".format(
        len(weeks), generated)))
    grid.append(blank[:])
    grid.append(row("Rep", *SUMMARY_STATUSES, "Total"))

    first, last_row = a["sum_first"], a["sum_total"] - 1
    helper_first = _col_letter(HELPER_COL0)
    helper_last = _col_letter(HELPER_COL0 + n_status + 1)

    for i, rep in enumerate(reps):
        r = first + i
        cells = blank[:]
        if i == 0:
            # One SORT over the whole helper block, descending by Total (the
            # last column). Spills down and right over the visible rep rows.
            cells[0] = "=SORT({h1}{f}:{h2}{l},{tc},FALSE)".format(
                h1=helper_first, f=first, h2=helper_last, l=last_row,
                tc=n_status + 2)
        # Hidden helper: rep name, its counts, its total.
        cells[HELPER_COL0] = rep
        for j in range(n_status):
            label_col = _col_letter(1 + j)          # status header in row 5
            cells[HELPER_COL0 + 1 + j] = _summary_formula(
                "{}{}".format(helper_first, r), "{}$5".format(label_col))
        cells[HELPER_COL0 + n_status + 1] = "=SUM({a}{r}:{b}{r})".format(
            a=_col_letter(HELPER_COL0 + 1),
            b=_col_letter(HELPER_COL0 + n_status), r=r)
        grid.append(cells)

    totals = blank[:]
    totals[0] = "TOTAL"
    for j in range(n_status + 1):
        col = _col_letter(1 + j)
        totals[1 + j] = "=SUM({c}{f}:{c}{l})".format(c=col, f=first, l=last_row)
    grid.append(totals)

    grid.append(blank[:])
    hdr = blank[:]
    for i, h in enumerate(DISPLAY_HEADERS):
        hdr[i] = h
    grid.append(hdr)

    # The log. NO SORT() — FILTER preserves source order, and the data tab is
    # already written in exactly the order we want (week desc, then rep, then
    # most-urgent status) WITH a blank row between reps. Sorting here would
    # scatter those spacers, which is the whole reason the ordering is done
    # in Python instead.
    rng = "'{d}'!A2:L".format(d=TAB_DATA)
    key = "'{d}'!${c}$2:${c}".format(d=TAB_DATA, c=_FILTER_WEEK_COL)
    logrow = blank[:]
    logrow[0] = (
        '=IFERROR(IF({w}="{all}",'
        'FILTER({rng},{key}<>""),'
        'FILTER({rng},{key}<>"",{key}={wv})),'
        '"No sales in this week.")'.format(
            w=REF_WEEK, all=ALL_WEEKS, rng=rng, key=key, wv=_WEEK_VALUE))
    grid.append(logrow)
    return grid


def _format_requests(view_id: int, n_reps: int, n_status: int) -> List[dict]:
    """Static look: title, header bands, widths, frozen rows, number formats."""
    a = _anchors(n_reps)
    width = n_status + 2
    reqs: List[dict] = [
        # RESET first. The block boundaries move as the roster grows, and
        # ws.clear() wipes values but NOT formats — so last run's date format
        # sat on cells that are now summary counts and rendered them as
        # "12/30/1899". Strip all formatting, then repaint from scratch.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": 0,
                      "endRowIndex": LOG_LAST, "startColumnIndex": 0,
                      "endColumnIndex": HELPER_COL0 + 12},
            "cell": {},
            "fields": "userEnteredFormat"}},
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {
                "bold": True, "fontSize": 16}}},
            "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": ROW_WEEK - 1,
                      "endRowIndex": ROW_WEEK, "startColumnIndex": 0,
                      "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat"}},
        # The dropdown cell, gold like the one on his sales board.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": ROW_WEEK - 1,
                      "endRowIndex": ROW_WEEK, "startColumnIndex": 1,
                      "endColumnIndex": 2},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb("FFF2CC"),
                "horizontalAlignment": "CENTER",
                # Without this the reset above leaves it bare and the week
                # shows as the raw serial (46221).
                "numberFormat": {"type": "DATE", "pattern": "mm/dd/yyyy"},
                "textFormat": {"bold": True}}},
            "fields": ("userEnteredFormat(backgroundColor,horizontalAlignment,"
                       "numberFormat,textFormat)")}},
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": ROW_NOTE - 1,
                      "endRowIndex": ROW_NOTE, "startColumnIndex": 0,
                      "endColumnIndex": width},
            "cell": {"userEnteredFormat": {"textFormat": {
                "italic": True, "foregroundColor": _rgb("666666"),
                "fontSize": 9}}},
            "fields": "userEnteredFormat.textFormat"}},
    ]

    for row0, w in ((ROW_SUM_HEAD - 1, width),
                    (a["log_head"] - 1, len(DISPLAY_HEADERS))):
        reqs.append({"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": row0,
                      "endRowIndex": row0 + 1, "startColumnIndex": 0,
                      "endColumnIndex": w},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb("3D3D3D"),
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
                "textFormat": {"bold": True, "foregroundColor": WHITE}}},
            "fields": ("userEnteredFormat(backgroundColor,horizontalAlignment,"
                       "verticalAlignment,wrapStrategy,textFormat)")}})

    # Per-rep summary body: rep names left, counts centered.
    reqs.append({"repeatCell": {
        "range": {"sheetId": view_id, "startRowIndex": a["sum_first"] - 1,
                  "endRowIndex": a["sum_total"], "startColumnIndex": 1,
                  "endColumnIndex": width},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.horizontalAlignment"}})
    reqs.append({"repeatCell": {
        "range": {"sheetId": view_id, "startRowIndex": a["sum_total"] - 1,
                  "endRowIndex": a["sum_total"], "startColumnIndex": 0,
                  "endColumnIndex": width},
        "cell": {"userEnteredFormat": {
            "backgroundColor": _rgb("EDEDED"),
            "textFormat": {"bold": True}}},
        "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

    widths = [165, 150, 150, 150, 110, 150, 110, 90, 90, 65, 90, 110]
    for i, px in enumerate(widths):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})

    # FILTER returns raw values, so the log range carries no number format of
    # its own — dates land as 46221 and kWh as 26578 unless we format the
    # destination columns.
    def _numfmt(col0: int, ftype: str, pattern: str) -> dict:
        return {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": a["log_first"] - 1,
                      "endRowIndex": LOG_LAST, "startColumnIndex": col0,
                      "endColumnIndex": col0 + 1},
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": ftype, "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat"}}

    for col0 in (0, 2, 8):
        reqs.append(_numfmt(col0, "DATE", "mm/dd/yyyy"))
    reqs.append(_numfmt(11, "NUMBER", "#,##0"))

    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": view_id,
                       "gridProperties": {"frozenRowCount": a["log_head"]}},
        "fields": "gridProperties.frozenRowCount"}})

    # Hide the helper block that feeds the SORT. Carlos should never see it.
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": view_id, "dimension": "COLUMNS",
                  "startIndex": HELPER_COL0,
                  "endIndex": HELPER_COL0 + n_status + 2},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
    return reqs


def _validation_request(view_id: int, weeks: Sequence[dt.date]) -> dict:
    """The WEEK dropdown — same ONE_OF_LIST shape as his churn tab's C3."""
    values = [_fmt_date(w) for w in weeks] + [ALL_WEEKS]
    return {"setDataValidation": {
        "range": {"sheetId": view_id, "startRowIndex": ROW_WEEK - 1,
                  "endRowIndex": ROW_WEEK, "startColumnIndex": 1,
                  "endColumnIndex": 2},
        "rule": {
            "condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": v} for v in values]},
            "strict": True, "showCustomUi": True}}}


def _color_rules(view_id: int, n_reps: int) -> List[dict]:
    """Status colors on the log, plus a divider between rep blocks.

    Derived from clean.STATUS_COLORS rather than a list kept here — a
    hardcoded copy silently went stale when Ready For Booking moved from red
    to green (2026-07-18) and the sheet kept painting it red.

    CUSTOM_FORMULA throughout (not TEXT_EQ) because the fills have to follow
    the dynamic FILTER output row by row.
    """
    a = _anchors(n_reps)
    first = a["log_first"]
    rng = {"sheetId": view_id, "startRowIndex": first - 1,
           "endRowIndex": LOG_LAST, "startColumnIndex": 0,
           "endColumnIndex": len(DISPLAY_HEADERS)}

    # Separator bar FIRST, so it wins over anything below it. Sheets
    # conditional formatting cannot draw borders — the API rejects them
    # outright ("only supports bold, italic, strikethrough, foreground color
    # and background color") — and the log's block boundaries move with the
    # week dropdown, so static borders would misalign the moment Carlos
    # switched weeks. Painting the spacer row dark-on-dark gives the same
    # read: every rep block sits bracketed between two solid rules.
    # A spacer is "Week Ending filled, Rep Name blank"; the empty rows below
    # the spill have both blank, so they stay clean.
    bar = _rgb("3D3D3D")
    rules: List[dict] = [{"addConditionalFormatRule": {
        "index": 0,
        "rule": {"ranges": [rng],
                 "booleanRule": {
                     "condition": {"type": "CUSTOM_FORMULA", "values": [
                         {"userEnteredValue":
                          '=AND($A{r}<>"",$B{r}="")'.format(r=first)}]},
                     "format": {"backgroundColor": bar,
                                "textFormat": {"foregroundColor": bar}}}}}}]

    # One rule per color. The waiting/we-owe split can't be read off the
    # Status column alone — a sale in Verification is "waiting" if it was
    # already submitted and "ours to chase" if it wasn't — so those two test
    # Secondary Status (H) as well. Mirrors clean.color_for().
    sec = "$" + _SECONDARY_COL + str(first)
    st = "$" + _STATUS_COL + str(first)
    was_submitted = 'ISNUMBER(SEARCH("{s}",{h}))'.format(s=clean.SUBMITTED, h=sec)
    specs = [
        (clean.GREEN_BRIGHT, '={st}="Ready For Booking"'.format(st=st)),
        (clean.GREEN, '={st}="Accepted by Supplier"'.format(st=st)),
        (clean.RED_BRIGHT, '={st}="Incomplete"'.format(st=st)),
        (clean.RED, '=OR({st}="Cancelled by Broker",{st}="Rejected",'
                    '{st}="Dropped")'.format(st=st)),
        # Waiting on the supplier.
        (clean.YELLOW, '=OR({st}="{sub}",AND({st}="Verification",{ws}))'
                       .format(st=st, sub=clean.SUBMITTED, ws=was_submitted)),
        # We owe a bill / ETF document.
        (clean.ORANGE, '=AND({st}="Verification",NOT({ws}))'
                       .format(st=st, ws=was_submitted)),
    ]
    for hexv, formula in specs:
        rules.append({"addConditionalFormatRule": {
            "index": len(rules),
            "rule": {"ranges": [rng],
                     "booleanRule": {
                         "condition": {"type": "CUSTOM_FORMULA", "values": [
                             {"userEnteredValue": formula}]},
                         "format": {"backgroundColor": _rgb(hexv)}}}}})

    # Divider: bold the first row of each rep block, so the sections read
    # clearly even when two adjacent blocks share a fill color.
    rules.append({"addConditionalFormatRule": {
        "index": len(rules),
        "rule": {"ranges": [rng],
                 "booleanRule": {
                     "condition": {"type": "CUSTOM_FORMULA", "values": [
                         {"userEnteredValue":
                          '=AND($B{r}<>"",$B{r}<>$B{p})'.format(
                              r=first, p=first - 1)}]},
                     "format": {"textFormat": {"bold": True}}}}}})
    return rules


def _clear_color_rules(sh, view_id: int) -> List[dict]:
    """Delete our existing rules so re-runs don't stack duplicates."""
    meta = _retry(lambda: sh.client.request(
        "get", "https://sheets.googleapis.com/v4/spreadsheets/{}".format(sh.id),
        params={"fields": "sheets(properties(sheetId),conditionalFormats)"}
    ).json())
    n = 0
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") == view_id:
            n = len(s.get("conditionalFormats", []) or [])
            break
    # Highest index first — deleting shifts the ones above it down.
    return [{"deleteConditionalFormatRule": {"sheetId": view_id, "index": i}}
            for i in range(n - 1, -1, -1)]


def push(sales: Sequence, *, generated: Optional[str] = None,
         today: Optional[dt.date] = None, weeks_back: int = WEEKS,
         log=print) -> Dict[str, object]:
    """Merge today's pull into the sheet and repaint the view."""
    sh = _open()
    today = today or dt.date.today()

    # Belt and braces: refuse to run if our view tab name ever collides with
    # one of Carlos's. Cheap check, and the failure mode it prevents is
    # overwriting hand-entered work.
    if TAB_VIEW in PROTECTED_TABS or TAB_DATA in PROTECTED_TABS:
        raise RuntimeError("refusing to write: target tab is protected")

    if not generated:
        generated = _stamp(dt.datetime.now())

    # ---- hidden data tab: merge, don't overwrite ------------------------
    data_ws = _ensure_tab(sh, TAB_DATA, hidden=True, cols=len(DATA_HEADERS))
    prior = _retry(lambda: data_ws.get_all_values())
    prior_body = prior[1:] if prior else []

    result = merge_rows(prior_body, sales, today=today, weeks=weeks_back)
    rows = result["rows"]
    if not rows:
        raise RuntimeError("merge produced no rows — refusing to blank the tab")

    # Size for the SPACED body — one extra row per rep block, so this is
    # meaningfully larger than len(rows).
    spaced = with_spacers(rows)
    _retry(lambda: data_ws.resize(rows=max(1000, len(spaced) + 50),
                                  cols=len(DATA_HEADERS)))
    # Pin the two ID columns to plain text. They are the merge key, and as
    # numbers they render with thousands separators that used to corrupt it.
    _retry(lambda: sh.batch_update({"requests": [
        {"repeatCell": {
            "range": {"sheetId": data_ws.id, "startRowIndex": 1,
                      "startColumnIndex": c, "endColumnIndex": c + 1},
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "TEXT"}}},
            "fields": "userEnteredFormat.numberFormat"}}
        for c in (_COL_CONTRACT, _COL_ACCOUNT)]}))
    _retry(lambda: data_ws.clear())
    body = [list(DATA_HEADERS)] + spaced
    _retry(lambda: data_ws.update(
        body, "A1:{}{}".format(_FILTER_WEEK_COL, len(body)),
        value_input_option="USER_ENTERED"))
    log("  hidden data tab: {} rows ({} new, {} status changes, "
        "{} carried over, {} aged out, {} no longer count)".format(
            len(rows), result["added"], result["changed"],
            result["carried"], result["aged_out"], result["purged"]))

    # Weeks and reps come from the MERGED set, not just today's pull, so a
    # rep with nothing new today keeps their dropdown entry and their history.
    weeks = sorted({d for d in (clean._parse_date(r[_COL_WEEK]) for r in rows)
                    if d}, reverse=True)
    rep_names = sorted({r[1].strip() for r in rows if len(r) > 1 and r[1].strip()})

    # ---- view tab -------------------------------------------------------
    view_ws = _ensure_tab(sh, TAB_VIEW)

    # Keep whichever week is currently picked, so the 7am refresh doesn't yank
    # the view off the week Carlos is reading. Falls back to the newest week.
    week_labels = [_fmt_date(w) for w in weeks]
    current = ""
    try:
        current = (_retry(lambda: view_ws.acell(CELL_WEEK).value) or "").strip()
    except Exception:
        pass
    selected = current if current in week_labels + [ALL_WEEKS] else None

    grid = build_view_values(weeks, rep_names, generated, selected=selected)

    _retry(lambda: view_ws.clear())
    _retry(lambda: view_ws.update(
        grid, "A1:{}{}".format(_col_letter(len(grid[0]) - 1), len(grid)),
        value_input_option="USER_ENTERED"))

    reqs: List[dict] = []
    reqs += _clear_color_rules(sh, view_ws.id)
    reqs += _format_requests(view_ws.id, len(rep_names), len(SUMMARY_STATUSES))
    reqs.append(_validation_request(view_ws.id, weeks))
    reqs += _color_rules(view_ws.id, len(rep_names))
    _retry(lambda: sh.batch_update({"requests": reqs}))

    log("  view tab: {} weeks in the dropdown, {} reps in the breakdown".format(
        len(weeks) + 1, len(rep_names)))
    return {"rows": len(rows), "weeks": len(weeks), "reps": len(rep_names),
            "added": result["added"], "changed": result["changed"],
            "aged_out": result["aged_out"], "purged": result["purged"],
            "carried": result["carried"]}

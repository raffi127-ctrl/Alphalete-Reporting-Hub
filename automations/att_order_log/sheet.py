"""Write Carlos's ATT B2B Order Log into the Vantura Master Sales Board.

Two tabs, mirroring the BOX Order Log Carlos already reads every morning, so
his two logs behave identically:

  * "Lucy At&t Data"      — hidden. One row per real sale (post un-pivot),
                            rewritten in full on every run.
  * "Lucy At&t Order Log" — what Carlos looks at. Rep + period dropdowns, a
                            status summary, and the log itself. Everything
                            below the dropdowns is FORMULAS reading the hidden
                            tab, so changing the rep repaints instantly with no
                            re-run.

GOLDEN RULE, inherited from box_order_log.sheet and vantura_churn.fill: this is
the LIVE board. We touch ONLY our own two tabs. Megan 2026-07-19 confirmed both
targets were blank when she made them, but the guard stays — the risk was never
our own empty tabs, it is a bug reaching Carlos's hand-built "Box Order Log" or
the live "Sales Board" / "Commission" tabs sitting beside them.

FULL REWRITE, NOT A MERGE — deliberately different from box_order_log. That
module merges because its Tableau view is a rolling ~44-day window with only
~3 days of slack over the 6 weeks it reports, so rows age out of the source
before they age out of the report. The ORDERLOG view takes explicit Start/End
Date URL params, so we pull exactly the window we intend to show and can
rewrite it wholesale. Rewriting is simpler and cannot drift; merging exists to
work around a source limitation this feed does not have.
"""
from __future__ import annotations

import collections
import datetime as dt
from typing import Dict, List, Optional, Sequence

from automations.recruiting_report.fill import _retry, open_by_key

from . import colors

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master Sales Board
TAB_VIEW = "Lucy At&t Order Log"      # gid 1491859853, created blank by Megan
TAB_DATA = "Lucy At&t Data"           # hidden; created on first run

# Never write here, whatever else changes. "Box Order Log" is Carlos's own
# hand-built sheet; the rest are live report or finance tabs.
PROTECTED_TABS = (
    "Box Order Log", "Lucy Box Order Log", "Lucy Box Data",
    "Churn", "Churn - Atef", "LUCY CHURN", "Activations",
    "Sales Board", "WeekData", "Roll Call", "RollCallData", "Stations",
    "Commission", "Commission Calculator", "Rates", "Adjustments", "RAW",
    "Copy of Carlos PNL 2026", "Name Aliases", "NoRevPay", "New DU",
    "JE Sales by Store", "Report an Issue",
    "Lucy Wireless Churn", "Lucy New INT Churn",   # ours, but a DIFFERENT module's
)

# The visible log, in Carlos's own column order — read off the tab he showed on
# the Loom (his screenshot, columns A..Q). He said "mine's will have more
# columns than his [Raf's]"; this is the set he actually keeps. Every one of
# these is present in the 47-column export (verified by the 2026-07-19 probe),
# and they are looked up BY LABEL at write time, never by index.
DISPLAY_HEADERS = (
    "Rep",
    "sp.Order Date (copy)",
    "Customer Name",
    "Product Type (Broken Out)",
    "CRU/IRU",
    "DTR Status (enriched)",
    "DTR Status Date",
    "spe.TN",
    "spe.TN Type",
    "sp.SPM Number",
    "spe.Account BAN",
    "spe.Phone",
    "Wireless Installment Plan",
    "IF/OOF",
    "Package",
    "spe.Install Date",
    "Order date to Install Date Days",
)

# Friendlier headers for the view tab. Carlos reads this daily; "sp.Order Date
# (copy)" is a Tableau artefact, not a column name a human should have to parse.
# The hidden tab keeps the raw names so the mapping stays debuggable.
DISPLAY_LABELS = (
    "Rep", "Order Date", "Customer Name", "Product Type", "CRU/IRU",
    "Status", "Status Date", "TN", "TN Type", "SPM #", "Account BAN",
    "Phone", "Wireless Installment Plan", "IF/OOF", "Package",
    "Install Date", "Order->Install Days",
)

# The hidden tab adds a sort/filter key past the display slice.
DATA_HEADERS = DISPLAY_HEADERS + ("Filter Period",)

ALL_PERIODS = "All"
LAST_30 = "Last 30 Days"          # Carlos's Slack ask, 2026-07-19

CELL_REP = "B2"
CELL_PERIOD = "D2"       # both dropdowns share row 2 — see build_view_values

_COL_REP = DISPLAY_HEADERS.index("Rep")
_COL_ORDER_DATE = DISPLAY_HEADERS.index("sp.Order Date (copy)")
_COL_STATUS = DISPLAY_HEADERS.index("DTR Status (enriched)")
_COL_PERIOD = len(DISPLAY_HEADERS)          # "Filter Period"


def _col_letter(index0: int) -> str:
    s, n = "", index0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _rgb(hex_str: str) -> Dict[str, float]:
    h = hex_str.lstrip("#")
    return {"red": int(h[0:2], 16) / 255.0,
            "green": int(h[2:4], 16) / 255.0,
            "blue": int(h[4:6], 16) / 255.0}


def _parse_date(v) -> Optional[dt.date]:
    if not v:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _fmt_date(d: Optional[dt.date]) -> str:
    return "{}/{}/{}".format(d.month, d.day, d.year) if d else ""


def _open():
    return open_by_key(SHEET_ID)


def _ensure_tab(sh, title: str, *, hidden: bool = False, rows: int = 1000,
                cols: int = 26):
    try:
        ws = sh.worksheet(title)
    except Exception:  # noqa: BLE001 — gspread raises WorksheetNotFound
        ws = _retry(lambda: sh.add_worksheet(title=title, rows=rows, cols=cols))
    if hidden:
        try:
            _retry(lambda: sh.batch_update({"requests": [
                {"updateSheetProperties": {
                    "properties": {"sheetId": ws.id, "hidden": True},
                    "fields": "hidden"}}]}))
        except Exception:  # noqa: BLE001 — hiding is cosmetic, never fail on it
            pass
    return ws


def build_data_rows(lines: Sequence[dict], today: dt.date) -> List[List[str]]:
    """One row per sale, in DISPLAY_HEADERS order, plus the period key.

    Columns are pulled BY LABEL from each line dict — the export's column order
    is not a contract and has already changed shape once (17 visible in the
    screenshot vs 47 in the real download).
    """
    cutoff = today - dt.timedelta(days=30)
    out: List[List[str]] = []
    for ln in lines:
        row = [str(ln.get(h, "") or "").strip() for h in DISPLAY_HEADERS]
        od = _parse_date(ln.get("sp.Order Date (copy)"))
        # Period key drives the dropdown. Kept as its own column so the view's
        # FILTER can match a single cell instead of re-deriving dates in-sheet.
        row.append(LAST_30 if (od and od >= cutoff) else "")
        out.append(row)
    # Newest first, then by rep, so the log reads the way Carlos scrolls it.
    out.sort(key=lambda r: (_parse_date(r[_COL_ORDER_DATE]) or dt.date.min,
                            r[_COL_REP]), reverse=True)
    return out


def build_view_values(rows: Sequence[Sequence[str]], reps: Sequence[str],
                      generated: str, *, selected_rep: str = "",
                      selected_period: str = "") -> List[List[str]]:
    """The visible tab: title, dropdowns, status summary, then the log."""
    data = "'{}'".format(TAB_DATA)
    rep_cell = "${}${}".format(CELL_REP[0], CELL_REP[1:])
    per_cell = "${}${}".format(CELL_PERIOD[0], CELL_PERIOD[1:])

    # EVERY range starts at row 2. FILTER requires its condition ranges to be
    # the SAME HEIGHT as the source range; mixing $A$2:$Q (from row 2) with
    # $A:$A (from row 1) makes it error, IFERROR swallows the error, and the
    # tab renders a tidy "no orders match" on top of 1,354 perfectly good rows
    # — a silent failure that still exits 0 (observed live 2026-07-19 22:42).
    def _col(idx0: int) -> str:
        c = _col_letter(idx0)
        return "{}!${}$2:${}".format(data, c, c)

    rep_col = _col(_COL_REP)
    per_col = _col(_COL_PERIOD)
    stat_col = _col(_COL_STATUS)
    last_col = _col_letter(len(DISPLAY_HEADERS) - 1)
    body_rng = "{}!$A$2:${}".format(data, last_col)

    # One spilling FILTER. Conditions are built so "All" short-circuits to TRUE
    # rather than needing a separate formula per combination.
    rep_cond = '(({r}="{all}")+({rc}={r}))'.format(
        r=rep_cell, rc=rep_col, all=ALL_PERIODS)
    per_cond = '(({p}="{all}")+({pc}={p}))'.format(
        p=per_cell, pc=per_col, all=ALL_PERIODS)
    log_formula = ('=IFERROR(FILTER({body},{rep},{per}),'
                   '"— no orders match —")').format(
        body=body_rng, rep=rep_cond, per=per_cond)

    ncol = len(DISPLAY_HEADERS)
    # Live row count for the CURRENT selection. Carlos's first question of this
    # tab is "how much am I looking at" — making him read it off the scrollbar
    # is a large part of why it feels like a wall.
    showing = '=COUNTA(FILTER({b},{rep},{per}))'.format(
        b="{}!$A$2:$A".format(data), rep=rep_cond, per=per_cond)

    grid: List[List[str]] = []
    grid.append(["AT&T B2B Order Log"] + [""] * (ncol - 1))
    # Both dropdowns on ONE row, with the count beside them — three separate
    # header lines pushed the actual data further down for no benefit.
    grid.append(["Rep:", selected_rep or ALL_PERIODS,
                 "Period:", selected_period or LAST_30,
                 "Showing:", showing, "orders"] + [""] * (ncol - 7))
    grid.append(["Updated " + generated] + [""] * (ncol - 1))
    grid.append([""] * ncol)

    # Status summary — counts for the CURRENT dropdown selection, so the
    # numbers always describe what is on screen.
    statuses = sorted({r[_COL_STATUS] for r in rows if r[_COL_STATUS]})
    grid.append(["Status"] + list(statuses[:len(DISPLAY_HEADERS) - 1]))
    # SUMPRODUCT, not COUNTIFS. COUNTIFS needs a wildcard for the "All" case,
    # and "*" matches any TEXT cell — but Filter Period is EMPTY on anything
    # older than 30 days, so those rows were never counted and the summary
    # under-reported badly (Canceled showed 25 against 1,354 sales, live
    # 2026-07-19). SUMPRODUCT mirrors the FILTER's own boolean logic exactly,
    # so the summary and the log can never disagree.
    counts = []
    for s in statuses[:len(DISPLAY_HEADERS) - 1]:
        counts.append(
            '=SUMPRODUCT(({sc}="{s}")*({rep}>0)*({per}>0))'.format(
                sc=stat_col, s=s.replace('"', '""'),
                rep=rep_cond, per=per_cond))
    grid.append(["Count"] + counts)
    grid.append([""] * len(DISPLAY_HEADERS))

    grid.append(list(DISPLAY_LABELS))
    grid.append([log_formula] + [""] * (len(DISPLAY_HEADERS) - 1))
    return grid


HEADER_ROW = 8          # 1-based row of DISPLAY_LABELS in build_view_values
FIRST_LOG_ROW = 9       # where the FILTER spills


def _format_requests(view_id: int) -> List[dict]:
    ncol = len(DISPLAY_HEADERS)
    return [
        # Title
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 14}}},
            "fields": "userEnteredFormat.textFormat"}},
        # Column header row
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": HEADER_ROW - 1,
                      "endRowIndex": HEADER_ROW, "startColumnIndex": 0,
                      "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True},
                "backgroundColor": _rgb("#000000"),
                "horizontalAlignment": "CENTER"}},
            "fields": ("userEnteredFormat.textFormat,"
                       "userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.horizontalAlignment")}},
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": HEADER_ROW - 1,
                      "endRowIndex": HEADER_ROW, "startColumnIndex": 0,
                      "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {"textFormat": {
                "bold": True, "foregroundColor": _rgb("#FFFFFF")}}},
            "fields": "userEnteredFormat.textFormat"}},
        # Freeze the header + dropdowns so the log scrolls under them.
        {"updateSheetProperties": {
            "properties": {"sheetId": view_id, "gridProperties": {
                "frozenRowCount": HEADER_ROW}},
            "fields": "gridProperties.frozenRowCount"}},
        {"autoResizeDimensions": {"dimensions": {
            "sheetId": view_id, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": ncol}}},
    ] + _date_format_requests(view_id) + _density_requests(view_id)


# Columns that are reference data rather than things Carlos scans. autoResize
# lets these sprawl (Package strings run 40+ chars), which is most of why the
# tab reads as a wall. Capped, not hidden — he asked to KEEP the columns
# ("this tab is everything that should stay on here"), so narrowing is the
# right lever, and he can widen any of them by hand.
_NARROW_COLUMNS = {
    "spe.TN": 90, "spe.TN Type": 60, "spe.Account BAN": 100,
    "spe.Phone": 100, "Wireless Installment Plan": 110, "IF/OOF": 55,
    "Package": 150, "Order date to Install Date Days": 70,
    "sp.SPM Number": 100, "Customer Name": 130, "Rep": 120,
}
BAND_HEX = "#F3F6FA"      # very light blue; readable behind the status fills


def _density_requests(view_id: int) -> List[dict]:
    """Make 500+ rows scannable: smaller type, row banding, hairline borders,
    capped widths. Megan 2026-07-19: "It's a lot to look at.\""""
    ncol = len(DISPLAY_HEADERS)
    reqs: List[dict] = [
        # 10pt across the log — 11pt default plus 17 columns is what forces
        # horizontal scrolling before you have read a single row.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": FIRST_LOG_ROW - 1,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "textFormat": {"fontSize": 10},
                "verticalAlignment": "MIDDLE"}},
            "fields": ("userEnteredFormat.textFormat.fontSize,"
                       "userEnteredFormat.verticalAlignment")}},
        # Hairline grid so the eye can track across 17 columns.
        {"updateBorders": {
            "range": {"sheetId": view_id, "startRowIndex": HEADER_ROW - 1,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "innerHorizontal": {"style": "SOLID", "width": 1,
                                "color": _rgb("#D9D9D9")},
            "innerVertical": {"style": "SOLID", "width": 1,
                              "color": _rgb("#D9D9D9")}}},
    ]
    # Banding via conditional format on EVEN rows rather than addBanding: the
    # log is a spilling FILTER of unknown length, and a fixed banding range
    # would either stop short or paint empty rows below the data.
    reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [{"sheetId": view_id, "startRowIndex": FIRST_LOG_ROW - 1,
                    "startColumnIndex": 0, "endColumnIndex": ncol}],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [
                {"userEnteredValue":
                 '=AND($A{r}<>"",ISEVEN(ROW()))'.format(r=FIRST_LOG_ROW)}]},
            "format": {"backgroundColor": _rgb(BAND_HEX)}}}}})
    for label, px in _NARROW_COLUMNS.items():
        if label not in DISPLAY_HEADERS:
            continue
        c = DISPLAY_HEADERS.index(label)
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": c, "endIndex": c + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    return reqs


# Columns that hold dates, resolved BY LABEL so a column reorder can't turn
# this into "format whatever is in position 1".
_DATE_COLUMNS = ("sp.Order Date (copy)", "DTR Status Date", "spe.Install Date")


def _date_format_requests(view_id: int) -> List[dict]:
    """Force a date format on the date columns of the VIEW tab.

    The hidden tab stores these correctly — writing with USER_ENTERED lets
    Sheets parse "07/18/2026" into a real date, which is what we want for
    sorting. But the view is a spilling FILTER, and FILTER output carries the
    VALUE without the source cell's format, so those cells rendered as raw
    serials: every Order Date showed "46221" instead of 7/18/2026 (observed
    live 2026-07-19). Formatting the destination columns fixes it; converting
    the dates to text would too, but would break date sorting.
    """
    reqs = []
    for label in _DATE_COLUMNS:
        if label not in DISPLAY_HEADERS:
            continue
        c = DISPLAY_HEADERS.index(label)
        reqs.append({"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": FIRST_LOG_ROW - 1,
                      "startColumnIndex": c, "endColumnIndex": c + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {
                "type": "DATE", "pattern": "m/d/yyyy"}}},
            "fields": "userEnteredFormat.numberFormat"}})
    return reqs


def _validation(view_id: int, reps: Sequence[str],
                periods: Sequence[str]) -> List[dict]:
    """Dropdowns at B2 (rep) and D2 (period) — both on the header row."""
    def rule(col0: int, values: Sequence[str]) -> dict:
        return {"setDataValidation": {
            "range": {"sheetId": view_id, "startRowIndex": 1,
                      "endRowIndex": 2, "startColumnIndex": col0,
                      "endColumnIndex": col0 + 1},
            "rule": {"condition": {
                "type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": v} for v in values]},
                "showCustomUi": True, "strict": False}}}
    return [rule(1, [ALL_PERIODS] + list(reps)),        # B2
            rule(3, [ALL_PERIODS] + list(periods))]     # D2


def _status_color_rules(view_id: int) -> List[dict]:
    """Colour the Status column by Carlos's rule.

    One rule per colour rather than per status, matched with a REGEX over the
    statuses that share it — 15 statuses would otherwise be 15 rules, and
    Sheets applies conditional formats in order, so fewer rules is both faster
    and easier to reason about.
    """
    ncol = len(DISPLAY_HEADERS)
    by_color: Dict[str, List[str]] = collections.defaultdict(list)
    for status, color in colors.STATUS_COLORS.items():
        by_color[color].append(status)

    reqs, idx = [], 0
    scol = _COL_STATUS
    for color, statuses in by_color.items():
        pattern = "(?i)^(" + "|".join(sorted(statuses)) + ")$"
        reqs.append({"addConditionalFormatRule": {"index": idx, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": FIRST_LOG_ROW - 1,
                        "startColumnIndex": scol, "endColumnIndex": scol + 1}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue":
                                          '=REGEXMATCH(${c}{r},"{p}")'.format(
                                              c=_col_letter(scol),
                                              r=FIRST_LOG_ROW, p=pattern)}]},
                "format": {"backgroundColor": _rgb(colors.FILL_HEX[color])}}}}})
        idx += 1
    return reqs


def _clear_color_rules(sh, view_id: int) -> List[dict]:
    """Delete existing conditional formats so repeated runs don't stack them."""
    try:
        meta = _retry(lambda: sh.fetch_sheet_metadata())
    except Exception:  # noqa: BLE001
        return []
    n = 0
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") == view_id:
            n = len(s.get("conditionalFormats", []) or [])
            break
    return [{"deleteConditionalFormatRule": {"sheetId": view_id, "index": 0}}
            for _ in range(n)]


def push(lines: Sequence[dict], *, today: Optional[dt.date] = None,
         generated: Optional[str] = None, log=print) -> Dict[str, object]:
    """Write the hidden data tab and repaint the view tab."""
    if TAB_VIEW in PROTECTED_TABS or TAB_DATA in PROTECTED_TABS:
        raise RuntimeError("refusing to write: target tab is protected")

    today = today or dt.date.today()
    generated = generated or dt.datetime.now().strftime("%m/%d/%Y %I:%M %p").lstrip("0")
    sh = _open()

    rows = build_data_rows(lines, today)
    if not rows:
        raise RuntimeError("no rows to write — refusing to blank the tab")

    # Surface any status we have no colour for, rather than rendering it white.
    unknown = colors.unmapped(r[_COL_STATUS] for r in rows)
    if unknown:
        log("  !! UNMAPPED statuses (rendering uncoloured): {}".format(
            ", ".join(sorted(unknown))))

    # ---- hidden data tab -------------------------------------------------
    data_ws = _ensure_tab(sh, TAB_DATA, hidden=True, cols=len(DATA_HEADERS))
    _retry(lambda: data_ws.resize(rows=max(1000, len(rows) + 50),
                                  cols=len(DATA_HEADERS)))
    _retry(lambda: data_ws.clear())
    body = [list(DATA_HEADERS)] + [list(r) for r in rows]
    _retry(lambda: data_ws.update(
        body, "A1:{}{}".format(_col_letter(len(DATA_HEADERS) - 1), len(body)),
        value_input_option="USER_ENTERED"))
    log("  hidden data tab: {} sales".format(len(rows)))

    # ---- view tab --------------------------------------------------------
    view_ws = _ensure_tab(sh, TAB_VIEW, cols=len(DISPLAY_HEADERS))
    reps = sorted({r[_COL_REP] for r in rows if r[_COL_REP]})
    periods = [LAST_30]

    # Keep whatever Carlos currently has selected so a morning refresh doesn't
    # yank the view out from under him.
    def _current(cell):
        try:
            return (_retry(lambda: view_ws.acell(cell).value) or "").strip()
        except Exception:  # noqa: BLE001
            return ""
    cur_rep, cur_per = _current(CELL_REP), _current(CELL_PERIOD)
    sel_rep = cur_rep if cur_rep in [ALL_PERIODS] + reps else ALL_PERIODS
    # Default to LAST 30 DAYS, not All. The pull is a 60-day window and 846 of
    # 1,354 orders are older than 30 days — opening on "All" means the tab
    # greets Carlos with ~1,350 rows, most of them stale. His own selection is
    # still preserved across runs; this only changes the cold-start default.
    sel_per = cur_per if cur_per in [ALL_PERIODS] + periods else LAST_30

    grid = build_view_values(rows, reps, generated,
                             selected_rep=sel_rep, selected_period=sel_per)
    _retry(lambda: view_ws.clear())
    _retry(lambda: view_ws.update(
        grid, "A1:{}{}".format(_col_letter(len(DISPLAY_HEADERS) - 1), len(grid)),
        value_input_option="USER_ENTERED"))

    reqs: List[dict] = []
    reqs += _clear_color_rules(sh, view_ws.id)
    reqs += _format_requests(view_ws.id)
    reqs += _validation(view_ws.id, reps, periods)
    reqs += _status_color_rules(view_ws.id)
    _retry(lambda: sh.batch_update({"requests": reqs}))

    log("  view tab: {} reps in the dropdown".format(len(reps)))
    return {"sales": len(rows), "reps": len(reps), "unmapped": sorted(unknown)}

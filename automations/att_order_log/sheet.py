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

# Per-line measures from the un-pivot. NOT in the visible log — Carlos's 17
# columns are what he asked to see — but carried on the hidden tab so the rep
# box can compute activation % without a second Tableau pull. Each is an
# indicator on a line (probe 2026-07-19: values 1/1/0/0), so summing them per
# rep is the whole calculation.
MEASURE_UNITS = "Unit Count"
MEASURE_ACTIVATIONS = "Total Activations"
MEASURES = (MEASURE_UNITS, "Total Volume", MEASURE_ACTIVATIONS,
            "Sales (All)  (non pmts) (60-120)")

# The hidden tab adds the measures + a sort/filter key past the display slice.
DATA_HEADERS = DISPLAY_HEADERS + MEASURES + ("Filter Period",)

ALL_PERIODS = "All"
LAST_30 = "Last 30 Days"          # Carlos's Slack ask, 2026-07-19

CELL_REP = "B2"
CELL_PERIOD = "D2"       # both dropdowns share row 2 — see build_view_values

_COL_REP = DISPLAY_HEADERS.index("Rep")
_COL_ORDER_DATE = DISPLAY_HEADERS.index("sp.Order Date (copy)")
_COL_STATUS = DISPLAY_HEADERS.index("DTR Status (enriched)")
_COL_UNITS = DATA_HEADERS.index(MEASURE_UNITS)
_COL_ACTIVATIONS = DATA_HEADERS.index(MEASURE_ACTIVATIONS)
_COL_PERIOD = DATA_HEADERS.index("Filter Period")


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
        row += [str(ln.get(m, "") or "").strip() for m in MEASURES]
        od = _parse_date(ln.get("sp.Order Date (copy)"))
        # Period key drives the dropdown. Kept as its own column so the view's
        # FILTER can match a single cell instead of re-deriving dates in-sheet.
        row.append(LAST_30 if (od and od >= cutoff) else "")
        out.append(row)
    # Newest first, then by rep, so the log reads the way Carlos scrolls it.
    out.sort(key=lambda r: (_parse_date(r[_COL_ORDER_DATE]) or dt.date.min,
                            r[_COL_REP]), reverse=True)
    return out


# A whole data-tab column, anchored from ROW 2. FILTER requires its condition
# ranges to be the SAME HEIGHT as the source range; mixing $A$2:$Q (from row 2)
# with $A:$A (from row 1) makes it error, IFERROR swallows it, and the tab
# renders "no orders match" over 1,354 good rows — silent, still exit 0
# (observed 2026-07-19). Module-level so both the log and the rep box use it.
def _col(idx0: int) -> str:
    c = _col_letter(idx0)
    return "'{}'!${}$2:${}".format(TAB_DATA, c, c)


def _conditions():
    """(rep_col, per_col, stat_col, rep_cond, per_cond) — the FILTER building
    blocks shared by the log and the rep box, so the two can never disagree
    about which rows the current dropdown selection includes."""
    rep_cell = "${}${}".format(CELL_REP[0], CELL_REP[1:])
    per_cell = "${}${}".format(CELL_PERIOD[0], CELL_PERIOD[1:])
    rep_col, per_col, stat_col = (_col(_COL_REP), _col(_COL_PERIOD),
                                  _col(_COL_STATUS))
    rep_cond = '(({r}="{all}")+({rc}={r}))'.format(
        r=rep_cell, rc=rep_col, all=ALL_PERIODS)
    per_cond = '(({p}="{all}")+({pc}={p}))'.format(
        p=per_cell, pc=per_col, all=ALL_PERIODS)
    return rep_col, per_col, stat_col, rep_cond, per_cond


def build_view_values(rows: Sequence[Sequence[str]], reps: Sequence[str],
                      generated: str, *, selected_rep: str = "",
                      selected_period: str = "") -> List[List[str]]:
    """The visible tab: title, dropdowns, status summary, then the log."""
    data = "'{}'".format(TAB_DATA)
    rep_cell = "${}${}".format(CELL_REP[0], CELL_REP[1:])
    per_cell = "${}${}".format(CELL_PERIOD[0], CELL_PERIOD[1:])

    rep_col, per_col, stat_col, rep_cond, per_cond = _conditions()
    last_col = _col_letter(len(DISPLAY_HEADERS) - 1)
    body_rng = "{}!$A$2:${}".format(data, last_col)

    # One spilling FILTER. Conditions short-circuit "All" to TRUE.
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
    grid.append([""] * ncol)

    grid.append(list(DISPLAY_LABELS))
    grid.append([log_formula] + [""] * (ncol - 1))
    return grid


# The rep box is a spilling formula of unknown height, so its formatting rules
# cover a GENEROUS fixed extent below the header rather than a rep count.
REPBOX_ROWS = 300


def repbox_formula() -> str:
    """ONE spilling formula for the whole rep box, sorted by activation %
    DESCENDING and re-sorting LIVE when the dropdowns change (Megan 2026-07-20:
    the build-time sort "didn't carry" when she switched to Last 30 Days).

    Per rep, over the current B2 (rep) + D2 (period) selection: orders, total
    activations, and % = activations/units. Reps with no orders in the window
    drop out (FILTER ord>0). SORT(..,4,FALSE) orders by % desc, so a dropdown
    change recomputes AND re-sorts on its own.

    Conditions are INLINED with direct range refs, NOT a precomputed LET array:
    referencing a computed array variable inside MAP's LAMBDA throws #VALUE!
    (verified live 2026-07-20); direct range refs inside the lambda work.
    """
    d = "'{}'".format(TAB_DATA)
    A = "{}!$A$2:$A".format(d)                 # Rep
    R = "{}!$R$2:$R".format(d)                 # Unit Count
    T = "{}!$T$2:$T".format(d)                 # Total Activations
    V = "{}!$V$2:$V".format(d)                 # Filter Period
    cond = ('(($B$2="{all}")+({A}=$B$2))*(($D$2="{all}")+({V}=$D$2))'
            ).format(all=ALL_PERIODS, A=A, V=V)
    return ('=LET('
            'ur,UNIQUE(FILTER({A},{A}<>"")),'
            'ord,MAP(ur,LAMBDA(r,SUMPRODUCT(({A}=r)*{cond}))),'
            'ac,MAP(ur,LAMBDA(r,SUMPRODUCT(({A}=r)*{cond}*N({T})))),'
            'un,MAP(ur,LAMBDA(r,SUMPRODUCT(({A}=r)*{cond}*N({R})))),'
            'pct,MAP(ac,un,LAMBDA(a,u,IF(u=0,-1,a/u))),'
            'tbl,HSTACK(ur,ord,ac,pct),'
            'IFERROR(SORT(FILTER(tbl,ord>0),4,FALSE),""))'
            ).format(A=A, R=R, T=T, cond=cond)


def build_repbox_values() -> List[List[str]]:
    """Rep box = header row + ONE spilling live-sort formula (Rep|Orders|
    Activations|%). Formula-driven now, so it re-sorts when the dropdowns
    change and push() writes it once instead of a row per rep."""
    return [["Rep", "Orders", "Activations", "Activation %"],
            [repbox_formula(), "", "", ""]]


# The log header is a FIXED 8 rows now (title, controls, updated, blank, status
# header, status count, blank, column labels) — the rep box no longer lives
# above the log, so this can't drift with the rep count.
HEADER_ROW = 8          # 1-based row of DISPLAY_LABELS
FIRST_LOG_ROW = 9       # where the FILTER spills

# The rep box lives to the RIGHT of the log's 17 columns, after one gap column.
REPBOX_COL0 = len(DISPLAY_HEADERS) + 1     # 0-based: column S (index 18)
# Header sits on the SAME row as the log's column-label row (the last frozen
# row), so the rep-box header stays visible and the box is NOT bisected by the
# 8-row freeze (Megan 2026-07-20: "the right side chart is frozen at a weird
# spot"). Rep rows then begin at row 9, entirely in the scroll zone.
REPBOX_HEADER_ROW0 = HEADER_ROW - 1        # 0-based row 7 == sheet row 8
REPBOX_PCT_COL = REPBOX_COL0 + 3           # "Activation %" column




# --- header palette -------------------------------------------------------
# Megan 2026-07-19: "change the colors of the sheet (not the orders part) to be
# more aesthetic". Her hand-styled version had a blue title, a yellow Updated
# bar, a pink Status block and a light-blue spacer — four unrelated hues
# competing above the data. This is one family instead: a deep navy anchor, two
# tints of the same blue-grey stepping down, and white gutters. It reads as a
# single frame around the log rather than a stack of coloured bars, and it stays
# out of the way of the green/yellow/red that carry meaning in the rows.
NAVY = "#1C3A5E"        # title + column headers — the anchor
SLATE = "#E4EAF1"       # control row (dropdowns)
MIST = "#F2F5F9"        # status/count block — one step lighter than SLATE
INK = "#2E4057"         # body text on the light tints
MUTED = "#7A8A9A"       # the "Updated" timestamp — present, not shouting


def _format_requests(view_id: int) -> List[dict]:
    ncol = len(DISPLAY_HEADERS)
    return [
        # Title — merged across A:H (Megan's merge, preserved below).
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(NAVY),
                "verticalAlignment": "MIDDLE",
                "textFormat": {"bold": True, "fontSize": 14,
                               "foregroundColor": _rgb("#FFFFFF")}}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.verticalAlignment,"
                       "userEnteredFormat.textFormat")}},
        # Control row — dropdowns + live count.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": 1, "endRowIndex": 2,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(SLATE),
                "verticalAlignment": "MIDDLE",
                "textFormat": {"bold": True, "fontSize": 11,
                               "foregroundColor": _rgb(INK)}}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.verticalAlignment,"
                       "userEnteredFormat.textFormat")}},
        # "Updated …" — muted, italic. It is provenance, not a headline; the
        # yellow bar made it the loudest thing on the tab.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": 2, "endRowIndex": 3,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb("#FFFFFF"),
                "textFormat": {"bold": False, "italic": True, "fontSize": 9,
                               "foregroundColor": _rgb(MUTED)}}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.textFormat")}},
        # Status + Count block.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": 4, "endRowIndex": 6,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(MIST),
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 10,
                               "foregroundColor": _rgb(INK)}}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.horizontalAlignment,"
                       "userEnteredFormat.textFormat")}},
        # Left-align the two row labels in that block.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": 4, "endRowIndex": 6,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
            "fields": "userEnteredFormat.horizontalAlignment"}},
        # Column header row — same navy as the title, so the frame closes.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": HEADER_ROW - 1,
                      "endRowIndex": HEADER_ROW, "startColumnIndex": 0,
                      "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(NAVY),
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
                "textFormat": {"bold": True, "fontSize": 10,
                               "foregroundColor": _rgb("#FFFFFF")}}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.horizontalAlignment,"
                       "userEnteredFormat.verticalAlignment,"
                       "userEnteredFormat.wrapStrategy,"
                       "userEnteredFormat.textFormat")}},
        # Freeze the header + dropdowns so the log scrolls under them.
        {"updateSheetProperties": {
            "properties": {"sheetId": view_id, "gridProperties": {
                "frozenRowCount": HEADER_ROW}},
            "fields": "gridProperties.frozenRowCount"}},
        {"autoResizeDimensions": {"dimensions": {
            "sheetId": view_id, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": ncol}}},
    ] + _merge_requests(view_id) + _date_format_requests(view_id) \
      + _density_requests(view_id) + _summary_border_requests(view_id)


def _summary_border_requests(view_id: int) -> List[dict]:
    """Box the two summary tables (Megan 2026-07-20: "put in some borders to the
    charts"). A solid outer border + light inner grid on the Status/Count block
    (rows 5-6) and the rep box (S:V) makes each read as a distinct table rather
    than floating cells. The log itself already has its own grid."""
    solid = {"style": "SOLID", "width": 1, "color": _rgb("#5A6B7B")}
    thin = {"style": "SOLID", "width": 1, "color": _rgb("#B7C2CE")}
    reqs = []
    # Status summary: rows 5-6 (0-based 4-6), cols A..Q.
    reqs.append({"updateBorders": {
        "range": {"sheetId": view_id, "startRowIndex": 4, "endRowIndex": 6,
                  "startColumnIndex": 0, "endColumnIndex": len(DISPLAY_HEADERS)},
        "top": solid, "bottom": solid, "left": solid, "right": solid,
        "innerHorizontal": thin, "innerVertical": thin}})
    return reqs


def _repbox_border_requests(view_id: int, n_reps: int) -> List[dict]:
    """Box the rep box, sized to the current roster, run EVERY day (Megan
    2026-07-20: a new rep should be bordered automatically). Clears the generous
    extent first so a shrunk roster leaves no stray borders, then boxes header +
    n_reps rows. Scoped to the rep-box columns only, so nothing else Megan
    formatted is touched."""
    if n_reps <= 0:
        return []
    none = {"style": "NONE"}
    solid = {"style": "SOLID", "width": 1, "color": _rgb("#5A6B7B")}
    thin = {"style": "SOLID", "width": 1, "color": _rgb("#B7C2CE")}
    full = {"sheetId": view_id, "startRowIndex": REPBOX_HEADER_ROW0,
            "endRowIndex": REPBOX_HEADER_ROW0 + 1 + REPBOX_ROWS,
            "startColumnIndex": REPBOX_COL0, "endColumnIndex": REPBOX_COL0 + 4}
    box = {"sheetId": view_id, "startRowIndex": REPBOX_HEADER_ROW0,
           "endRowIndex": REPBOX_HEADER_ROW0 + 1 + n_reps,
           "startColumnIndex": REPBOX_COL0, "endColumnIndex": REPBOX_COL0 + 4}
    return [
        {"updateBorders": {"range": full, "top": none, "bottom": none,
                           "left": none, "right": none,
                           "innerHorizontal": none, "innerVertical": none}},
        {"updateBorders": {"range": box, "top": solid, "bottom": solid,
                           "left": solid, "right": solid,
                           "innerHorizontal": thin, "innerVertical": thin}},
    ]


# Megan merged the title and the "Updated" line across A:H by hand
# (2026-07-19). Re-created here so a rebuild restores them instead of quietly
# dropping her layout — clear() leaves merges alone, but a tab rebuilt from
# scratch would lose them. mergeType MERGE_ALL matches what she applied.
_MERGE_ROWS = ((0, 1), (2, 3))     # title row, updated row (0-based, end-excl)
_MERGE_COLS = (0, 22)              # A:V — Megan widened these 2026-07-20


def _merge_requests(view_id: int) -> List[dict]:
    reqs: List[dict] = []
    for r0, r1 in _MERGE_ROWS:
        rng = {"sheetId": view_id, "startRowIndex": r0, "endRowIndex": r1,
               "startColumnIndex": _MERGE_COLS[0],
               "endColumnIndex": _MERGE_COLS[1]}
        # Unmerge first: merging an already-merged range errors, and the run
        # must be idempotent.
        reqs.append({"unmergeCells": {"range": rng}})
        reqs.append({"mergeCells": {"range": rng, "mergeType": "MERGE_ALL"}})
    return reqs


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
    """Dropdowns at B2 (rep) and D2 (period) — both on the header row.

    CLEARS the whole header block first. Data validation is not removed by
    clear() or by writing new values, so a dropdown left at a cell we have
    since moved away from just stays there: when the period control moved from
    B3 to D2, B3 kept its "All / Last 30 Days" list and the tab showed the same
    choice twice (Megan spotted it 2026-07-19). Wiping rows 1-8 and re-adding
    exactly the two we want makes the run self-correcting, so any future move
    cannot strand another orphan.
    """
    ncol = len(DISPLAY_HEADERS)
    reqs: List[dict] = [{"setDataValidation": {
        "range": {"sheetId": view_id, "startRowIndex": 0,
                  "endRowIndex": HEADER_ROW, "startColumnIndex": 0,
                  "endColumnIndex": ncol}}}]      # no rule = clear

    def rule(col0: int, values: Sequence[str]) -> dict:
        return {"setDataValidation": {
            "range": {"sheetId": view_id, "startRowIndex": 1,
                      "endRowIndex": 2, "startColumnIndex": col0,
                      "endColumnIndex": col0 + 1},
            "rule": {"condition": {
                "type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": v} for v in values]},
                "showCustomUi": True, "strict": False}}}
    reqs.append(rule(1, [ALL_PERIODS] + list(reps)))        # B2 — rep
    reqs.append(rule(3, [ALL_PERIODS] + list(periods)))     # D2 — period
    return reqs


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
        # WHOLE ROW, not just the Status cell (Megan 2026-07-19). The range
        # spans every column; the formula pins the COLUMN ($F) and leaves the
        # ROW relative, so each row is tested against its own status and the
        # fill carries across all 17 columns.
        reqs.append({"addConditionalFormatRule": {"index": idx, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": FIRST_LOG_ROW - 1,
                        "startColumnIndex": 0, "endColumnIndex": ncol}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue":
                                          '=REGEXMATCH(${c}{r},"{p}")'.format(
                                              c=_col_letter(scol),
                                              r=FIRST_LOG_ROW, p=pattern)}]},
                "format": {"backgroundColor": _rgb(colors.FILL_HEX[color])}}}}})
        idx += 1
    return reqs


def _repbox_color_rules(view_id: int, n_reps: int) -> List[dict]:
    """Carlos's activation thresholds on the rep box.

    Slack 2026-07-19, verbatim: "Anything under 70% is red / 70% to 75% is
    yellow / Anything above 75% is green."

    Boundaries follow his wording literally: 70 and 75 are INSIDE the yellow
    band ("70% to 75% is yellow"), so red is strictly < 0.70 and green strictly
    > 0.75. Yellow is the BETWEEN rule and needs no explicit bounds check — it
    is registered last, so anything the other two did not claim lands there.

    Values are fractions (0.72), not 72 — the cell holds activations/units, and
    a percent NUMBER FORMAT is applied separately.
    """
    if n_reps <= 0:
        return []
    # Rep box lives to the RIGHT now; the Activation % column is REPBOX_PCT_COL,
    # rows start one below the box header.
    first = REPBOX_HEADER_ROW0 + 1
    rng = {"sheetId": view_id, "startRowIndex": first,
           "endRowIndex": first + REPBOX_ROWS,
           "startColumnIndex": REPBOX_PCT_COL,
           "endColumnIndex": REPBOX_PCT_COL + 1}

    def rule(idx, cond_type, values, hexcolor):
        return {"addConditionalFormatRule": {"index": idx, "rule": {
            "ranges": [dict(rng)],
            "booleanRule": {
                "condition": {"type": cond_type,
                              "values": [{"userEnteredValue": v}
                                         for v in values]},
                "format": {"backgroundColor": _rgb(hexcolor),
                           "textFormat": {"bold": True}}}}}}

    return [
        rule(0, "NUMBER_LESS", ["0.7"], colors.FILL_HEX[colors.RED]),
        rule(1, "NUMBER_GREATER", ["0.75"], colors.FILL_HEX[colors.GREEN]),
        rule(2, "NUMBER_BETWEEN", ["0.7", "0.75"],
             colors.FILL_HEX[colors.YELLOW]),
    ]


def _repbox_format_requests(view_id: int, n_reps: int) -> List[dict]:
    """Percent format + a header style for the rep box."""
    if n_reps <= 0:
        return []
    c0 = REPBOX_COL0
    hdr = REPBOX_HEADER_ROW0
    return [
        # Box header row (Rep | Orders | Activations | Activation %) — navy, to
        # match the log's own header so the two blocks read as one sheet.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": hdr,
                      "endRowIndex": hdr + 1, "startColumnIndex": c0,
                      "endColumnIndex": c0 + 4},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _rgb(NAVY),
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 10,
                               "foregroundColor": _rgb("#FFFFFF")}}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.horizontalAlignment,"
                       "userEnteredFormat.textFormat")}},
        # Percent format on the Activation % column.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": hdr + 1,
                      "endRowIndex": hdr + 1 + REPBOX_ROWS,
                      "startColumnIndex": REPBOX_PCT_COL,
                      "endColumnIndex": REPBOX_PCT_COL + 1},
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "PERCENT", "pattern": "0.0%"},
                "horizontalAlignment": "CENTER"}},
            "fields": ("userEnteredFormat.numberFormat,"
                       "userEnteredFormat.horizontalAlignment")}},
        # Rep NAME column: left, no-wrap, 10pt — long names were wrapping to two
        # lines and making the row heights ragged (Megan 2026-07-20: "text
        # formatting is all over the place").
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": hdr + 1,
                      "endRowIndex": hdr + 1 + REPBOX_ROWS,
                      "startColumnIndex": c0, "endColumnIndex": c0 + 1},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "LEFT", "wrapStrategy": "CLIP",
                "textFormat": {"fontSize": 10}}},
            "fields": ("userEnteredFormat.horizontalAlignment,"
                       "userEnteredFormat.wrapStrategy,"
                       "userEnteredFormat.textFormat")}},
        # Orders + Activations columns: centered numbers.
        {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": hdr + 1,
                      "endRowIndex": hdr + 1 + REPBOX_ROWS,
                      "startColumnIndex": c0 + 1, "endColumnIndex": c0 + 3},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER",
                                           "textFormat": {"fontSize": 10}}},
            "fields": ("userEnteredFormat.horizontalAlignment,"
                       "userEnteredFormat.textFormat")}},
        # Widen the NAME column so full names fit; number cols stay tight.
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": c0, "endIndex": c0 + 1},
            "properties": {"pixelSize": 185}, "fields": "pixelSize"}},
    ]


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
         generated: Optional[str] = None, reformat: bool = False,
         log=print) -> Dict[str, object]:
    """Write the hidden data tab and refresh the view tab's VALUES.

    reformat=False (DEFAULT): refresh data + formulas only, and DO NOT re-apply
    any visual formatting. Megan hand-formats this tab (borders, merges,
    colours, 2026-07-20) and the daily run must not clobber it. Updating a
    cell's VALUE keeps its FORMAT, so the log/rep-box formulas refresh while her
    presentation survives. The view is almost entirely FILTER/SUMPRODUCT
    formulas that recompute off the hidden tab, so daily there is nothing to
    reformat anyway.

    reformat=True: also apply the code's full formatting (borders, freeze,
    merges, threshold colours). For a first build of an empty tab, or a
    deliberate reset — NOT the daily run. It WILL overwrite manual formatting.
    """
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
    # Rep box is a single live-sort formula now — re-sorts itself when the
    # dropdowns change, so no build-time ordering needed.
    repbox = build_repbox_values()

    # Write VALUES in place. No clear() of the whole tab — updating a value
    # keeps the cell's format, so Megan's formatting is preserved. The log's
    # FILTER (A9) governs its own spill, so we never write the log rows.
    _retry(lambda: view_ws.update(
        grid, "A1:{}{}".format(_col_letter(len(DISPLAY_HEADERS) - 1), len(grid)),
        value_input_option="USER_ENTERED"))
    # Rep box: the data area (below the header) MUST be cleared before the
    # live-sort formula is written — any leftover static rows in its spill path
    # would make it #SPILL. Values only, so Megan's formatting on the box stays.
    c0, c3 = _col_letter(REPBOX_COL0), _col_letter(REPBOX_COL0 + 3)
    _retry(lambda: view_ws.batch_clear(
        ["{c}{r}:{c2}{r2}".format(c=c0, r=REPBOX_HEADER_ROW0 + 2, c2=c3,
                                  r2=REPBOX_HEADER_ROW0 + 400)]))
    box_a1 = "{c}{r}:{c2}{r2}".format(
        c=c0, r=REPBOX_HEADER_ROW0 + 1, c2=c3,
        r2=REPBOX_HEADER_ROW0 + len(repbox))
    _retry(lambda: view_ws.update(repbox, box_a1,
                                  value_input_option="USER_ENTERED"))

    if reformat:
        reqs: List[dict] = []
        reqs += _clear_color_rules(sh, view_ws.id)
        reqs += _format_requests(view_ws.id)
        reqs += _repbox_format_requests(view_ws.id, len(reps))
        reqs += _validation(view_ws.id, reps, periods)
        # Rep-box thresholds BEFORE the row-status rules: both register at
        # index 0, so the last added wins — the activation colour must own its
        # cell rather than be painted over by the row's status fill.
        reqs += _status_color_rules(view_ws.id)
        reqs += _repbox_color_rules(view_ws.id, len(reps))
        reqs += _repbox_border_requests(view_ws.id, len(reps))
        _retry(lambda: sh.batch_update({"requests": reqs}))
        log("  view tab: reformatted ({} reps)".format(len(reps)))
    else:
        # Refresh the dropdown VALIDATION (a new rep must be pickable) AND
        # restore the title/updated MERGES. Writing grid values into the merged
        # rows (title row 1, updated row 3) breaks those merges — the value
        # write drops them (Megan 2026-07-20: merges gone after a value-only
        # run). Re-applying just the merges — captured at her A:V width — puts
        # them back WITHOUT touching borders/colours, so her look is restored,
        # not clobbered. Validation + merges are structural, not the visual
        # formatting she owns.
        # Validation + merges (structural, restored) + the rep-box border sized
        # to the roster, so a NEW rep is auto-bordered (Megan 2026-07-20). All
        # scoped so her borders/colours elsewhere are untouched.
        keep = _validation(view_ws.id, reps, periods) \
            + _merge_requests(view_ws.id) \
            + _repbox_border_requests(view_ws.id, len(reps))
        _retry(lambda: sh.batch_update({"requests": keep}))
        log("  view tab: data refreshed; merges + rep-box borders applied, "
            "formatting preserved ({} reps)".format(len(reps)))
    return {"sales": len(rows), "reps": len(reps), "unmapped": sorted(unknown)}

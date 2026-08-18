"""Build a per-office sales board that looks like Raf's.

The goal is that Raf opens his new board and does not notice a difference
(Megan 2026-08-17). So the layout, the labels, the colours, the fonts and the
frozen panes are all taken from his live sheet rather than designed — read off
`Sales Board WE 8.23` on 2026-08-17:

  * three header rows, frozen, with 3 frozen columns
  * row 1  banner: RUNNING WEEK TOTALS / LAST WEEK'S TOTALS (#CC0000) / the day
    names, Georgia bold white
  * row 3  columns: `#` (Arial 14 bold) then the week label, then the products,
    each on its own fill — INT #660000, INT UP #783F04, DTV #20124D,
    NL #073763, EN #274E13, Cx #BF9000 — Georgia bold, white text
  * his labels: "Total Apps" this week, "APPS" last week. Not renamed.

THREE things are deliberately different, because they are defects rather than
style, and every one of them is invisible to someone reading the board:

  1. tenure and status come OUT of the rep's name. "Anthony Vargas (Wk 2)"
     means somebody bumps it every Monday and the suffix breaks name matching
     against Tableau; here they are their own columns.
  2. markers (X / T / RT) come out of the number cells and live in Roll Call,
     so a count no longer has to filter text out of a numeric column.
  3. the LAST-WEEK average columns are not reproduced. His divide last week's
     units by THIS week's headcount (`=$K/CI`), reading 65.40 where the truth
     is 7.52.

TWO TABS:

  Teams             one row per team: the weekly goal the owner sets, plus that
                    team's stats. Goals are per office — a 25-rep team and a
                    200-rep team do not share a target.
  Sales Board WE …  one per week, AND the record of who was on the team that
                    week: identity, this week by product, last week's total,
                    then every day broken out by product with its Roll Call.

No roster tab: the week tab already names every rep with their team, level,
tenure and status, and a roster beside it would be the same person listed
twice. A new week carries forward from the PREVIOUS WEEK'S TAB, which is also
the truer record — last week's tab says who was on the team last week.

    python -m automations.icd_sales_board.new_sheet            # dry run
    python -m automations.icd_sales_board.new_sheet --write
    python -m automations.icd_sales_board.new_sheet --sync-new-reps --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# The blank workbook Megan made for this (2026-08-17).
SHEET_ID = "1gtQpfZT4vNCTWsl1snRUclSQ_I6086iKUS3R_HyF_iY"
# Raf's board, read-only — the source of rep names until each office's own
# board is live. Kept here rather than imported from site.py so this module
# never drags Streamlit into a batch run.
SOURCE_SHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"

TEAMS_TAB = "Teams"
DAYS = ["MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"]

# Products in his order, with his header fills.
PRODUCTS = [
    ("Total Apps", None),        # no fill on his board
    ("INT", "#660000"),
    ("INT UP", "#783F04"),
    ("DTV", "#20124D"),
    ("NL", "#073763"),
    ("EN", "#274E13"),
    ("Cx", "#BF9000"),
]
PRODUCT_NAMES = [p for p, _ in PRODUCTS]
DAY_PRODUCTS = ["Apps", "Int", "Int Up", "DTV", "NL", "EN", "Cx"]
ROLL_CALL = "Roll Call"

# Identity. '#' and the rep name sit where his are; the three columns that were
# buried in the name on his board get their own headers here.
# HIS ORDER: `#`, the rep, then the three week blocks, then the days, and every
# rep attribute out at the end. Production sits next to the name because that
# is what the board is read for; who someone is comes second.
# Column A is his narrow marker column, kept so the frozen block is 3 wide as
# on his board — and so no merge ever straddles the freeze line, which Sheets
# refuses outright.
IDENTITY = ["", "#", "Rep"]
# The rep column's HEADER is the week label ("WE 8/17- 8/23"), the way his is —
# so it can't be found by name and is referenced by position instead.
REP_COL = 2
LAST_WEEK_PRODUCTS = ["APPS", "INT", "INT UP", "DTV", "NL", "EN", "Cx"]
PRIOR_WEEK_PRODUCTS = ["Apps", "INT", "INT UP", "DTV", "NL", "EN", "Cx"]
# The attribute block, in the order he has it. Tenure is his "Field Status".
TRAILING_ATTRS = ["Tenure", "Campaign", "Team", "Leadership", "A Player?",
                  "Email", "Location", "Status"]

TEAMS_COLS = (["Teams", "Team Weekly Goal", "Active Reps"] + PRODUCT_NAMES
              + ["TOTAL UNITS AVG", "NEW INT AVG", "% TO GOAL"])

# His fonts, read off the sheet.
FONT = "Georgia"
# Everything, not just the headers: Georgia 12 bold across the whole board
# (Megan 2026-08-17). Matches the house report standard.
BODY_SIZE = 12
BODY_BOLD = True
HEADER_SIZE = 12
BANNER_RED = "#CC0000"
HEADER_BG = "#000000"        # his header rows sit on black
WHITE = "#FFFFFF"
FROZEN_ROWS = 3
FROZEN_COLS = 3
BUFFER_COLS = 2              # trailing blanks so the frozen pane has somewhere to sit


def week_tab_name(d: dt.date | None = None) -> str:
    """'Sales Board WE 8.23' — his naming, for the Sunday ending that week."""
    d = d or dt.date.today()
    sunday = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    return f"Sales Board WE {sunday.month}.{sunday.day}"


def week_label(d: dt.date | None = None) -> str:
    """'WE 8/17- 8/23', the label he has in the header row."""
    d = d or dt.date.today()
    sunday = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    monday = sunday - dt.timedelta(days=6)
    return f"WE {monday.month}/{monday.day}- {sunday.month}/{sunday.day}"


def week_headers(d: dt.date | None = None) -> tuple:
    """His three header rows: banner, day numbers, columns.

    Every day repeats the full product set, as his does — a day's total alone
    can't tell you whether a slow Tuesday was internet or wireless."""
    d = d or dt.date.today()
    sunday = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    monday = sunday - dt.timedelta(days=6)

    banner = [""] * len(IDENTITY)
    daynum = [""] * len(IDENTITY)
    cols = list(IDENTITY)

    banner += ["RUNNING WEEK TOTALS"] + [""] * (len(PRODUCTS) - 1)
    daynum += [""] * len(PRODUCTS)
    cols += list(PRODUCT_NAMES)

    banner += ["LAST WEEK'S TOTALS"] + [""] * (len(LAST_WEEK_PRODUCTS) - 1)
    daynum += [""] * len(LAST_WEEK_PRODUCTS)
    cols += list(LAST_WEEK_PRODUCTS)

    # Two weeks back, the full block as his board carries it. One prior week
    # tells you a number moved; two tell you whether it's a trend or a blip.
    banner += ["PRIOR WEEK'S TOTALS"] + [""] * (len(PRIOR_WEEK_PRODUCTS) - 1)
    daynum += [""] * len(PRIOR_WEEK_PRODUCTS)
    cols += list(PRIOR_WEEK_PRODUCTS)

    for i, day in enumerate(DAYS):
        banner += [day] + [""] * len(DAY_PRODUCTS)
        daynum += [str((monday + dt.timedelta(days=i)).day)] + \
            [""] * len(DAY_PRODUCTS)
        cols += list(DAY_PRODUCTS) + [ROLL_CALL]

    banner += ["REP INFO"] + [""] * (len(TRAILING_ATTRS) - 1)
    daynum += [""] * len(TRAILING_ATTRS)
    cols += list(TRAILING_ATTRS)

    cols[REP_COL] = week_label(d)          # his week label sits here
    return banner, daynum, cols


def col_index(name: str, d: dt.date | None = None) -> int:
    """Where a column sits, by header name.

    Looked up rather than hardcoded: the layout has already moved twice, and a
    position baked into the carry-over is exactly what breaks silently when it
    moves again."""
    _, _, cols = week_headers(d)
    return cols.index(name)


def carry_over_rows(prev_week_rows: list, d: dt.date | None = None) -> list:
    """The rep rows a new week starts with, taken from LAST WEEK'S tab.

    EVERYONE CARRIES OVER unless somebody actually marked them Terminated — a
    new week must never begin by quietly dropping people, because the absence of
    a name is indistinguishable from an oversight. Terminating is a deliberate
    act; nothing else removes a rep.

    Only identity comes across. Production cells stay EMPTY, not zeroed: blank
    means the day hasn't happened, 0 means they were out and sold nothing, and
    opening a week with zeros tells every rep they already rolled one."""
    _, _, cols = week_headers(d)
    rep_i = REP_COL
    attr_i = {a: cols.index(a) for a in TRAILING_ATTRS}

    out = []
    for row in prev_week_rows:
        def cell(i):
            return (row[i].strip() if i < len(row) and row[i] else "")

        rep = cell(rep_i)
        if not rep:
            continue
        if cell(attr_i["Status"]).strip().lower() == "terminated":
            continue
        out.append({"rep": rep, "n": len(out) + 1,
                    "attrs": {a: cell(i) for a, i in attr_i.items()}})
    for r in out:
        r["attrs"]["Status"] = r["attrs"].get("Status") or "Active"
    return out


TOTALS_LABEL = "TOTALS"


def totals_row_values(first_rep_row: int, last_rep_row: int,
                      n_cols: int) -> list:
    """The TOTALS row, as live SUM formulas over the rep block.

    Formulas rather than numbers so the row stays right when a pull rewrites
    the day cells or somebody adds a rep — a written-out total is stale the
    moment anything above it changes. Columns that hold text (identity, Roll
    Call) are left blank: there is nothing to total, and a 0 there would read
    like a value.

    SUM ignores text, so a Roll Call marker or an 'X' sitting in a number
    column can never be counted as production."""
    row = [""] * n_cols
    row[REP_COL] = TOTALS_LABEL

    def a1(i):
        s, i = "", i + 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    text_cols = set(range(len(IDENTITY)))
    for i, name in enumerate(week_headers()[2]):
        if name == ROLL_CALL or name in TRAILING_ATTRS:
            text_cols.add(i)
    text_cols.add(REP_COL)
    for i in range(n_cols):
        if i in text_cols:
            continue
        col = a1(i)
        row[i] = f"=SUM({col}{first_rep_row}:{col}{last_rep_row})"
    return row


def rows_to_grid(carried: list, n_cols: int, d: dt.date | None = None) -> list:
    """Turn carry-over records into full-width sheet rows.

    Values are placed BY COLUMN NAME. With the attributes now out past the day
    blocks, writing a short row would drop a rep's team into a production
    column — which is the exact failure that made this a lookup."""
    _, _, cols = week_headers(d)
    out = []
    for rec in carried:
        row = [""] * n_cols
        row[REP_COL - 1] = rec["n"]
        row[REP_COL] = rec["rep"]
        for attr, val in (rec.get("attrs") or {}).items():
            if attr in cols and val:
                row[cols.index(attr)] = val
        out.append(row)
    return out


def _hex(h: str) -> dict:
    h = (h or "#000000").lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


def plan(d: dt.date | None = None) -> dict:
    """What would be created. Pure — reads nothing, writes nothing."""
    banner, daynum, cols = week_headers(d)
    return {"tabs": [TEAMS_TAB, week_tab_name(d)],
            "teams_cols": TEAMS_COLS, "week_banner": banner,
            "week_daynum": daynum, "week_cols": cols,
            "width": len(cols) + BUFFER_COLS}


def _base_format(sheet_id: int, header_rows: int, freeze_cols: int) -> list:
    """His look: Georgia, centred both ways, black bold white-text headers,
    frozen panes. Centring is also the standing rule for every report here — a
    left-aligned cell reads as somebody's hand-edit."""
    return [
        {"repeatCell": {
            "range": {"sheetId": sheet_id},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"fontFamily": FONT, "fontSize": BODY_SIZE,
                               "bold": BODY_BOLD}}},
            "fields": ("userEnteredFormat(horizontalAlignment,"
                       "verticalAlignment,textFormat)")}},
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0,
                      "endRowIndex": header_rows},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _hex(HEADER_BG),
                "textFormat": {"fontFamily": FONT, "fontSize": HEADER_SIZE,
                               "bold": True,
                               "foregroundColor": _hex(WHITE)}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": header_rows,
                                              "frozenColumnCount": freeze_cols}},
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
    ]


def banner_spans(banner: list) -> list:
    """[(start, end)] for each banner label — the columns it sits over.

    A banner runs from its label to the next label, so a merge is derived from
    the header itself rather than hand-counted; add a product and the merge
    grows with it."""
    starts = [i for i, v in enumerate(banner) if str(v).strip()]
    spans = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(banner)
        spans.append((i, end))
    return spans


def _merge_requests(sheet_id: int, banner: list) -> list:
    """Merge each day's banner across its block, so 'MON' sits over Monday's
    columns instead of hiding in the first one.

    UNMERGES the banner row first. Adding a column shifts every block right,
    and Sheets rejects a merge that partially overlaps an existing one — so a
    re-run after any layout change fails unless the old merges are cleared."""
    # Unmerge the WHOLE sheet, not just the banner row. A write into a merged
    # range only lands in the top-left cell and the rest is silently dropped —
    # so headers rewritten while old merges are still in place lose every label
    # that isn't at a merge's start. Clear first, then write, then merge.
    out = [{"unmergeCells": {"range": {"sheetId": sheet_id}}}]
    for start, end in banner_spans(banner):
        if end - start < 2:
            continue
        out.append({"mergeCells": {
            "mergeType": "MERGE_ALL",
            "range": {"sheetId": sheet_id, "startRowIndex": 0,
                      "endRowIndex": 1, "startColumnIndex": start,
                      "endColumnIndex": end}}})
    return out


def content_row_count(rows: list, key_col: int, header_rows: int) -> int:
    """Rows that actually hold a record — headers plus the last row with a
    name in the key column.

    Counted from the LAST filled row rather than by counting filled ones, so a
    gap in the middle doesn't shorten the block and leave a bordered row
    stranded below it."""
    last = header_rows
    for i, r in enumerate(rows[header_rows:], start=header_rows):
        if len(r) > key_col and str(r[key_col] or "").strip():
            last = i + 1
    return last


def _border_requests(sheet_id: int, n_rows: int, n_cols: int,
                     grid_rows: int | None = None) -> list:
    """Borders on the rows that hold content, and NONE below them.

    Bordering the whole grid draws a box around hundreds of empty rows, which
    reads as a table that is mostly blank rather than a team of 61. The second
    request clears anything a previous run over-bordered — without it, removing
    a rep would leave their empty row still boxed in."""
    edge = {"style": "SOLID", "color": _hex("#9AA0A6")}
    none = {"style": "NONE"}
    out = [{"updateBorders": {
        "range": {"sheetId": sheet_id, "startRowIndex": 0,
                  "endRowIndex": n_rows, "startColumnIndex": 0,
                  "endColumnIndex": n_cols},
        "top": edge, "bottom": edge, "left": edge, "right": edge,
        "innerHorizontal": edge, "innerVertical": edge}}]
    if grid_rows and grid_rows > n_rows:
        out.append({"updateBorders": {
            "range": {"sheetId": sheet_id, "startRowIndex": n_rows,
                      "endRowIndex": grid_rows, "startColumnIndex": 0,
                      "endColumnIndex": n_cols},
            "top": none, "bottom": none, "left": none, "right": none,
            "innerHorizontal": none, "innerVertical": none}})
    return out


# Georgia 12 bold is a wide face: roughly 9px a character, plus padding.
PX_PER_CHAR = 9
PX_PADDING = 22
MIN_COL_PX = 58


def column_widths(rows: list, n_cols: int) -> list:
    """A width per column, from the widest thing actually in it.

    Sheets' own auto-resize fits the CONTENT, so a column of single digits
    collapses to ~25px and its header ("INT UP") is clipped — the numbers fit
    but nobody can read what they are. Sizing from the widest of header and
    values, with a floor, keeps every header legible."""
    widest = [0] * n_cols
    for r in rows:
        for i, v in enumerate(r[:n_cols]):
            widest[i] = max(widest[i], len(str(v or "").strip()))
    return [max(MIN_COL_PX, w * PX_PER_CHAR + PX_PADDING) for w in widest]


def _autosize_requests(sheet_id: int, n_cols: int, rows: list | None = None,
                       ) -> list:
    """Explicit widths when we can see the content; Sheets' own fit otherwise."""
    if not rows:
        return [{"autoResizeDimensions": {"dimensions": {
            "sheetId": sheet_id, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": n_cols}}}]
    out = []
    for i, px in enumerate(column_widths(rows, n_cols)):
        out.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    return out


def _fill(sheet_id: int, row: int, col: int, colour: str) -> dict:
    return {"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": row,
                  "endRowIndex": row + 1, "startColumnIndex": col,
                  "endColumnIndex": col + 1},
        "cell": {"userEnteredFormat": {"backgroundColor": _hex(colour)}},
        "fields": "userEnteredFormat.backgroundColor"}}


def _product_fills(sheet_id: int, cols: list, row: int) -> list:
    """Every product header on its own colour, his colours, every day block."""
    colour = {name: c for name, c in PRODUCTS if c}
    colour.update({"Int": colour.get("INT"), "Int Up": colour.get("INT UP")})
    out = []
    for i, name in enumerate(cols):
        c = colour.get(name)
        if c:
            out.append(_fill(sheet_id, row, i, c))
    return out


def build(*, write: bool = False, sheet_id: str = SHEET_ID,
          d: dt.date | None = None) -> dict:
    """Create the tabs. ADDITIVE and IDEMPOTENT — an existing tab is left
    exactly as it is, never cleared or rebuilt, because by then it holds an
    owner's roster and a week of production."""
    p = plan(d)
    if not write:
        return p

    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(sheet_id)
    existing = {w.title: w for w in sh.worksheets()}
    made, skipped, reqs = [], [], []

    def ensure(title, rows, cols):
        if title in existing:
            skipped.append(title)
            return None
        ws = _retry(sh.add_worksheet, title=title, rows=rows, cols=cols)
        made.append(title)
        return ws

    ws = ensure(TEAMS_TAB, 100, len(TEAMS_COLS) + BUFFER_COLS)
    if ws:
        _retry(ws.update, [TEAMS_COLS], "A1")
        reqs += _base_format(ws.id, 1, 1)
        reqs += _product_fills(ws.id, TEAMS_COLS, 0)

    wk = week_tab_name(d)
    ws = ensure(wk, 400, p["width"])
    if ws:
        _retry(ws.update,
               [p["week_banner"], p["week_daynum"], p["week_cols"]], "A1")
        reqs += _base_format(ws.id, FROZEN_ROWS, FROZEN_COLS)
        reqs += _product_fills(ws.id, p["week_cols"], FROZEN_ROWS - 1)
        reqs += _merge_requests(ws.id, p["week_banner"])
        # his LAST WEEK'S TOTALS banner is red
        if "LAST WEEK'S TOTALS" in p["week_banner"]:
            reqs.append(_fill(ws.id, 0,
                              p["week_banner"].index("LAST WEEK'S TOTALS"),
                              BANNER_RED))

        prev = _previous_week_tab(existing, wk)
        if prev is not None:
            carried = carry_over_rows(
                _retry(prev.get_all_values)[FROZEN_ROWS:], d)
            if carried:
                grid = rows_to_grid(carried, len(p["week_cols"]), d)
                _retry(ws.update, grid, f"A{FROZEN_ROWS + 1}")
            p["carried_over"] = len(carried)

    if reqs:
        _retry(sh.batch_update, {"requests": reqs})
    if made:
        # borders and widths last, once the values are in place
        _retry(sh.batch_update, {"requests": reformat_requests(sh, p, d)})
    return {**p, "created": made, "already_there": skipped}


def reformat_requests(sh, p: dict, d=None) -> list:
    """Border + autosize passes for whatever tabs exist right now."""
    from automations.recruiting_report.fill import _retry
    out = []
    for w in sh.worksheets():
        if w.title == TEAMS_TAB:
            rows = _retry(w.get_all_values)
            out += _border_requests(w.id, content_row_count(rows, 0, 1),
                                    len(TEAMS_COLS), w.row_count)
            out += _autosize_requests(w.id, len(TEAMS_COLS))
        elif w.title == week_tab_name(d):
            rows = _retry(w.get_all_values)
            out += _border_requests(
                w.id, content_row_count(rows, REP_COL, FROZEN_ROWS),
                len(p["week_cols"]), w.row_count)
            out += _autosize_requests(w.id, len(p["week_cols"]))
    return out


def reformat(*, sheet_id: str = SHEET_ID, d: dt.date | None = None) -> dict:
    """Re-apply formatting to the tabs that already exist.

    Formatting only — merges, borders, fills, fonts, freezing and column
    widths. It never touches a value, so it is safe to run over a board that
    already holds a week of production."""
    from automations.recruiting_report.fill import open_by_key, _retry

    p = plan(d)
    sh = open_by_key(sheet_id)
    tabs = {w.title: w for w in sh.worksheets()}
    reqs, done = [], []

    wk = tabs.get(week_tab_name(d))
    if wk is not None:
        rows = _retry(wk.get_all_values)
        n_rows = content_row_count(rows, REP_COL, FROZEN_ROWS)
        n_cols = len(p["week_cols"])
        reqs += _base_format(wk.id, FROZEN_ROWS, FROZEN_COLS)
        reqs += _product_fills(wk.id, p["week_cols"], FROZEN_ROWS - 1)
        reqs += _merge_requests(wk.id, p["week_banner"])
        reqs.append(_fill(wk.id, 0,
                          p["week_banner"].index("LAST WEEK'S TOTALS"),
                          BANNER_RED))
        # TOTALS sits directly under the last rep. Rewritten each time rather
        # than appended, so re-running can never stack a second one.
        existing_totals = next(
            (i for i, r in enumerate(rows[FROZEN_ROWS:], start=FROZEN_ROWS)
             if len(r) > REP_COL
             and str(r[REP_COL]).strip().upper() == TOTALS_LABEL),
            None)
        last_rep = (existing_totals if existing_totals is not None else n_rows)
        if last_rep > FROZEN_ROWS:
            trow = last_rep + 1
            _retry(wk.update,
                   [totals_row_values(FROZEN_ROWS + 1, last_rep, n_cols)],
                   f"A{trow}", value_input_option="USER_ENTERED")
            n_rows = trow
            reqs.append({"repeatCell": {
                "range": {"sheetId": wk.id, "startRowIndex": trow - 1,
                          "endRowIndex": trow, "startColumnIndex": 0,
                          "endColumnIndex": n_cols},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _hex("#F1C232"),
                    "textFormat": {"fontFamily": FONT, "fontSize": BODY_SIZE,
                                   "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"}})

        reqs += _border_requests(wk.id, n_rows, n_cols,
                                 wk.row_count)
        reqs += _autosize_requests(wk.id, n_cols, rows)
        done.append(wk.title)

    tm = tabs.get(TEAMS_TAB)
    if tm is not None:
        rows = _retry(tm.get_all_values)
        n_cols = len(TEAMS_COLS)
        reqs += _base_format(tm.id, 1, 1)
        reqs += _product_fills(tm.id, TEAMS_COLS, 0)
        reqs += _border_requests(tm.id, content_row_count(rows, 0, 1), n_cols,
                                 tm.row_count)
        reqs += _autosize_requests(tm.id, n_cols, rows or [TEAMS_COLS])
        done.append(tm.title)

    if reqs:
        _retry(sh.batch_update, {"requests": reqs})
    return {"reformatted": done}


def _previous_week_tab(existing: dict, current: str):
    """The most recent 'Sales Board WE …' tab that isn't the current one."""
    keyed = []
    for title, ws in existing.items():
        m = re.match(r"^Sales Board WE\s+(\d{1,2})\.(\d{1,2})$", title.strip())
        if m and title != current:
            keyed.append(((int(m.group(1)), int(m.group(2))), ws))
    return max(keyed, key=lambda kv: kv[0])[1] if keyed else None


def sync_new_reps(names, *, write: bool = False, sheet_id: str = SHEET_ID,
                  today: dt.date | None = None) -> dict:
    """Add reps who have appeared in Tableau but aren't on the board yet.

    STRICTLY ADDITIVE — appends to the current week tab and does nothing else:
    never edits a row, never removes one, and never resurrects someone marked
    Terminated, because the name match finds them and skips. Tableau is the
    source of new NAMES; the owner stays the source of everything about them."""
    from automations.recruiting_report.fill import open_by_key, _retry

    today = today or dt.date.today()
    sh = open_by_key(sheet_id)
    tabs = {w.title: w for w in sh.worksheets()}
    wk = tabs.get(week_tab_name(today))
    if wk is None:
        return {"error": f"no {week_tab_name(today)} tab — build it first"}

    _, _, cols = week_headers(today)
    rows = _retry(wk.get_all_values)
    body = rows[FROZEN_ROWS:]
    rep_col = REP_COL
    have = {(r[rep_col] or "").strip().lower()
            for r in body if len(r) > rep_col and r[rep_col].strip()}

    fresh, seen = [], set()
    for n in names:
        key = " ".join(str(n or "").split()).strip()
        if not key or key.lower() in have or key.lower() in seen:
            continue
        seen.add(key.lower())
        fresh.append(key)

    out = {"found": len(fresh), "names": fresh, "added_to": []}
    if not fresh or not write:
        return out

    n0 = len(have)
    first_free = max(FROZEN_ROWS + 1, len(rows) + 1)
    grid = rows_to_grid(
        [{"n": n0 + i + 1, "rep": n, "attrs": {"Status": "Active"}}
         for i, n in enumerate(fresh)], len(cols), today)
    _retry(wk.update, grid, f"A{first_free}")
    out["added_to"].append(wk.title)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="build a sales board like Raf's")
    ap.add_argument("--write", action="store_true",
                    help="actually create/append (default is a dry run)")
    ap.add_argument("--sheet-id", default=SHEET_ID)
    ap.add_argument("--sync-new-reps", action="store_true",
                    help="add reps Tableau has that the sheet doesn't")
    ap.add_argument("--reformat", action="store_true",
                    help="re-apply borders/merges/widths to existing tabs "
                         "(formatting only — never touches a value)")
    a = ap.parse_args(argv)

    if a.reformat:
        res = reformat(sheet_id=a.sheet_id)
        print("reformatted:", ", ".join(res["reformatted"]) or "nothing")
        return 0

    if a.sync_new_reps:
        from automations.icd_sales_board import board_read as B
        from automations.recruiting_report.fill import open_by_key
        src = open_by_key(SOURCE_SHEET_ID)
        tabs = B.week_tabs([w.title for w in src.worksheets()])
        w = B.parse_week(src.worksheet(tabs[0]).get_all_values(), tabs[0])
        res = sync_new_reps([r["name"] for r in w.reps],
                            write=a.write, sheet_id=a.sheet_id)
        if res.get("error"):
            print(res["error"])
            return 1
        print(f"new reps: {res['found']}")
        for n in res["names"][:20]:
            print(f"  + {n}")
        print("added to:", res["added_to"] or
              ("nothing — dry run" if not a.write else "none"))
        return 0

    res = build(write=a.write, sheet_id=a.sheet_id)
    print(("CREATED" if a.write else "DRY RUN — would create") + ":")
    for t in res["tabs"]:
        print(f"  • {t}")
    print(f"\n{TEAMS_TAB} ({len(res['teams_cols'])} cols): "
          + " | ".join(res["teams_cols"]))
    print(f"\nWeek tab — {len(res['week_cols'])} columns, "
          f"{FROZEN_ROWS} frozen rows / {FROZEN_COLS} frozen columns")
    print("  identity  : " + " | ".join(IDENTITY))
    print("  this week : " + " | ".join(PRODUCT_NAMES))
    print("  last week : APPS")
    print(f"  each day  : {' | '.join(DAY_PRODUCTS)} | {ROLL_CALL}"
          f"   (×{len(DAYS)})")
    if a.write:
        print(f"\ncreated: {res['created'] or 'none'}")
        print(f"already there (left alone): {res['already_there'] or 'none'}")
        if "carried_over" in res:
            print(f"carried over from last week: {res['carried_over']} reps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

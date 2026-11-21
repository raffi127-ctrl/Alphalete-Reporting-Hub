"""Build the 'Country Campaign Board' tab (ATT Program - Focus Report workbook,
next to 'Country Metrics') and its hidden data tab.

Same shape as the top of the ORG Sales Board, COUNTRY totals, no owner
breakdown (Eve 2026-11-20):

  B2   title                                   COUNTRY - ALL CAMPAIGNS
  B3   Week Ending: <date>                     the week the board shows
  B4   Product Summary - This Week             campaign x Monday..Sunday + total
  then ONE 'Current vs Prior Weeks' box per campaign (All Campaigns first),
  each the ORG board's box — Sales This Week / vs Prior Week / vs 4 WeekAVG /
  Sales (Last Week) / Sales (4 Week AVG) — every campaign compared with ITSELF.
  bottom: 'Weekly History' — ONE box, campaigns down, the last 8 closed weeks
  across (newest left), weekly totals only.

The per-day history the boxes need lives on the hidden tab DATA_TAB: one row
per (closed week, campaign) + an 'All Campaigns' row per complete week, newest
on top under its header. Everything on the board reads it with SUMIFS /
AVERAGEIFS keyed on the week date in C3, so inserting rows never breaks a
reference.

Colors: campaign = its ORG Sales Board section color (on the bar of its box and
on its name as TEXT over light grey); everything else neutral greys.

  python -m automations.program_daily_summary.layout            # create tabs
"""
from __future__ import annotations

from automations.recruiting_report import fill as rfill

SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"   # same as Country Metrics
TAB = "Country Campaign Board"
DATA_TAB = "Country Campaign Board (data)"

CAMPAIGNS = ["ATT Fiber", "ATT NDS", "B2B", "Frontier", "Fios"]
ALL = "All Campaigns"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]
WE_LABEL = "Week Ending:"
PS_BAR = "Product Summary - This Week"
HIST_BAR = "Weekly History - Sales per Week"
HIST_WEEKS = 8
DATA_HDR = "Week Ending"          # B1 of DATA_TAB

R_TITLE, R_WE = 2, 3
R_PS_BAR, R_PS_HDR, R_PS_FIRST = 4, 5, 6
R_PS_TOTAL = R_PS_FIRST + len(CAMPAIGNS)            # 11
R_BOX0 = R_PS_TOTAL + 2                              # 13
BOX_H = 8                                            # bar+hdr+5 rows+gap
BOXES = [ALL] + CAMPAIGNS
R_HIST_BAR = R_BOX0 + BOX_H * len(BOXES)             # 61
R_HIST_HDR = R_HIST_BAR + 1
R_HIST_FIRST = R_HIST_HDR + 1
R_HIST_TOTAL = R_HIST_FIRST + len(CAMPAIGNS)

ROWS, COLS = R_HIST_TOTAL + 3, 11
DATA_ROWS, DATA_COLS = 1000, 11       # 6 rows a week -> ~3 years


def _hex(h: str) -> dict:
    h = h.lstrip("#")
    return {k: int(h[i:i + 2], 16) / 255 for k, i in
            (("red", 0), ("green", 2), ("blue", 4))}


def _tint(c: dict, amount: float = 0.82) -> dict:
    """`c` mixed toward white — the light header row under a campaign bar."""
    return {k: v + (1 - v) * amount for k, v in c.items()}


# Campaign colors = the ORG Sales Board's section bars (Eve 2026-11-20).
# Frontier = the color its ORG section had until it was retired 8/19.
# Fios has no ORG section -> its own color (burnt orange, unused there).
# All Campaigns = black, like the ORG board's 'ALL TOTALS'.
CAMPAIGN_COLORS = {
    ALL: _hex("#000000"),
    "ATT Fiber": _hex("#660000"),
    "ATT NDS": _hex("#073763"),
    "B2B": _hex("#bf9000"),
    "Frontier": _hex("#741b47"),
    "Fios": _hex("#b45f06"),
}
DARK = _hex("#434343")          # title text + neutral bars
HEAD = _hex("#d9d9d9")          # header rows, Grand Total row
TOTAL = _hex("#efefef")         # Grand Total column (Eve: not dark)
INK = _hex("#262626")           # body text
PALE = _hex("#f3f3f3")          # title, % rows, campaign-name cells
WHITE = _hex("#ffffff")
GREEN = {"red": 0.72, "green": 0.88, "blue": 0.72}
RED = {"red": 0.96, "green": 0.78, "blue": 0.78}

DAYCOLS = "CDEFGHI"       # Monday..Sunday on the board
HDAYCOLS = "DEFGHIJ"      # Monday..Sunday on DATA_TAB
WEEKCOLS = "CDEFGHIJ"     # the 8 weeks of the history box


def box_rows(i: int):
    """(bar, header, this, vs_prior, vs_4wk, last, avg4) rows of box i."""
    b = R_BOX0 + BOX_H * i
    return b, b + 1, b + 2, b + 3, b + 4, b + 5, b + 6


def _d(col: str) -> str:
    """Open-ended DATA_TAB column from its header row (row 1), so a week
    inserted at row 2 is always inside the range."""
    return f"'{DATA_TAB}'!${col}$1:${col}"


def _values():
    v = {f"B{R_TITLE}": "COUNTRY - ALL CAMPAIGNS",
         f"B{R_WE}": WE_LABEL,
         f"B{R_PS_BAR}": PS_BAR,
         f"B{R_PS_HDR}": "Product Type", f"J{R_PS_HDR}": "Grand Total"}
    for i, d in enumerate(DAYS):
        v[f"{DAYCOLS[i]}{R_PS_HDR}"] = d
    for k, name in enumerate(CAMPAIGNS):
        r = R_PS_FIRST + k
        v[f"B{r}"] = name
        v[f"J{r}"] = f'=IF(COUNT(C{r}:I{r})=0,"",SUM(C{r}:I{r}))'
    v[f"B{R_PS_TOTAL}"] = "Grand Total"
    for col in DAYCOLS + "J":
        rng = f"{col}{R_PS_FIRST}:{col}{R_PS_TOTAL - 1}"
        v[f"{col}{R_PS_TOTAL}"] = f'=IF(COUNT({rng})=0,"",SUM({rng}))'

    we = "$C$3"
    for i, name in enumerate(BOXES):
        bar, hdr, tw, vp, v4, lw, a4 = box_rows(i)
        src = R_PS_TOTAL if name == ALL else R_PS_FIRST + CAMPAIGNS.index(name)
        v[f"B{bar}"] = f"{name} - Current vs Prior Weeks"
        v[f"B{hdr}"] = f"{name}: Mon-Sun"
        v[f"B{tw}"] = "Sales - This Week"
        v[f"B{vp}"] = "vs Prior Week"
        v[f"B{v4}"] = "vs 4 WeekAVG"
        v[f"B{lw}"] = "Sales (Last Week)"
        v[f"B{a4}"] = "Sales ( 4 Week AVG)"
        crit = f'{_d("C")},"{name}"'
        for k, col in enumerate(DAYCOLS + "J"):
            v[f"{col}{hdr}"] = (DAYS + ["Grand Total"])[k]
            hc = (HDAYCOLS + "K")[k]
            this = f"{col}{src}"
            v[f"{col}{tw}"] = f'=IF({this}="","",{this})'
            v[f"{col}{lw}"] = (f'=IF(COUNTIFS({_d("B")},{we}-7,{crit})=0,"",'
                               f'SUMIFS({_d(hc)},{_d("B")},{we}-7,{crit}))')
            v[f"{col}{a4}"] = (f'=IFERROR(ROUND(AVERAGEIFS({_d(hc)},'
                               f'{_d("B")},">="&({we}-28),{_d("B")},"<="&({we}-7),'
                               f'{crit}),0),"")')
            v[f"{col}{vp}"] = (f'=IF(OR({col}{tw}="",{col}{lw}=""),"",'
                               f'IFERROR({col}{tw}/{col}{lw}-1,""))')
            v[f"{col}{v4}"] = (f'=IF(OR({col}{tw}="",{col}{a4}=""),"",'
                               f'IFERROR({col}{tw}/{col}{a4}-1,""))')

    # Weekly History: campaigns down, last 8 closed weeks across (newest left).
    v[f"B{R_HIST_BAR}"] = HIST_BAR
    v[f"B{R_HIST_HDR}"] = "Campaign"
    for k, col in enumerate(WEEKCOLS):
        v[f"{col}{R_HIST_HDR}"] = f"={we}-{7 * (k + 1)}"
    for r, name in [(R_HIST_FIRST + k, c) for k, c in enumerate(CAMPAIGNS)] + \
                   [(R_HIST_TOTAL, ALL)]:
        v[f"B{r}"] = "Grand Total" if name == ALL else name
        for col in WEEKCOLS:
            h = f"{col}${R_HIST_HDR}"
            crit = f'{_d("B")},{h},{_d("C")},"{name}"'
            v[f"{col}{r}"] = (f'=IF(COUNTIFS({crit})=0,"",SUMIFS({_d("K")},{crit}))')
    return v


def _data_header():
    return [[DATA_HDR, "Campaign"] + DAYS + ["Grand Total"]]


def _rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0 - 1, "endRowIndex": r1,
            "startColumnIndex": ord(c0) - 65, "endColumnIndex": ord(c1) - 64}


def _fmt(rng, bg=None, fg=None, bold=None, size=None, align="CENTER", num=None):
    f, fields = {}, []
    if bg:
        f["backgroundColor"] = bg; fields.append("backgroundColor")
    tf = {}
    if fg:
        tf["foregroundColor"] = fg
    if bold is not None:
        tf["bold"] = bold
    if size:
        tf["fontSize"] = size
    if tf:
        tf["fontFamily"] = "Merriweather"
        f["textFormat"] = tf; fields.append("textFormat")
    if align:
        f["horizontalAlignment"] = align; fields.append("horizontalAlignment")
    f["verticalAlignment"] = "MIDDLE"; fields.append("verticalAlignment")
    if num:
        f["numberFormat"] = num; fields.append("numberFormat")
    return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": f},
                           "fields": ",".join(f"userEnteredFormat.{x}" for x in fields)}}


def _border(rng):
    s = {"style": "SOLID", "color": {"red": 0.6, "green": 0.6, "blue": 0.6}}
    return {"updateBorders": {"range": rng, "top": s, "bottom": s, "left": s,
                              "right": s, "innerHorizontal": s, "innerVertical": s}}


def _merge(rng):
    return {"mergeCells": {"range": rng, "mergeType": "MERGE_ALL"}}


def _size(sid, dim, a, b, px):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": dim, "startIndex": a, "endIndex": b},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}


def _name_cell(sid, r, name):
    """Campaign name: light grey cell, the campaign's color on the TEXT."""
    return _fmt(_rng(sid, r, r, "B", "B"), PALE, CAMPAIGN_COLORS[name], True, 9)


def _requests(sid):
    pct = {"type": "PERCENT", "pattern": "0%"}
    num = {"type": "NUMBER", "pattern": "#,##0"}
    date = {"type": "DATE", "pattern": "m/d/yyyy"}
    reqs = [
        _merge(_rng(sid, R_TITLE, R_TITLE, "B", "J")),
        _merge(_rng(sid, R_PS_BAR, R_PS_BAR, "B", "J")),
        _fmt(_rng(sid, R_TITLE, R_TITLE, "B", "J"), PALE, DARK, True, 16),
        _fmt(_rng(sid, R_WE, R_WE, "B", "B"), None, INK, True, 9, align="RIGHT"),
        _fmt(_rng(sid, R_WE, R_WE, "C", "C"), None, DARK, True, 9, align="LEFT", num=date),
        _fmt(_rng(sid, R_PS_BAR, R_PS_BAR, "B", "J"), DARK, WHITE, True, 11),
        _fmt(_rng(sid, R_PS_HDR, R_PS_HDR, "B", "J"), HEAD, INK, True, 9),
        _fmt(_rng(sid, R_PS_FIRST, R_PS_TOTAL - 1, "C", "I"), WHITE, INK, False, 9, num=num),
        _fmt(_rng(sid, R_PS_FIRST, R_PS_TOTAL - 1, "J", "J"), TOTAL, INK, True, 9, num=num),
        _fmt(_rng(sid, R_PS_TOTAL, R_PS_TOTAL, "B", "J"), HEAD, INK, True, 10, num=num),
        *[_name_cell(sid, R_PS_FIRST + k, c) for k, c in enumerate(CAMPAIGNS)],
        _border(_rng(sid, R_PS_HDR, R_PS_TOTAL, "B", "J")),
    ]
    for i, name in enumerate(BOXES):
        bar, hdr, tw, vp, v4, lw, a4 = box_rows(i)
        color = CAMPAIGN_COLORS[name]
        reqs += [
            _merge(_rng(sid, bar, bar, "B", "J")),
            _fmt(_rng(sid, bar, bar, "B", "J"), color, WHITE, True, 11),
            _fmt(_rng(sid, hdr, hdr, "B", "J"), _tint(color), color, True, 9),
            _fmt(_rng(sid, tw, a4, "B", "I"), WHITE, INK, False, 9, num=num),
            _fmt(_rng(sid, vp, v4, "B", "I"), PALE, INK, False, 9, num=pct),
            _fmt(_rng(sid, tw, a4, "J", "J"), TOTAL, INK, True, 9, num=num),
            _fmt(_rng(sid, vp, v4, "J", "J"), None, None, None, None, num=pct),
            _border(_rng(sid, hdr, a4, "B", "J")),
        ]
        for op, c in (("NUMBER_GREATER_THAN_EQ", GREEN), ("NUMBER_LESS", RED)):
            reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [_rng(sid, vp, v4, "C", "J")],
                "booleanRule": {"condition": {"type": op, "values": [{"userEnteredValue": "0"}]},
                                "format": {"backgroundColor": c}}}}})
    last = WEEKCOLS[-1]
    reqs += [
        _merge(_rng(sid, R_HIST_BAR, R_HIST_BAR, "B", last)),
        _fmt(_rng(sid, R_HIST_BAR, R_HIST_BAR, "B", last), DARK, WHITE, True, 11),
        _fmt(_rng(sid, R_HIST_HDR, R_HIST_HDR, "B", last), HEAD, INK, True, 9,
             num={"type": "DATE", "pattern": "\"WE\" m/d"}),
        _fmt(_rng(sid, R_HIST_FIRST, R_HIST_TOTAL - 1, "C", last), WHITE, INK, False, 9, num=num),
        *[_name_cell(sid, R_HIST_FIRST + k, c) for k, c in enumerate(CAMPAIGNS)],
        _fmt(_rng(sid, R_HIST_TOTAL, R_HIST_TOTAL, "B", last), HEAD, INK, True, 10, num=num),
        _border(_rng(sid, R_HIST_HDR, R_HIST_TOTAL, "B", last)),
        _size(sid, "COLUMNS", 0, 1, 20),
        _size(sid, "COLUMNS", 1, 2, 190),
        _size(sid, "COLUMNS", 2, COLS, 92),
        _size(sid, "ROWS", R_TITLE - 1, R_TITLE, 40),
    ]
    return reqs


def _col(i: int) -> str:
    """0-based column index -> A1 letters (works past Z)."""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _irng(sid, r0, r1, c0, c1):
    """Like _rng but with 0-based column indexes (c1 inclusive)."""
    return {"sheetId": sid, "startRowIndex": r0 - 1, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1 + 1}


FIRST_HIST_COL = 2                       # C
VISIBLE_HIST_COLS = len(WEEKCOLS)        # C..J stay open; K+ grouped


def history_formulas(c: int) -> dict:
    """A1 -> formula for history column index `c` (k-th week back)."""
    col, k = _col(c), c - FIRST_HIST_COL
    v = {f"{col}{R_HIST_HDR}": f"=$C$3-{7 * (k + 1)}"}
    for r, name in [(R_HIST_FIRST + i, x) for i, x in enumerate(CAMPAIGNS)] +                    [(R_HIST_TOTAL, ALL)]:
        crit = f'{_d("B")},{col}${R_HIST_HDR},{_d("C")},"{name}"'
        v[f"{col}{r}"] = f'=IF(COUNTIFS({crit})=0,"",SUMIFS({_d("K")},{crit}))'
    return v


def grow_history(ws, n_weeks: int, *, dry_run=False, logfn=print) -> int:
    """Weekly History accumulates to the RIGHT (Eve 2026-11-20): one column
    per stored week (newest left), never fewer than C..J. Columns past J are
    grouped (collapsed by default) so the box still reads as 8 weeks.
    Idempotent: only adds what is missing. Returns columns added."""
    have = len(ws.row_values(R_HIST_HDR)) - FIRST_HIST_COL
    want = max(VISIBLE_HIST_COLS, n_weeks)
    if want <= have:
        return 0
    first, last = FIRST_HIST_COL + have, FIRST_HIST_COL + want - 1
    logfn(f"  Weekly History: adding {want - have} week column(s) "
          f"{_col(first)}..{_col(last)}")
    if dry_run:
        return want - have
    sid = ws.id
    if ws.col_count < last + 1:
        ws.add_cols(last + 1 - ws.col_count)
    num = {"type": "NUMBER", "pattern": "#,##0"}
    reqs = [
        {"unmergeCells": {"range": _irng(sid, R_HIST_BAR, R_HIST_BAR, 1, last)}},
        {"mergeCells": {"range": _irng(sid, R_HIST_BAR, R_HIST_BAR, 1, last),
                        "mergeType": "MERGE_ALL"}},
        _fmt(_irng(sid, R_HIST_BAR, R_HIST_BAR, first, last), DARK, WHITE, True, 11),
        _fmt(_irng(sid, R_HIST_HDR, R_HIST_HDR, first, last), HEAD, INK, True, 9,
             num={"type": "DATE", "pattern": "\"WE\" m/d"}),
        _fmt(_irng(sid, R_HIST_FIRST, R_HIST_TOTAL - 1, first, last), WHITE, INK,
             False, 9, num=num),
        _fmt(_irng(sid, R_HIST_TOTAL, R_HIST_TOTAL, first, last), HEAD, INK, True,
             10, num=num),
        _border(_irng(sid, R_HIST_HDR, R_HIST_TOTAL, 1, last)),
        {"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": first,
            "endIndex": last + 1}, "properties": {"pixelSize": 92},
            "fields": "pixelSize"}},
    ]
    g0 = FIRST_HIST_COL + VISIBLE_HIST_COLS                 # K
    meta = ws.spreadsheet.fetch_sheet_metadata(
        {"fields": "sheets(properties.sheetId,columnGroups)"})
    groups = next((x.get("columnGroups", []) for x in meta["sheets"]
                   if x["properties"]["sheetId"] == sid), [])
    for g in groups:
        reqs.append({"deleteDimensionGroup": {"range": g["range"]}})
    if last >= g0:
        rng = {"sheetId": sid, "dimension": "COLUMNS", "startIndex": g0,
               "endIndex": last + 1}
        reqs += [{"addDimensionGroup": {"range": rng}},
                 {"updateDimensionGroup": {"dimensionGroup": {
                     "range": rng, "depth": 1, "collapsed": True},
                     "fields": "collapsed"}}]
    ws.spreadsheet.batch_update({"requests": reqs})
    vals = {}
    for c in range(first, last + 1):
        vals.update(history_formulas(c))
    ws.batch_update([{"range": a, "values": [[f]]} for a, f in vals.items()],
                    value_input_option="USER_ENTERED")
    return want - have


def build(*, logfn=print):
    """Create both tabs if missing. Never touches an existing one.
    Returns (board ws, data ws)."""
    sh = rfill.open_by_key(SHEET_ID)
    titles = [w.title for w in sh.worksheets()]
    if DATA_TAB in titles:
        data = sh.worksheet(DATA_TAB)
    else:
        data = sh.add_worksheet(DATA_TAB, rows=DATA_ROWS, cols=DATA_COLS)
        data.update("B1", _data_header())
        sh.batch_update({"requests": [
            _fmt(_rng(data.id, 1, 1, "B", "K"), HEAD, INK, True, 9),
            _fmt(_rng(data.id, 2, DATA_ROWS, "B", "B"), None, None, None, None,
                 num={"type": "DATE", "pattern": "m/d/yyyy"}),
            {"updateSheetProperties": {"properties": {"sheetId": data.id, "hidden": True},
                                       "fields": "hidden"}}]})
        logfn(f"created hidden '{DATA_TAB}'")
    if TAB in titles:
        logfn(f"'{TAB}' already exists — left as is")
        return sh.worksheet(TAB), data
    after = titles.index("Country Metrics") + 1 if "Country Metrics" in titles else None
    ws = sh.add_worksheet(TAB, rows=ROWS, cols=COLS, index=after)
    sh.batch_update({"requests": _requests(ws.id)})
    vals = [{"range": a1, "values": [[val]]} for a1, val in _values().items()]
    ws.batch_update(vals, value_input_option="USER_ENTERED")
    logfn(f"created '{TAB}' ({ROWS}x{COLS}) next to Country Metrics")
    return ws, data


if __name__ == "__main__":
    build()

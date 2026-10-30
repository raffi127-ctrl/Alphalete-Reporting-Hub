"""Lumen Owners tab — the captainship-style performance boxes, on their own tab
of the Org Sales Board workbook.

WHY (Raf, 2026-10-20, reply to the Lumen Owners mail, with a screenshot of his
own captainship box): "can we add this type of reporting as well please?" —
the NEW INTERNET PERFORMANCE box: Product Summary This Week, Current vs Prior
Weeks (vs last week, vs the 4-week average), the CAPTAIN TEAM week-by-week
history and the daily board. Eve 2026-10-21: that needs weeks of history a
one-off email cannot rebuild every day, so it lives on a tab like the boxes
on the Org Sales Board, and the mail carries a picture of it.

TWO TABS, both written ONLY by this module:
  * `Lumen Owners` — what people look at. Rebuilt from scratch every run (the
    owner list moves with the Quantum tracker), so nobody should hand-edit it.
  * `_lumen_history` (hidden) — one line per (week, metric, crosstab owner)
    with the 7 day counts, from the SAME all-teams fiber crosstab every run
    pulls. It is what the week columns and the 4-week average read. Every
    owner on the crosstab is kept, not only Lumen owners, so somebody who joins
    the Lumen list later already has their weeks.

Nothing here touches the shared 'Alphalete ORG Sales Board' tab.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

TAB = "Lumen Owners"
HISTORY_TAB = "_lumen_history"
# The numbers are AT&T sales of owners moving over from Lumen; "Lumen" alone
# read like Lumen sales (Eve, 2026-10-30).
TEAM_TITLE = "Former Lumen Owners — Moving to AT&T"

WEEK_COLS = 10            # CAPTAIN TEAM: this week + 9 back (A..L, like the board)
KEEP_WEEKS = 14           # history lines older than this are dropped
METRICS = ("NewInternet", "Total")
BOXES = (
    # metric, title, product-summary label, units label
    ("NewInternet", "\U0001F4F6 AT&T SALES — INTERNET ONLY", "Fiber - New Internet",
     "Fiber - New Internet Units"),
    ("Total", "\U0001F6DC AT&T SALES — ALL UNITS", "Fiber - All Units",
     "Fiber - All Units"),
)
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")
NCOLS = 12                # A..L
COL_WIDTHS = (24, 240, 96, 96, 96, 96, 96, 96, 96, 125, 93, 93)

# Layout copied from Raf's box on the Org Sales Board, but in our own
# colours so nobody mistakes it for his captainship (Eve, 2026-10-21):
# New Internet = burgundy, All Units = plum, so the two boxes tell apart.
WHITE, BLACK = "#ffffff", "#000000"
HEAD_BG, GT_BG = "#999999", "#666666"
SHADE = "#f3f3f3"
NEG_BG, POS_BG = "#e6b8af", "#b6d7a8"
NEG_GT_FG, POS_GT_FG = "#dd7e6b", "#93c47d"
WE_BG = "#434343"
ZEBRA = "#efefef"
HDR_LAST_BG, HDR_PREV_BG = "#999999", "#d9d9d9"
TEAM_BG = "#e8e1e3"
PALETTES = {
    "NewInternet": dict(            # muted burgundy
        title_bg="#c4919b", title_fg="#5e2230", team_fg="#8a3a4c",
        section="#8a3a4c", units="#7a3343", units_fg="#f2d9de",
        name="#d7b3ba", day="#f1e4e7",
        run="#8a3a4c", last="#a65a6b", prev="#c4919b",
        run_tot="#4a1a26", last_tot="#5e2230", prev_tot="#7a3343",
        totals_fg="#f2b8c4"),
    "Total": dict(                  # muted plum
        title_bg="#a993b8", title_fg="#3f2a52", team_fg="#664a7d",
        section="#664a7d", units="#57406b", units_fg="#e4d9ee",
        name="#c8b8d4", day="#ece5f1",
        run="#664a7d", last="#8569a0", prev="#a993b8",
        run_tot="#2f1f3d", last_tot="#3f2a52", prev_tot="#57406b",
        totals_fg="#d4bfe6"),
}
DISPLAY = "Alfa Slab One"
SERIF = "Georgia"


# --------------------------------------------------------------- history

def week_ending(d: dt.date) -> dt.date:
    """The Sunday of d's Mon-Sun calendar week. Pure."""
    return d + dt.timedelta(days=6 - d.weekday())


def history_to_weeks(lines: List[List[str]]) -> Dict[dt.date, Dict[str, dict]]:
    """`_lumen_history` lines -> {week_ending: {owner: {metric: {date: n}}}}.
    The same shape pull_programs returns, so att_metrics() reads it as is.
    The header line and anything unparsable are skipped. Pure."""
    out: Dict[dt.date, Dict[str, dict]] = {}
    for ln in lines:
        if len(ln) < 3:
            continue
        try:
            we = dt.date.fromisoformat(ln[0].strip())
        except ValueError:
            continue
        metric, owner = ln[1].strip(), ln[2].strip()
        if not owner or metric not in METRICS:
            continue
        per = out.setdefault(we, {}).setdefault(owner, {}).setdefault(metric, {})
        for i in range(7):
            cell = ln[3 + i].strip() if 3 + i < len(ln) else ""
            if cell:
                try:
                    per[we - dt.timedelta(days=6 - i)] = int(float(cell))
                except ValueError:
                    pass
    return out


def weeks_to_history(weeks: Dict[dt.date, Dict[str, dict]],
                     keep_from: dt.date) -> List[List]:
    """Inverse of history_to_weeks, newest week first, weeks before
    `keep_from` dropped. A day with no sales is written blank, the way the
    crosstab leaves it. Pure."""
    out: List[List] = [["week_ending", "metric", "owner"] + list(DAY_NAMES)]
    for we in sorted(weeks, reverse=True):
        if we < keep_from:
            continue
        for owner in sorted(weeks[we], key=str.casefold):
            for metric in METRICS:
                per = (weeks[we][owner] or {}).get(metric)
                if per is None:
                    continue
                days = [we - dt.timedelta(days=6 - i) for i in range(7)]
                out.append([we.isoformat(), metric, owner]
                           + [per.get(d, "") for d in days])
    return out


# --------------------------------------------------------------- numbers

def owner_week(owner: str, weeks: Dict[dt.date, Dict[str, dict]], we: dt.date,
               metric: str, aliases) -> Optional[Dict[dt.date, int]]:
    """This owner's {date: n} for one week, {} when the crosstab did not list
    them (= sold nothing), None when that WEEK is missing altogether (pull
    failed and never stored) — a dash, not a zero that looks real."""
    from automations.lumen_owners.run import att_metrics
    if we not in weeks:
        return None
    return dict(att_metrics(owner, weeks[we], aliases).get(metric) or {})


def box_numbers(owners: Sequence[str], weeks: Dict[dt.date, Dict[str, dict]],
                this_week: List[dt.date], today: dt.date, metric: str,
                aliases) -> dict:
    """Everything one box prints, as plain numbers. Pure given its inputs.

      days        this week's 7 dates
      shown       which of them are not in the future (the rest stay blank)
      wes         the CAPTAIN TEAM week endings, newest first
      owners      [(name, {we: total|None}, {date: n})], most this week first
      team_days   this week's team total per day
      last_days   last week's team total per day (None = week missing)
      avg_days    4-week average per day over the weeks we have (None = none)
    """
    cur = this_week[-1]
    wes = [cur - dt.timedelta(days=7 * i) for i in range(WEEK_COLS)]
    rows = []
    for o in owners:
        totals = {}
        for we in wes:
            per = owner_week(o, weeks, we, metric, aliases)
            totals[we] = None if per is None else sum(per.values())
        days = owner_week(o, weeks, cur, metric, aliases) or {}
        rows.append((o, totals, days))
    rows.sort(key=lambda r: (-(r[1][cur] or 0), r[0].casefold()))

    def team_day(we: dt.date, i: int) -> Optional[int]:
        if we not in weeks:
            return None
        d = we - dt.timedelta(days=6 - i)
        return sum((owner_week(o, weeks, we, metric, aliases) or {}).get(d, 0)
                   for o in owners)

    team = [team_day(cur, i) or 0 for i in range(7)]
    last = [team_day(wes[1], i) for i in range(7)]
    avg = []
    for i in range(7):
        vals = [v for v in (team_day(wes[k], i) for k in range(1, 5))
                if v is not None]
        avg.append(round(sum(vals) / len(vals)) if vals else None)
    # Tableau loads a day only the NEXT day, so today is blank, never a 0
    # that reads as "nobody sold" (Eve, 2026-10-24).
    return {"days": list(this_week), "shown": [d < today for d in this_week],
            "wes": wes, "owners": rows, "team_days": team,
            "last_days": last, "avg_days": avg}


def _pct(now: Optional[float], then: Optional[float]) -> Optional[float]:
    if now is None or not then:
        return None
    return (now - then) / then


# --------------------------------------------------------------- layout

def _color(hex_: str) -> dict:
    h = hex_.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


def _fmt(bg=WHITE, fg=BLACK, font=SERIF, size=12, bold=False, pct=False,
         border=True, wrap=False) -> dict:
    f = {"backgroundColor": _color(bg),
         "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
         "textFormat": {"foregroundColor": _color(fg), "fontFamily": font,
                        "fontSize": size, "bold": bold}}
    if pct:
        f["numberFormat"] = {"type": "PERCENT", "pattern": "0%"}
    if wrap:
        f["wrapStrategy"] = "WRAP"
    if border:
        line = {"style": "SOLID", "color": _color(BLACK)}
        f["borders"] = {k: line for k in ("top", "bottom", "left", "right")}
    return f


class Grid:
    """Cells + merges + row heights for the tab, built row by row. Pure."""

    def __init__(self):
        self.cells: Dict[Tuple[int, int], Tuple[object, dict]] = {}
        self.merges: List[Tuple[int, int, int, int]] = []   # r0, r1, c0, c1 (excl)
        self.heights: Dict[int, int] = {}
        # conditional colours: (r0, r1, c0, c1 excl, custom formula, format)
        self.rules: List[Tuple[int, int, int, int, str, dict]] = []
        self.row = 0

    def put(self, r: int, c: int, value, fmt: dict):
        self.cells[(r, c)] = (value, fmt)

    def merge(self, r: int, c0: int, c1: int, rows: int = 1):
        self.merges.append((r, r + rows, c0, c1))

    def skip(self, n: int = 1):
        self.row += n


def _box(g: Grid, n: dict, metric: str, title: str, ps_label: str,
         units_label: str, team_title: str) -> Tuple[int, int]:
    """Lay one box (New Internet or All Units) out from g.row down. Returns
    its (first row, last row), 0-based, for the email picture."""
    from automations.lumen_owners.run import pretty_name
    p = PALETTES[metric]
    top = g.row
    shown = n["shown"]

    def merged_title(text, fmt, height=None):
        g.put(g.row, 1, text, fmt)
        g.merge(g.row, 1, 10)
        if height:
            g.heights[g.row] = height
        g.skip()

    merged_title(title, _fmt(p["title_bg"], p["title_fg"], DISPLAY, 20), 38)
    merged_title(team_title, _fmt(TEAM_BG, p["team_fg"], DISPLAY, 20), 34)
    g.skip()

    team = n["team_days"]

    # Sales tables first (Eve, 2026-10-21), the summaries under them.
    # CAPTAIN TEAM — one column per week ending, newest first.
    g.put(g.row, 0, "FORMER LUMEN OWNERS", _fmt(TEAM_BG, p["team_fg"], DISPLAY, 14))
    g.merge(g.row, 0, 2)
    g.heights[g.row] = 34
    for k, we in enumerate(n["wes"]):
        g.put(g.row, 2 + k, "WE %02d.%02d" % (we.month, we.day),
              _fmt(WE_BG, WHITE, SERIF, 11, True))
    g.skip()
    g.put(g.row, 0, units_label, _fmt(p["units"], WHITE, SERIF, 12, True))
    g.merge(g.row, 0, 2)
    for k in range(WEEK_COLS):
        g.put(g.row, 2 + k, "", _fmt(p["units"]))
    g.skip()
    team_first = g.row
    for i, (name, totals, _days) in enumerate(n["owners"]):
        bg = WHITE if i % 2 == 0 else ZEBRA
        g.put(g.row, 0, i + 1, _fmt(WHITE, BLACK, "Arial", 10))
        g.put(g.row, 1, pretty_name(name), _fmt(p["name"], BLACK, SERIF, 12, True))
        for k, we in enumerate(n["wes"]):
            v = totals[we]
            g.put(g.row, 2 + k, "–" if v is None else v,
                  _fmt(bg, BLACK, SERIF, 12, True))
        g.skip()
    team_tot = g.row
    g.put(g.row, 0, "TOTALS", _fmt(BLACK, WHITE, SERIF, 14, True))
    g.merge(g.row, 0, 2)
    for k, we in enumerate(n["wes"]):
        vals = [t[we] for _, t, _ in n["owners"]]
        tot = "–" if any(v is None for v in vals) else sum(vals)
        g.put(g.row, 2 + k, tot, _fmt(BLACK, WHITE, SERIF, 14, True))
    g.skip(2)

    # Daily board — owner x Mon-Sun + this week / last week / the week before.
    g.put(g.row, 0, units_label,
          _fmt(p["units"], p["units_fg"], DISPLAY, 14, wrap=True))
    g.merge(g.row, 0, 2, rows=2)
    for i, d in enumerate(DAY_NAMES):
        g.put(g.row, 2 + i, d, _fmt(BLACK, WHITE, SERIF, 8, True))
        g.put(g.row + 1, 2 + i, n["days"][i].day, _fmt(BLACK, WHITE, SERIF, 8, True))
    for c, (label, bg, fg) in zip((9, 10, 11), (
            ("RUNNING WEEK TOTALS", WE_BG, WHITE),
            ("LAST WEEK'S TOTALS", HDR_LAST_BG, WHITE),
            ("PREVIOUS WEEK'S TOTALS", HDR_PREV_BG, BLACK))):
        g.put(g.row, c, label, _fmt(bg, fg, SERIF, 7, True, wrap=True))
        g.merge(g.row, c, c + 1, rows=2)
    g.skip(2)
    wes = n["wes"]
    day_first = g.row
    for i, (name, totals, days) in enumerate(n["owners"]):
        g.put(g.row, 0, i + 1, _fmt(WHITE, BLACK, "Arial", 10))
        g.put(g.row, 1, pretty_name(name), _fmt(p["name"], BLACK, SERIF, 12, True))
        for k, d in enumerate(n["days"]):
            g.put(g.row, 2 + k, days.get(d, 0) if shown[k] else "",
                  _fmt(p["day"], BLACK, SERIF, 12, True))
        for c, we, bg, size in ((9, wes[0], p["run"], 14), (10, wes[1], p["last"], 12),
                                (11, wes[2], p["prev"], 12)):
            v = totals[we]
            g.put(g.row, c, "–" if v is None else v,
                  _fmt(bg, BLACK, SERIF, size, True))
        g.skip()
    g.put(g.row, 0, "Totals", _fmt(BLACK, p["totals_fg"], SERIF, 12, True))
    g.merge(g.row, 0, 2)
    for k in range(7):
        g.put(g.row, 2 + k, team[k] if shown[k] else "",
              _fmt(BLACK, WHITE, SERIF, 14, True))
    for c, we, bg, size in ((9, wes[0], p["run_tot"], 14), (10, wes[1], p["last_tot"], 12),
                            (11, wes[2], p["prev_tot"], 12)):
        vals = [t[we] for _, t, _ in n["owners"]]
        tot = "–" if any(v is None for v in vals) else sum(vals)
        g.put(g.row, c, tot, _fmt(bg, WHITE, SERIF, size, True))
    day_tot = g.row
    g.skip(3)

    def header(first: str, first_size: int):
        g.put(g.row, 1, first, _fmt(HEAD_BG, BLACK, SERIF, first_size, True))
        for i, d in enumerate(DAY_NAMES):
            g.put(g.row, 2 + i, d, _fmt(HEAD_BG, BLACK, SERIF, 11, True))
        g.put(g.row, 9, "Grand Total", _fmt(GT_BG, WHITE, SERIF, 12, True))
        g.skip()

    # Product Summary - This Week
    merged_title("Product Summary - This Week",
                 _fmt(p["section"], WHITE, SERIF, 14, True))
    header("Product Type", 12)
    wtd = sum(v for v, s in zip(team, shown) if s)
    ps_row = g.row
    g.put(g.row, 1, ps_label, _fmt())
    for i in range(7):
        g.put(g.row, 2 + i, team[i] if shown[i] else "", _fmt())
    g.put(g.row, 9, wtd, _fmt(GT_BG, WHITE, SERIF, 12, True))
    g.skip(2)

    # Current vs Prior Weeks. The Grand Total column compares the SAME days
    # (week to date), so a Tuesday is never measured against a full week.
    merged_title("Current vs Prior Weeks", _fmt(p["section"], WHITE, SERIF, 14, True))
    header("Mon-Sun", 10)
    last, avg = n["last_days"], n["avg_days"]

    def wtd_of(vals):
        got = [v for v, s in zip(vals, shown) if s]
        return None if any(v is None for v in got) else sum(got)

    lines = [
        ("Sales - This Week", WHITE, [t if s else "" for t, s in zip(team, shown)],
         wtd, False),
        ("vs Prior Week", SHADE,
         [_pct(t, l) if s else None for t, l, s in zip(team, last, shown)],
         _pct(wtd, wtd_of(last)), True),
        ("vs 4 WeekAVG", WHITE,
         [_pct(t, a) if s else None for t, a, s in zip(team, avg, shown)],
         _pct(wtd, wtd_of(avg)), True),
        ("Sales (Last Week)", SHADE, last, wtd_of(last), False),
        ("Sales ( 4 Week AVG)", WHITE, avg, wtd_of(avg), False),
    ]
    cvp = g.row                 # rows cvp..cvp+4 = the five lines below
    for label, bg, vals, gt, is_pct in lines:
        g.put(g.row, 1, label, _fmt(bg))
        for i, v in enumerate(vals):
            g.put(g.row, 2 + i, "" if v is None else v, _fmt(bg, pct=is_pct))
        if is_pct:
            g.put(g.row, 9, "" if gt is None else gt,
                  _fmt(GT_BG, WHITE, SERIF, 12, True, pct=True))
        else:
            g.put(g.row, 9, "" if gt is None else gt,
                  _fmt(GT_BG, WHITE, SERIF, 12, True))
        g.skip()
    g.skip()

    bottom = g.row - 2
    _wire_formulas(g, ps_row, cvp, team_first, team_tot, day_first, day_tot)
    g.skip(3)
    return top, bottom


def _col(c: int) -> str:
    return chr(ord("A") + c)


def _wire_formulas(g: Grid, ps: int, cvp: int, team_first: int, team_tot: int,
                   day_first: int, day_tot: int):
    """Swap the this-week numbers for formulas that read the daily board, so
    they follow it as each new day's sales land there (Eve, 2026-10-21):
    daily Totals -> Product Summary -> Sales This Week -> the % rows. The
    values put in first stay as the cell formats; only the value changes.
    Rows are 0-based in; formulas are 1-based."""
    def put(r, c, formula):
        g.cells[(r, c)] = (formula, g.cells[(r, c)][1])

    n_owners = day_tot - day_first
    if n_owners <= 0:
        return
    a, b = day_first + 1, day_tot              # owner rows of the daily board
    tot, ps1 = day_tot + 1, ps + 1
    this, prior, avg4, last, avg = (cvp + k + 1 for k in range(5))
    days = "C%d:I%d"
    for k in range(7):
        x = _col(2 + k)
        put(day_tot, 2 + k,
            '=IF(COUNT(%s%d:%s%d)=0,"",SUM(%s%d:%s%d))' % (x, a, x, b, x, a, x, b))
        put(ps, 2 + k, "=%s%d" % (x, tot))
        put(cvp, 2 + k, "=%s%d" % (x, ps1))
        for row, base in ((prior - 1, last), (avg4 - 1, avg)):
            put(row, 2 + k, '=IF(OR(%s%d="",N(%s%d)=0),"",%s%d/%s%d-1)'
                % (x, this, x, base, x, this, x, base))
    for r in range(day_first, day_tot):          # RUNNING WEEK TOTALS
        put(r, 9, "=SUM(%s)" % (days % (r + 1, r + 1)))
    put(day_tot, 9, "=SUM(J%d:J%d)" % (a, b))
    put(ps, 9, "=SUM(%s)" % (days % (tot, tot)))
    put(cvp, 9, "=J%d" % ps1)
    for row in (last - 1, avg - 1):              # same days only (week to date)
        put(row, 9, '=SUMPRODUCT(--(%s<>""),%s)'
            % (days % (this, this), days % (row + 1, row + 1)))
    for row, base in ((prior - 1, last), (avg4 - 1, avg)):
        put(row, 9, '=IF(N(J%d)=0,"",J%d/J%d-1)' % (base, this, base))
    for i in range(n_owners):                    # LUMEN TEAM, this week's column
        put(team_first + i, 2, "=J%d" % (day_first + i + 1))
    put(team_tot, 2, "=SUM(C%d:C%d)" % (team_first + 1, team_first + n_owners))

    # red / green follow the numbers instead of being painted once
    g.rules += [
        (prior - 1, avg4, 2, 9, "=AND(ISNUMBER(C%d),C%d<0)" % (prior, prior),
         {"backgroundColor": _color(NEG_BG)}),
        (prior - 1, avg4, 2, 9, "=AND(ISNUMBER(C%d),C%d>=0)" % (prior, prior),
         {"backgroundColor": _color(POS_BG)}),
        (prior - 1, avg4, 9, 10, "=AND(ISNUMBER(J%d),J%d<0)" % (prior, prior),
         {"textFormat": {"foregroundColor": _color(NEG_GT_FG)}}),
        (prior - 1, avg4, 9, 10, "=AND(ISNUMBER(J%d),J%d>=0)" % (prior, prior),
         {"textFormat": {"foregroundColor": _color(POS_GT_FG)}}),
    ]


def build_grid(owners: Sequence[str], weeks: Dict[dt.date, Dict[str, dict]],
               this_week: List[dt.date], today: dt.date, aliases,
               team_title: str = TEAM_TITLE) -> Tuple[Grid, List[Tuple[str, int, int]]]:
    """The whole tab: both boxes, stacked. Returns (grid, [(metric, top,
    bottom)]) — the row spans the email pictures. Pure given its inputs."""
    g = Grid()
    g.skip()
    spans = []
    for metric, title, ps_label, units_label in BOXES:
        n = box_numbers(owners, weeks, this_week, today, metric, aliases)
        top, bottom = _box(g, n, metric, title, ps_label, units_label, team_title)
        spans.append((metric, top, bottom))
    return g, spans


# --------------------------------------------------------------- sheet I/O

def _cell_data(value, fmt: dict) -> dict:
    if value == "" or value is None:
        uev = None
    elif isinstance(value, bool):
        uev = {"stringValue": str(value)}
    elif isinstance(value, (int, float)):
        uev = {"numberValue": value}
    elif isinstance(value, str) and value.startswith("="):
        uev = {"formulaValue": value}
    else:
        uev = {"stringValue": str(value)}
    out = {"userEnteredFormat": fmt}
    if uev is not None:
        out["userEnteredValue"] = uev
    return out


def _open():
    from automations.recruiting_report import fill as F
    from automations.captainship_drafts.sales_board import SALES_BOARD_ID
    return F._client().open_by_key(SALES_BOARD_ID)


def _get_or_add(sh, title: str, rows: int, cols: int, hidden: bool = False):
    import gspread
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=rows, cols=cols)
        if hidden:
            sh.batch_update({"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "hidden": True},
                "fields": "hidden"}}]})
        return ws


def read_history(sh=None) -> Dict[dt.date, Dict[str, dict]]:
    sh = sh or _open()
    ws = _get_or_add(sh, HISTORY_TAB, 50, 10, hidden=True)
    return history_to_weeks(ws.get_all_values())


def write_history(weeks: Dict[dt.date, Dict[str, dict]], today: dt.date,
                  sh=None) -> int:
    """Rewrite the hidden history tab (small: ~200 lines a week). Returns the
    number of lines written."""
    sh = sh or _open()
    ws = _get_or_add(sh, HISTORY_TAB, 50, 10, hidden=True)
    lines = weeks_to_history(weeks, today - dt.timedelta(days=7 * KEEP_WEEKS))
    ws.resize(rows=max(len(lines), 2), cols=10)
    ws.batch_clear(["A:J"])
    ws.update(values=lines, range_name="A1", value_input_option="RAW")
    return len(lines) - 1


def write_tab(g: Grid, sh=None):
    """Clear the Lumen Owners tab and write the grid — values, formats,
    merges, sizes — in one batch. Returns the worksheet."""
    sh = sh or _open()
    nrows = max(g.row + 2, 60)
    ws = _get_or_add(sh, TAB, nrows, NCOLS)
    sid = ws.id
    reqs = [
        {"updateSheetProperties": {"properties": {
            "sheetId": sid,
            "gridProperties": {"rowCount": nrows, "columnCount": NCOLS,
                               "hideGridlines": True}},
            "fields": "gridProperties(rowCount,columnCount,hideGridlines)"}},
        {"unmergeCells": {"range": {"sheetId": sid}}},
        {"updateCells": {"range": {"sheetId": sid}, "fields": "*"}},
    ]
    for c, w in enumerate(COL_WIDTHS):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": c, "endIndex": c + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS",
                  "startIndex": 0, "endIndex": nrows},
        "properties": {"pixelSize": 23}, "fields": "pixelSize"}})
    for r, h in g.heights.items():
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": r, "endIndex": r + 1},
            "properties": {"pixelSize": h}, "fields": "pixelSize"}})
    rows = []
    blank = {"userEnteredFormat": {"backgroundColor": _color(WHITE)}}
    for r in range(g.row):
        rows.append({"values": [
            _cell_data(*g.cells[(r, c)]) if (r, c) in g.cells else blank
            for c in range(NCOLS)]})
    reqs.append({"updateCells": {
        "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": g.row,
                  "startColumnIndex": 0, "endColumnIndex": NCOLS},
        "rows": rows, "fields": "userEnteredValue,userEnteredFormat"}})
    for r0, r1, c0, c1 in g.merges:
        reqs.append({"mergeCells": {"mergeType": "MERGE_ALL", "range": {
            "sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}}})
    # conditional colours: drop last run's rules, then add this run's
    meta = sh.fetch_sheet_metadata(
        {"fields": "sheets(properties.sheetId,conditionalFormats)"})
    old = next((len(s.get("conditionalFormats") or []) for s in meta["sheets"]
                if s["properties"]["sheetId"] == sid), 0)
    reqs += [{"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}}] * old
    for i, (r0, r1, c0, c1, formula, fmt) in enumerate(g.rules):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": [{"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                        "startColumnIndex": c0, "endColumnIndex": c1}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": formula}]},
                "format": fmt}}}})
    sh.batch_update({"requests": reqs})
    return ws


def render_boxes(ws, spans: List[Tuple[str, int, int]], out_dir: Path
                 ) -> List[Tuple[str, Path]]:
    """One PNG per box, rendered from the tab's own cells and formats (the
    captainship drafts' renderer — API token, no Google browser login)."""
    from automations.captainship_drafts import sheet_render as SR
    out = []
    labels = {"NewInternet": "AT&T Sales — Internet Only",
              "Total": "AT&T Sales — All Units"}
    for metric, top, bottom in spans:
        a1 = "'%s'!A%d:L%d" % (ws.title, top + 1, bottom + 1)
        meta = SR._retrying(lambda: ws.spreadsheet.fetch_sheet_metadata(
            {"includeGridData": "true", "ranges": a1}))
        sheet = meta["sheets"][0]
        data = sheet["data"][0]
        grid = {"start_row": data.get("startRow", top),
                "start_col": data.get("startColumn", 0) or 0,
                "rows": data.get("rowData", []),
                "row_meta": data.get("rowMetadata", []),
                "col_meta": data.get("columnMetadata", []),
                "merges": sheet.get("merges", [])}
        html = SR._build_html(grid, NCOLS)
        png = SR._render_html_to_png(html, Path(out_dir) / ("lumen_%s.png" % metric),
                                     fonts_present=True)
        out.append((labels[metric], png))
    return out

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
IDENTITY = ["#", "Rep", "Team", "Leadership", "Tenure", "Status"]

TEAMS_COLS = (["Teams", "Team Weekly Goal", "Active Reps"] + PRODUCT_NAMES
              + ["TOTAL UNITS AVG", "NEW INT AVG", "% TO GOAL"])

# His fonts, read off the sheet.
FONT = "Georgia"
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

    banner += ["LAST WEEK'S TOTALS"]
    daynum += [""]
    cols += ["APPS"]

    for i, day in enumerate(DAYS):
        banner += [day] + [""] * len(DAY_PRODUCTS)
        daynum += [str((monday + dt.timedelta(days=i)).day)] + \
            [""] * len(DAY_PRODUCTS)
        cols += list(DAY_PRODUCTS) + [ROLL_CALL]

    cols[IDENTITY.index("Rep")] = week_label(d)     # his week label sits here
    return banner, daynum, cols


def carry_over_rows(prev_week_rows: list) -> list:
    """The rep rows a new week starts with, taken from LAST WEEK'S tab.

    EVERYONE CARRIES OVER unless somebody actually marked them Terminated — a
    new week must never begin by quietly dropping people, because the absence of
    a name is indistinguishable from an oversight. Terminating is a deliberate
    act; nothing else removes a rep.

    Only identity comes across. Production cells stay EMPTY, not zeroed: blank
    means the day hasn't happened, 0 means they were out and sold nothing, and
    opening a week with zeros tells every rep they already rolled one."""
    out = []
    for row in prev_week_rows:
        def cell(i):
            return (row[i].strip() if i < len(row) and row[i] else "")

        rep = cell(IDENTITY.index("Rep"))
        if not rep:
            continue
        if cell(IDENTITY.index("Status")).strip().lower() == "terminated":
            continue
        out.append([len(out) + 1, rep,
                    cell(IDENTITY.index("Team")),
                    cell(IDENTITY.index("Leadership")),
                    cell(IDENTITY.index("Tenure")),
                    cell(IDENTITY.index("Status")) or "Active"])
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
                "textFormat": {"fontFamily": FONT, "fontSize": 11}}},
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
        # his LAST WEEK'S TOTALS banner is red
        if "LAST WEEK'S TOTALS" in p["week_banner"]:
            reqs.append(_fill(ws.id, 0,
                              p["week_banner"].index("LAST WEEK'S TOTALS"),
                              BANNER_RED))

        prev = _previous_week_tab(existing, wk)
        if prev is not None:
            carried = carry_over_rows(_retry(prev.get_all_values)[FROZEN_ROWS:])
            if carried:
                _retry(ws.update, carried,
                       f"A{FROZEN_ROWS + 1}:F{FROZEN_ROWS + len(carried)}")
            p["carried_over"] = len(carried)

    if reqs:
        _retry(sh.batch_update, {"requests": reqs})
    return {**p, "created": made, "already_there": skipped}


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

    rows = _retry(wk.get_all_values)
    body = rows[FROZEN_ROWS:]
    rep_col = IDENTITY.index("Rep")
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
    _retry(wk.update,
           [[n0 + i + 1, n, "", "", "", "Active"] for i, n in enumerate(fresh)],
           f"A{first_free}:F{first_free + len(fresh) - 1}")
    out["added_to"].append(wk.title)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="build a sales board like Raf's")
    ap.add_argument("--write", action="store_true",
                    help="actually create/append (default is a dry run)")
    ap.add_argument("--sheet-id", default=SHEET_ID)
    ap.add_argument("--sync-new-reps", action="store_true",
                    help="add reps Tableau has that the sheet doesn't")
    a = ap.parse_args(argv)

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

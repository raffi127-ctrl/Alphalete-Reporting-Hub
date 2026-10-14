"""Keep Raf's one-table 2nd-round tab up to date. See layout.py for the why.

    python -m automations.raf_second_rounds.run                  # daily: new month / new leaders
    python -m automations.raf_second_rounds.run --dry-run        # print, write nothing
    python -m automations.raf_second_rounds.run --seed-from-real # first build: copy Sept+Oct
                                                                 # numbers from '2nd rds %'s'
    python -m automations.raf_second_rounds.run --rebuild --seed-from-real
                                     # back up, wipe IN PLACE (same link), lay out + seed again

Writes ONLY its own tab (layout.TAB) in Raf's All in One. The real
'2nd rds %'s' tab is only READ, and only by --seed-from-real.

What a run does:
  * tab missing -> builds it (header, color rules, legend, Month picker)
  * this month has no rows -> inserts the month's block ON TOP (its TOTALS +
    team rows, then board leaders + last month's off-board people who had
    numbers) and points the picker at it
  * otherwise -> adds any board leader the month is missing to the end of it
Never deletes a row and never writes a typed cell of an existing row.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Sequence

from automations.raf_second_rounds import layout as L

REAL_TAB = "2nd rds %'s"
TITLE_ROW, HEADER_ROW = 1, 2          # title + Month picker, then the table header
END_ROW = 2000                        # formulas, colors + picker cover down to here
KIND_COL = len(L.HEADERS) + 1         # L, hidden: 'sum' on TOTALS / team rows
# The color key: three chips on the title row, right of the Month picker.
# (Not below it: every new month is a full-row insert under the header, so
# anything sitting beside the table there gets pushed down with it.)
KEY_COL = len(L.HEADERS) - 3          # H
KEY = ["On goal", "Close", "Below goal"]

# The sheet's own soft palette instead of pure green / yellow / red.
GREEN = {"red": 0.718, "green": 0.882, "blue": 0.804}
YELLOW = {"red": 0.988, "green": 0.910, "blue": 0.698}
RED = {"red": 0.957, "green": 0.780, "blue": 0.765}
NAVY = {"red": 0.161, "green": 0.235, "blue": 0.333}
WHITE = {"red": 1, "green": 1, "blue": 1}
GREY_TEXT = {"red": 0.45, "green": 0.45, "blue": 0.45}
DARK = {"red": 0.13, "green": 0.13, "blue": 0.13}
STRIPE = {"red": 0.925, "green": 0.933, "blue": 0.945}      # every other leader row
LINE = {"red": 0.800, "green": 0.812, "blue": 0.835}        # cell borders
LEADER_FMT = {"textFormat": {"bold": False, "foregroundColor": {"red": 0.13, "green": 0.13, "blue": 0.13}},
              "backgroundColor": WHITE}
TEAM_FMT = {"textFormat": {"bold": True, "foregroundColor": NAVY},
            "backgroundColor": {"red": 0.851, "green": 0.890, "blue": 0.945}}
TOTAL_FMT = {"textFormat": {"bold": True, "fontSize": 11, "foregroundColor": WHITE},
             "backgroundColor": {"red": 0.267, "green": 0.384, "blue": 0.537}}


def _kind_fmt(v_team: str, kind: str) -> dict:
    if kind != L.SUM:
        return LEADER_FMT
    return TOTAL_FMT if v_team == L.TOTALS else TEAM_FMT


def row_style(sid: int, row: int, team: str, kind: str) -> List[dict]:
    """Look + borders for one table row (1-based). A month's TOTALS row
    opens it with a thick navy line on top, so months read as blocks."""
    n = len(L.HEADERS)
    thin = {"style": "SOLID", "color": LINE}
    out = [_fmt(sid, row - 1, row, 0, n, _kind_fmt(team, kind)),
           {"updateBorders": {"range": _rng(sid, row - 1, row, 0, n),
                              "top": thin, "bottom": thin, "left": thin, "right": thin,
                              "innerVertical": thin}},
           {"updateDimensionProperties": {
               "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": row - 1, "endIndex": row},
               "properties": {"pixelSize": 30 if kind == L.SUM else 24}, "fields": "pixelSize"}}]
    if kind == L.SUM and team == L.TOTALS:
        out.append({"updateBorders": {"range": _rng(sid, row - 1, row, 0, n),
                                      "top": {"style": "SOLID_THICK", "color": NAVY}}})
    return out


def stripe_rule(sid: int) -> dict:
    """Every other leader row light grey, counted inside its month so it
    stays even when someone is added mid-month. Lowest priority: a % cell's
    green / yellow / red wins over it."""
    r = HEADER_ROW + 1
    f = '=AND($A{r}<>"",$L{r}="",ISEVEN(COUNTIFS($A${h}:$A{r},$A{r},$L${h}:$L{r},"")))'.format(
        r=r, h=HEADER_ROW)
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [_rng(sid, HEADER_ROW, END_ROW, 0, len(L.HEADERS))],
        "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                      "values": [{"userEnteredValue": f}]},
                        "format": {"backgroundColor": STRIPE}}}}}



def header_labels() -> List[str]:
    """What the header row SHOWS: each % column carries its goal, which is
    what the old 'Metric Goals' box said. read_tab never looks these up."""
    return [h + "\n(goal %d%%+)" % round(L.PCTS[h][2] * 100) if h in L.PCTS else h
            for h in L.HEADERS] + [L.KIND]


def top_values(q: str) -> List[dict]:
    return [{"range": "'%s'!A%d" % (q, TITLE_ROW), "values": [["2nd Rounds — BOB Call / Stats"]]},
            {"range": "'%s'!%s%d" % (q, L.col_letter(KEY_COL), TITLE_ROW), "values": [KEY]},
            {"range": "'%s'!A%d" % (q, HEADER_ROW), "values": [header_labels()]}]


# ------------------------------------------------------------------ sources

def board_leaders(today: dt.date, logfn=print) -> List[L.Person]:
    """Non-terminated leaders (+ their Team) off this week's sales board tab."""
    from automations.gap_alerts import leaders as LD
    from automations.terminated_reps import board as BD
    sh = BD.open_by_key(BD.SHEET_ID)
    title = BD.pick_tab(sh, today, None)
    grid = sh.worksheet(title).get_values(value_render_option="UNFORMATTED_VALUE")
    titles = {BD._norm(v): i for i, v in enumerate(grid[0], 1) if BD._norm(v)}
    team_col = titles.get("team")
    out = []
    for ld in LD.leaders_from_grid(grid, levels=L.LEVELS):
        team = str(BD._cell(grid, ld.row, team_col) or "").strip() if team_col else ""
        out.append(L.Person(ld.name, team))
    logfn("  sales board %r: %d leader(s)" % (title, len(out)))
    return out


def real_tab_months(sh, year: int) -> Dict[str, List[tuple]]:
    """{'October 2026': [(team, name, {count header: value}), ...]} from the
    side-by-side real tab -- only the blocks laid out like this one (Team Name,
    Leader Name, then the same columns). Older months use another layout and
    are left where they are."""
    grid = sh.worksheet(REAL_TAB).get_values("A1:CZ80", value_render_option="UNFORMATTED_VALUE")
    top, hdr = grid[0], grid[1]
    out = {}
    for c, text in enumerate(top):
        m = re.match(r"\s*([A-Za-z]+)\s+BOB Call", str(text))
        if not m:
            continue
        want = [L.TEAM, L.LEADER] + L.HEADERS[3:]
        got = [" ".join(str(v).split()) for v in hdr[c:c + len(want)]]
        if got != want:
            continue
        cols = {h: c + i for i, h in enumerate(want)}
        rows = []
        for r in grid[2:]:
            r = list(r) + [""] * (c + len(want))
            name = str(r[cols[L.LEADER]]).strip()
            if name.upper() == "TOTALS":
                break                 # team summary + legend live below it
            if not name:
                continue
            rows.append((str(r[cols[L.TEAM]]).strip(), name,
                         {h: r[cols[h]] for h in L.COUNTS}))
        out["%s %d" % (m.group(1).capitalize(), year)] = rows
    return out


# ------------------------------------------------------------------ the tab

def read_tab(ws) -> tuple:
    """(header row, {title: column}, [Row]) -- columns by their titles."""
    grid = ws.get_values("A1:Z%d" % END_ROW)
    hrow = next((i + 1 for i, r in enumerate(grid[:15]) if L.LEADER in r), None)
    if not hrow:
        raise RuntimeError("%r has no 'Leader Name' header in its first 15 rows" % L.TAB)
    cols = {str(v).strip(): i + 1 for i, v in enumerate(grid[hrow - 1]) if str(v).strip()}
    rows = []
    for i, r in enumerate(grid[hrow:], start=hrow + 1):
        def at(h):
            c = cols.get(h)
            return str(r[c - 1]).strip() if c and c - 1 < len(r) else ""
        if at(L.MONTH):
            rows.append(L.Row(i, at(L.MONTH), at(L.TEAM), at(L.LEADER),
                              {h: at(h) for h in L.COUNTS}, at(L.KIND) == L.SUM))
    return hrow, cols, rows


def _rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _fmt(sid, r0, r1, c0, c1, f):
    fields = ",".join("userEnteredFormat.%s" % k for k in f)
    return {"repeatCell": {"range": _rng(sid, r0, r1, c0, c1),
                           "cell": {"userEnteredFormat": f}, "fields": fields}}


def _width(sid, c, px):
    return {"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}


def color_rules(sid: int) -> List[dict]:
    """Green / yellow / red per % column, cuts from the tab's Metric Goals.
    From the header row down, so rows inserted on top stay inside. A blank %
    (no denominator yet) is not a number, so it stays white."""
    out = []
    for i, h in enumerate(L.HEADERS):
        if h not in L.PCTS:
            continue
        _, _, g, r = L.PCTS[h]
        rng = _rng(sid, HEADER_ROW - 1, END_ROW, i, i + 1)
        for t, vals, bg in (("NUMBER_GREATER_THAN_EQ", ["%g" % g], GREEN),
                            ("NUMBER_BETWEEN", ["%g" % r, "%g" % (g - 0.0001)], YELLOW),
                            ("NUMBER_LESS", ["%g" % r], RED)):
            out.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [rng], "booleanRule": {
                    "condition": {"type": t, "values": [{"userEnteredValue": v} for v in vals]},
                    "format": {"backgroundColor": bg,
                               "textFormat": {"foregroundColor": DARK}}}}}})
    return out


def _build_requests(sid: int) -> List[dict]:
    n = len(L.HEADERS)
    reqs = [{"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {
        "frozenRowCount": HEADER_ROW, "frozenColumnCount": 3}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}}]
    reqs.append(_fmt(sid, 0, END_ROW, 0, KIND_COL,
                     {"textFormat": {"fontFamily": "Arial", "fontSize": 10},
                      "verticalAlignment": "MIDDLE"}))
    for r, px in ((TITLE_ROW, 64), (HEADER_ROW, 62)):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r - 1, "endIndex": r},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    reqs.append(_fmt(sid, 0, 1, 0, 1, {"textFormat": {
        "bold": True, "fontSize": 16, "foregroundColor": NAVY}}))
    reqs.append(_fmt(sid, HEADER_ROW - 1, HEADER_ROW, 0, n, {
        "textFormat": {"bold": True, "foregroundColor": WHITE}, "backgroundColor": NAVY,
        "wrapStrategy": "WRAP", "horizontalAlignment": "CENTER"}))
    body = (HEADER_ROW, END_ROW)
    reqs.append(_fmt(sid, *body, 0, 1, {
        "numberFormat": {"type": "DATE", "pattern": "mmmm yyyy"},
        "textFormat": {"foregroundColor": GREY_TEXT}}))
    for i, h in enumerate(L.HEADERS):
        if h in L.PCTS:
            reqs.append(_fmt(sid, *body, i, i + 1, {
                "numberFormat": {"type": "PERCENT", "pattern": "0%"},
                "horizontalAlignment": "CENTER"}))
        elif h in L.COUNTS:
            reqs.append(_fmt(sid, *body, i, i + 1, {"horizontalAlignment": "CENTER"}))
    widths = {L.MONTH: 115, L.TEAM: 125, L.LEADER: 230}
    reqs += [_width(sid, i, widths.get(h, 92)) for i, h in enumerate(L.HEADERS)]
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS",
                  "startIndex": KIND_COL - 1, "endIndex": KIND_COL},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
    for k, bg in enumerate((GREEN, YELLOW, RED)):
        reqs.append(_fmt(sid, 0, 1, KEY_COL - 1 + k, KEY_COL + k, {
            "backgroundColor": bg, "horizontalAlignment": "CENTER",
            "textFormat": {"bold": True, "foregroundColor": NAVY}}))
    reqs.append(stripe_rule(sid))     # first in = ends up last = lowest priority
    reqs += color_rules(sid)
    # The Month picker (a slicer on column A), on the title row.
    reqs.append({"addSlicer": {"slicer": {
        "spec": {"dataRange": _rng(sid, HEADER_ROW - 1, END_ROW, 0, KIND_COL),
                 "columnIndex": 0, "title": "Pick a month", "applyToPivotTables": False},
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": sid, "rowIndex": 0, "columnIndex": 3},
            "offsetXPixels": 8, "offsetYPixels": 6,
            "widthPixels": 300, "heightPixels": 52}}}}})
    return reqs


def _wipe_requests(sh, sid: int) -> List[dict]:
    """Everything on OUR tab back to blank, same sheet id (so the link people
    already have keeps working): cells, color rules, slicers, frozen panes."""
    from automations.shared import sheets_retry as RETRY
    meta = RETRY.call(sh.fetch_sheet_metadata, params={
        "fields": "sheets(properties(sheetId),slicers(slicerId),conditionalFormats)"})
    me = next(s for s in meta["sheets"] if s["properties"]["sheetId"] == sid)
    reqs = [{"deleteEmbeddedObject": {"objectId": s["slicerId"]}} for s in me.get("slicers", [])]
    reqs += [{"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}}
             for _ in me.get("conditionalFormats", [])]
    reqs.append({"updateCells": {"range": {"sheetId": sid}, "fields": "*"}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS"},
        "properties": {"hiddenByUser": False}, "fields": "hiddenByUser"}})
    reqs.append({"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {
        "frozenRowCount": 0, "frozenColumnCount": 0}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}})
    return reqs


def build_tab(sh, ws=None, logfn=print):
    """Lay the tab out: title, header, legend, colors, Month picker. `ws`
    given = lay out that (already wiped) sheet in place."""
    from automations.shared import sheets_retry as RETRY
    if ws is None:
        ws = RETRY.call(sh.add_worksheet, title=L.TAB, rows=END_ROW, cols=20)
    q = L.TAB.replace("'", "''")
    RETRY.call(sh.values_batch_update, {"valueInputOption": "USER_ENTERED",
                                        "data": top_values(q)})
    RETRY.call(sh.batch_update, {"requests": _build_requests(ws.id)})
    logfn("  built %r" % L.TAB)
    return ws


def backup(ws, logfn=print) -> None:
    """Values + formulas of our tab to output/ before a rebuild."""
    import json
    import pathlib
    out = pathlib.Path(__file__).resolve().parents[2] / "output"
    out.mkdir(exist_ok=True)
    f = out / ("raf-2nd-rds-test-tab-backup-%s.json" % dt.datetime.now().strftime("%Y-%m-%d-%H%M"))
    vals = ws.get_values("A1:Z%d" % END_ROW, value_render_option="FORMULA")
    f.write_text(json.dumps({"tab": L.TAB, "values": vals}, ensure_ascii=False), encoding="utf-8")
    logfn("  backup -> %s" % f)


def insert_rows(sh, ws, at_row: int, values: List[list], logfn=print) -> None:
    """INSERT rows at `at_row` (never overwrite), fill them, and paint each
    one as what it is (TOTALS / team / leader) -- an inserted row copies its
    neighbor's look, which may be the wrong kind."""
    from automations.shared import sheets_retry as RETRY
    if not values:
        return
    sid = ws.id
    reqs = [{"insertDimension": {
        "range": {"sheetId": sid, "dimension": "ROWS",
                  "startIndex": at_row - 1, "endIndex": at_row - 1 + len(values)},
        "inheritFromBefore": at_row - 1 > HEADER_ROW}}]
    for i, v in enumerate(values):
        reqs += row_style(sid, at_row + i, v[1], v[-1])
    RETRY.call(sh.batch_update, {"requests": reqs})
    RETRY.call(sh.values_batch_update, {"valueInputOption": "USER_ENTERED", "data": [{
        "range": "'%s'!A%d:%s%d" % (L.TAB.replace("'", "''"), at_row,
                                     L.col_letter(KIND_COL), at_row + len(values) - 1),
        "values": values}]})
    logfn("  inserted %d row(s) at row %d" % (len(values), at_row))


def restyle(sh, ws, rows: Sequence[L.Row], logfn=print) -> None:
    """Re-paint the whole tab in today's look WITHOUT touching a value: our
    color rules are swapped for the current ones, every table row gets its
    kind's look + borders."""
    from automations.shared import sheets_retry as RETRY
    meta = RETRY.call(sh.fetch_sheet_metadata, params={
        "fields": "sheets(properties(sheetId),conditionalFormats)"})
    me = next(s for s in meta["sheets"] if s["properties"]["sheetId"] == ws.id)
    reqs = [{"deleteConditionalFormatRule": {"sheetId": ws.id, "index": 0}}
            for _ in me.get("conditionalFormats", [])]
    # The first layout's legend box (N..Q) and whatever the inserts dragged
    # down with it: blank out everything right of the hidden Kind column.
    reqs.append({"updateCells": {"range": {"sheetId": ws.id, "startColumnIndex": KIND_COL},
                                 "fields": "*"}})
    reqs += [r for r in _build_requests(ws.id)
             if "addSlicer" not in r and "addConditionalFormatRule" not in r]
    reqs.append(stripe_rule(ws.id))
    reqs += color_rules(ws.id)
    for r in rows:
        reqs += row_style(ws.id, r.row, r.team, L.SUM if r.summary else "")
    RETRY.call(sh.batch_update, {"requests": reqs})
    RETRY.call(sh.values_batch_update, {"valueInputOption": "USER_ENTERED",
                                        "data": top_values(L.TAB.replace("'", "''"))})
    logfn("  restyled %d row(s)" % len(rows))


def show_month(sh, ws, month: str, months: Sequence[str], logfn=print) -> None:
    """Point the picker at `month` (hide every other month)."""
    from automations.shared import sheets_retry as RETRY
    meta = RETRY.call(sh.fetch_sheet_metadata, params={"fields": "sheets(properties(sheetId),slicers)"})
    slicers = next((s.get("slicers", []) for s in meta["sheets"]
                    if s["properties"]["sheetId"] == ws.id), [])
    if not slicers:
        logfn("  ! no Month picker on the tab -- left alone")
        return
    hidden = [m for m in months if m != month]
    reqs = []
    for s in slicers:
        spec = dict(s["spec"])
        spec["filterCriteria"] = {"hiddenValues": hidden} if hidden else {}
        reqs.append({"updateSlicerSpec": {"slicerId": s["slicerId"], "spec": spec,
                                          "fields": "filterCriteria"}})
    RETRY.call(sh.batch_update, {"requests": reqs})
    logfn("  picker -> %s" % month)


# ------------------------------------------------------------------ main

def month_rows(month: str, people: Sequence[L.Person], at: int,
               counts: Sequence[dict] = ()) -> List[list]:
    """A whole new month block starting at sheet row `at`: TOTALS + team
    rows, then one row per person (with `counts[i]` typed in, when seeding)."""
    head = L.summary_values(month, L.month_teams(people), at, HEADER_ROW, END_ROW)
    body = [L.row_values(month, p, at + len(head) + i, counts[i] if counts else None)
            for i, p in enumerate(people)]
    return head + body


def plan(rows: List[L.Row], leaders: List[L.Person], month: str,
         first_data_row: int) -> tuple:
    """(row to insert at, [values], is_new_month). Pure, for the tests."""
    mine, after = L.month_block(rows, month)
    if after is None:
        prev = L.months_in(rows)
        last = [r for r in rows if prev and r.month == prev[0] and not r.summary]
        people = L.new_month_people(leaders, last)
        return first_data_row, month_rows(month, people, first_data_row), True
    missing = L.missing_from_month(leaders, mine)
    vals = [L.row_values(month, p, after + i) for i, p in enumerate(missing)]
    return after, vals, False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing.")
    ap.add_argument("--date", help="Run as if today were YYYY-MM-DD (tests a month change).")
    ap.add_argument("--seed-from-real", action="store_true",
                    help="Empty tab only: copy the months laid out like this one "
                         "(Sept + Oct 2026) from the real '2nd rds %%'s' tab first.")
    ap.add_argument("--rebuild", action="store_true",
                    help="Back the tab up to output/, wipe it IN PLACE (same link) "
                         "and lay it out again. Pair with --seed-from-real.")
    ap.add_argument("--restyle", action="store_true",
                    help="Re-paint the tab (colors, borders, stripes); no value changes.")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from automations.recruiting_report.fill import open_by_key
    from automations.shared import sheets_retry as RETRY
    from automations.shared.workbooks import ALL_IN_ONE_RAF
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    month = L.month_label(today)
    sh = open_by_key(ALL_IN_ONE_RAF)
    leaders = board_leaders(today)

    titles = [w.title for w in sh.worksheets()]
    if L.TAB not in titles or a.rebuild:
        if a.dry_run:
            print("  (dry run) would %s %r" % ("rebuild" if a.rebuild else "build", L.TAB))
            return 0
        if L.TAB in titles:
            ws = sh.worksheet(L.TAB)
            backup(ws)
            RETRY.call(sh.batch_update, {"requests": _wipe_requests(sh, ws.id)})
            build_tab(sh, ws)
        else:
            build_tab(sh)
    ws = sh.worksheet(L.TAB)
    hrow, cols, rows = read_tab(ws)
    first = hrow + 1
    if a.restyle:
        if a.dry_run:
            print("  (dry run) would restyle %d row(s)" % len(rows))
        else:
            restyle(sh, ws, rows)
        return 0

    if a.seed_from_real:
        if rows:
            print("  tab already has rows -- --seed-from-real only runs on an empty tab")
            return 1
        seeded = real_tab_months(sh, today.year)
        vals = []
        for m, people in seeded.items():       # left-to-right = newest first
            people = sorted(people, key=lambda p: p[1].lower())
            vals += month_rows(m, [L.Person(name, team) for team, name, _ in people],
                               first + len(vals), [c for _, _, c in people])
        print("  seed: %s" % ", ".join("%s (%d)" % (m, len(p)) for m, p in seeded.items()))
        if not a.dry_run:
            insert_rows(sh, ws, first, vals)
            hrow, cols, rows = read_tab(ws)

    at, vals, new_month = plan(rows, leaders, month, first)
    for v in vals:
        print("  + %s | %s | %s" % (v[0], v[1], v[2]))
    if a.dry_run:
        print("  (dry run) would insert %d row(s) at row %d%s"
              % (len(vals), at, " (new month)" if new_month else ""))
        return 0
    insert_rows(sh, ws, at, vals)
    if new_month or a.seed_from_real:
        show_month(sh, ws, month, L.months_in(read_tab(ws)[2]))
    print("  done: %s, %d row(s) added" % (month, len(vals)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

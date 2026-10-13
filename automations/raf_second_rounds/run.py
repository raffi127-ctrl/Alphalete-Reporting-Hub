"""Keep Raf's one-table 2nd-round tab up to date. See layout.py for the why.

    python -m automations.raf_second_rounds.run                  # daily: new month / new leaders
    python -m automations.raf_second_rounds.run --dry-run        # print, write nothing
    python -m automations.raf_second_rounds.run --seed-from-real # first build: copy Sept+Oct
                                                                 # numbers from '2nd rds %'s'

Writes ONLY its own tab (layout.TAB) in Raf's All in One. The real
'2nd rds %'s' tab is only READ, and only by --seed-from-real.

What a run does:
  * tab missing -> builds it (headers, TOTALS, color rules, legend, Month picker)
  * this month has no rows -> inserts the month's block ON TOP (board leaders +
    last month's off-board people who had numbers) and points the picker at it
  * otherwise -> adds any board leader the month is missing to the end of it
Never deletes a row and never writes a typed cell of an existing row.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Sequence

from automations.raf_second_rounds import layout as L

REAL_TAB = "2nd rds %'s"
# Rows ABOVE the leader table never move: every insert happens below its
# header. So the team summary and TOTALS sit up there, and their columns line
# up with the table's (Team Name over Team Name, counts over counts).
TEAMS = ["Alphaletes", "Ceaseless", "Hashiras", "Mindset Engine", "Se7en Sins", "Terminated"]
TEAM_HEADER_ROW = 3
TOTALS_ROW = TEAM_HEADER_ROW + len(TEAMS) + 2
HEADER_ROW = TOTALS_ROW + 2
END_ROW = 2000                # color rules + picker cover down to here
LEADERS_ON_TEAM, CONDUCTING = "Total Leaders on Team", "Leaders conducting interviews"
# Hidden helper column: =SUBTOTAL(103,A<row>) is 1 when the picker shows the
# row, 0 when it hides it. The team summary SUMIFS on it. (SUBTOTAL over a
# whole column follows the picker, but it can't be combined with a Team
# match; the OFFSET-array trick that does that in Excel returns 0 in Sheets.)
VISIBLE_COL = len(L.HEADERS) + 2          # M: one empty column after the table


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
                              {h: at(h) for h in L.COUNTS}))
    return hrow, cols, rows


def _build_requests(sid: int) -> List[dict]:
    from automations.sheet_format_audit import audit as A
    reqs = []
    ncol = len(L.HEADERS) + 1          # + 'Leaders conducting' in the summary

    def rng(r0, r1, c0, c1):
        return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def fmt(r, f, fields):
        reqs.append({"repeatCell": {"range": r, "cell": {"userEnteredFormat": f},
                                    "fields": "userEnteredFormat(%s)" % fields}})

    grey = {"red": 0.85, "green": 0.85, "blue": 0.85}
    head = {"textFormat": {"bold": True}, "wrapStrategy": "WRAP",
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "backgroundColor": grey}
    head_f = "textFormat,wrapStrategy,horizontalAlignment,verticalAlignment,backgroundColor"
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 60}, "fields": "pixelSize"}})
    fmt(rng(0, 1, 0, 3), {"textFormat": {"bold": True, "fontSize": 14},
                          "verticalAlignment": "MIDDLE"}, "textFormat,verticalAlignment")
    fmt(rng(TEAM_HEADER_ROW - 1, TEAM_HEADER_ROW, 1, ncol), head, head_f)
    fmt(rng(HEADER_ROW - 1, HEADER_ROW, 0, ncol - 1), head, head_f)
    fmt(rng(TOTALS_ROW - 1, TOTALS_ROW, 1, ncol),
        {"textFormat": {"bold": True},
         "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.83}},
        "textFormat,backgroundColor")
    for i, h in enumerate(L.HEADERS + [CONDUCTING]):
        if h in L.PCTS:
            fmt(rng(TEAM_HEADER_ROW, END_ROW, i, i + 1),
                {"numberFormat": {"type": "PERCENT", "pattern": "0%"},
                 "horizontalAlignment": "CENTER"}, "numberFormat,horizontalAlignment")
        elif h in L.COUNTS or h in (CONDUCTING,):
            fmt(rng(TEAM_HEADER_ROW, END_ROW, i, i + 1),
                {"horizontalAlignment": "CENTER"}, "horizontalAlignment")
    fmt(rng(HEADER_ROW, END_ROW, 0, 1),
        {"textFormat": {"foregroundColor": {"red": 0.4, "green": 0.4, "blue": 0.4}}},
        "textFormat")
    widths = {L.MONTH: 115, L.TEAM: 120, L.LEADER: 190, CONDUCTING: 110}
    for i, h in enumerate(L.HEADERS + [CONDUCTING]):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": widths.get(h, 95)}, "fields": "pixelSize"}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS",
                  "startIndex": VISIBLE_COL - 1, "endIndex": VISIBLE_COL},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
    # Colors: one set of rules per % column, team summary through END_ROW.
    for i, h in enumerate(L.HEADERS):
        if h in L.PCTS:
            num, den, green, red = L.PCTS[h]
            m = A.Metric(h, h, num, den, green, red)
            for rule in reversed(A.color_rules(sid, m, i + 1, TEAM_HEADER_ROW + 1, END_ROW)):
                reqs.append({"addConditionalFormatRule": {"rule": rule, "index": 0}})
    # The Month picker (a slicer on column A of the leader table).
    reqs.append({"addSlicer": {"slicer": {
        "spec": {"dataRange": rng(HEADER_ROW - 1, END_ROW, 0, ncol - 1), "columnIndex": 0,
                 "title": "Pick a month", "applyToPivotTables": False},
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": sid, "rowIndex": 0, "columnIndex": 3},
            "offsetXPixels": 10, "offsetYPixels": 4,
            "widthPixels": 280, "heightPixels": 52}}}}})
    return reqs


def _top_values() -> List[list]:
    """Rows 1 .. HEADER_ROW: title, team summary, TOTALS, the table header.

    Everything counts only the rows the picker shows: SUBTOTAL(103/109, ...)
    skips hidden rows, and the OFFSET form applies it row by row so it can be
    combined with a Team match. Ranges start AT the header row, so rows
    inserted under it (a new month goes on top) fall inside them."""
    col = {h: i + 1 for i, h in enumerate(L.HEADERS)}
    H, E = HEADER_ROW, END_ROW
    v = "$%s$%d:$%s$%d" % (L.col_letter(VISIBLE_COL), H, L.col_letter(VISIBLE_COL), E)
    d = "$D$%d:$D$%d" % (H, E)

    def pct(h, r):
        num, den = L.PCTS[h][0], L.PCTS[h][1]
        return "=iferror(%s%d/%s%d,0)" % (L.col_letter(col[num]), r, L.col_letter(col[den]), r)

    team_hdr = ["", L.TEAM, LEADERS_ON_TEAM] + L.HEADERS[3:] + [CONDUCTING]
    out = [["2nd Rounds — BOB Call / Stats"], [""], team_hdr]
    for i, team in enumerate(TEAMS):
        r = TEAM_HEADER_ROW + 1 + i
        match = "$B$%d:$B$%d,$B%d,%s,1" % (H, E, r, v)
        row = ["", team, "=COUNTIFS(%s)" % match]
        for h in L.HEADERS[3:]:
            a = L.col_letter(col[h])
            row.append(pct(h, r) if h in L.PCTS
                       else "=SUMIFS(%s$%d:%s$%d,%s)" % (a, H, a, E, match))
        row.append('=COUNTIFS(%s,%s,">0")' % (match, d))
        out.append(row)
    out.append([""])
    r = TOTALS_ROW
    tot = ["", "TOTALS (month picked)", "=COUNTIFS(%s,1)" % v]
    for h in L.HEADERS[3:]:
        a = L.col_letter(col[h])
        tot.append(pct(h, r) if h in L.PCTS else "=SUBTOTAL(109,%s%d:%s%d)" % (a, H, a, E))
    tot.append('=COUNTIFS(%s,1,%s,">0")' % (v, d))
    out += [tot, [""], list(L.HEADERS)]
    assert len(out) == HEADER_ROW
    return out


LEGEND = [["Metric Goals", "Job Offered", "BOB", "New starts showed"],
          ["Green", "75%+", "70% +", "65% +"],
          ["Yellow", "65% - 74.99%", "50% - 69.9%", "50% - 64.99%"],
          ["Red", "64.9% or below", "49.9% or below", "49.9% or below"]]


def build_tab(sh, logfn=print):
    from automations.shared import sheets_retry as RETRY
    ws = RETRY.call(sh.add_worksheet, title=L.TAB, rows=END_ROW, cols=20)
    q = L.TAB.replace("'", "''")
    RETRY.call(sh.values_batch_update, {"valueInputOption": "USER_ENTERED", "data": [
        {"range": "'%s'!A1" % q, "values": _top_values()},
        {"range": "'%s'!N%d" % (q, TEAM_HEADER_ROW), "values": LEGEND}]})
    RETRY.call(sh.batch_update, {"requests": _build_requests(ws.id)})
    logfn("  built %r" % L.TAB)
    return ws


def insert_rows(sh, ws, at_row: int, values: List[list], logfn=print) -> None:
    """INSERT rows at `at_row` (never overwrite) and fill them."""
    from automations.shared import sheets_retry as RETRY
    if not values:
        return
    RETRY.call(sh.batch_update, {"requests": [{"insertDimension": {
        "range": {"sheetId": ws.id, "dimension": "ROWS",
                  "startIndex": at_row - 1, "endIndex": at_row - 1 + len(values)},
        "inheritFromBefore": at_row - 1 > HEADER_ROW}}]})
    gap = [""] * (VISIBLE_COL - len(L.HEADERS) - 1)
    values = [list(v) + gap + ["=SUBTOTAL(103,A%d)" % (at_row + i)]
              for i, v in enumerate(values)]
    last = L.col_letter(VISIBLE_COL)
    RETRY.call(sh.values_batch_update, {"valueInputOption": "USER_ENTERED", "data": [{
        "range": "'%s'!A%d:%s%d" % (L.TAB.replace("'", "''"), at_row, last,
                                     at_row + len(values) - 1),
        "values": values}]})
    logfn("  inserted %d row(s) at row %d" % (len(values), at_row))


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

def plan(rows: List[L.Row], leaders: List[L.Person], month: str,
         first_data_row: int) -> tuple:
    """(row to insert at, [values], is_new_month). Pure, for the tests."""
    mine, after = L.month_block(rows, month)
    if not mine:
        prev = L.months_in(rows)
        last = [r for r in rows if prev and r.month == prev[0]]
        people = L.new_month_people(leaders, last)
        vals = [L.row_values(month, p, first_data_row + i) for i, p in enumerate(people)]
        return first_data_row, vals, True
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
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from automations.recruiting_report.fill import open_by_key
    from automations.shared.workbooks import ALL_IN_ONE_RAF
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    month = L.month_label(today)
    sh = open_by_key(ALL_IN_ONE_RAF)
    leaders = board_leaders(today)

    titles = [w.title for w in sh.worksheets()]
    if L.TAB not in titles:
        if a.dry_run:
            print("  (dry run) would build %r" % L.TAB)
            return 0
        build_tab(sh)
    ws = sh.worksheet(L.TAB)
    hrow, cols, rows = read_tab(ws)
    first = hrow + 1

    if a.seed_from_real:
        if rows:
            print("  tab already has rows -- --seed-from-real only runs on an empty tab")
            return 1
        seeded = real_tab_months(sh, today.year)
        vals = []
        for m, people in seeded.items():       # left-to-right = newest first
            for team, name, counts in sorted(people, key=lambda p: p[1].lower()):
                vals.append(L.row_values(m, L.Person(name, team), first + len(vals), counts))
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

"""Raf's '2nd Rds' tab inside his Daily Update sheet (Raf, Slack 2026-10-26):
"add my 2nd rd tab to my daily update spreadsheet, have a drop down for the
month and have it automatically pull the numbers from the daily update".

A Month dropdown -> one row per 2nd-round interviewer with the month's KPIs,
all FORMULAS over that month's tab ('October -2026', 'August-2026',
'Febuary-2026' -- the names drift, a hidden helper finds the real one), so it
updates by itself: built once, no daily job. Same KPIs + color cuts as the
All in One's '2nd rds %'s'. Counting rules = the month tab's own
"SECOND ROUNDS" block (cols O-T):
  2nd rds   = rows whose C (2nd Round Interviewer) is the leader
  Offered   = those with G (Status) not "*Leader said no*"
  Accepted  = G starts with "BOB"
  NS sched  = G starts with "BOB" and H (BOB Date) filled
  NS showed = K (SHOWED TO DAY 1) = "YES"
NS sched/showed come from the Daily Update here, NOT from the OBCL tabs the
All in One used -- that is what Raf asked for, so those two can differ.
Team Name = a Leader -> Team list on the right of the tab (S:T), seeded
from this week's sales board + the All in One's '2nd rds %'s'; Raf can type
a new leader's team there. Refuses to touch the tab if it already exists
(--rebuild re-makes it, test sheet only).

    python -m automations.raf_daily_update.second_rds --test-sheet          # dry
    python -m automations.raf_daily_update.second_rds --test-sheet --write
    python -m automations.raf_daily_update.second_rds --test-sheet --rebuild --write
    python -m automations.raf_daily_update.second_rds --write               # real sheet
"""
import argparse
import datetime as dt
import sys

from automations.raf_daily_update.run import REAL_SHEET, TEST_SHEET
from automations.recruiting_report.fill import open_by_key

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

TAB = "2nd Rds"
FIRST, LAST = 6, 80                 # leader rows
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MONTHS = ["December 2025"] + ["%s %d" % (m, y) for y in range(2026, 2031) for m in MONTH_NAMES]
HEAD = ["Team Name", "Leader Name", "2nd rds conducted", "Job offered", "Job Offered %",
        "BOB # / Accepted", "BOB %", "New Start Scheduled", "New starts showed",
        "NS Showed %"]
# % column index (0-based in HEAD) -> (green at/above, red below)
CUTS = {4: (0.75, 0.65), 6: (0.70, 0.50), 9: (0.65, 0.50)}
W = len(HEAD)                      # table = A:J
HELPER = "L2"                      # hidden: the month tab's real name
TEAMS_AT = 18                      # S:T = Leader -> Team list

NAVY = {"red": 0.161, "green": 0.235, "blue": 0.333}
HDR = {"red": 0.267, "green": 0.384, "blue": 0.537}
WHITE = {"red": 1, "green": 1, "blue": 1}
GREEN = {"red": 0.718, "green": 0.882, "blue": 0.804}
YELLOW = {"red": 0.988, "green": 0.910, "blue": 0.698}
RED = {"red": 0.957, "green": 0.780, "blue": 0.765}
LINE = {"red": 0.800, "green": 0.812, "blue": 0.835}

# L2 (hidden) = the month tab's real name for the B2 pick, "" if none.
# Tries the spellings the sheet uses: 'October -2026', 'August-2026',
# 'X - 2026', 'X 2026', and Raf's 'Febuary'.
_M = 'LEFT($B$2,LEN($B$2)-5)'
_Y = 'RIGHT($B$2,4)'


def _tab_finder():
    names = []
    for m in (_M, 'SUBSTITUTE(%s,"February","Febuary")' % _M):
        for sep in ('" -"', '"-"', '" - "', '" "'):
            names.append('%s&%s&%s' % (m, sep, _Y))
    f = '""'
    for n in reversed(names):
        f = 'IF(ISERROR(INDIRECT("\'"&%s&"\'!A1")),%s,%s)' % (n, f, n)
    return "=IF($B$2=\"\",\"\"," + f + ")"


def col(c):
    """The month tab's column `c` from row 2 down."""
    return 'INDIRECT("\'"&$L$2&"\'!%s2:%s")' % (c, c)


def row_formulas(r):
    base = '%s,$B%d' % (col("C"), r)
    blank = '=IF($B%d="","",' % r
    return [
        '=IF($B%d="","",IFERROR(VLOOKUP($B%d,$S$5:$T,2,FALSE),""))' % (r, r),
        blank + "COUNTIFS(%s))" % base,
        blank + 'COUNTIFS(%s,%s,"<>*Leader said no*"))' % (base, col("G")),
        blank + 'IF(C%d=0,"",D%d/C%d))' % (r, r, r),
        blank + 'COUNTIFS(%s,%s,"BOB*"))' % (base, col("G")),
        blank + 'IF(D%d=0,"",F%d/D%d))' % (r, r, r),
        blank + 'COUNTIFS(%s,%s,"BOB*",%s,"<>"))' % (base, col("G"), col("H")),
        blank + 'COUNTIFS(%s,%s,"YES"))' % (base, col("K")),
        blank + 'IF(H%d=0,"",I%d/H%d))' % (r, r, r),
    ]


def rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def fmt(sid, r0, r1, c0, c1, f):
    return {"repeatCell": {"range": rng(sid, r0, r1, c0, c1), "cell": {"userEnteredFormat": f},
                           "fields": ",".join("userEnteredFormat." + k for k in f)}}


def seed_teams():
    """{leader: team}: this week's sales board wins over the All in One's
    '2nd rds %'s' (every Team Name / Leader Name pair on it)."""
    from automations.local_office_1on1s.second_rounds import SHEET_ID, TAB as AIO_TAB
    from automations.raf_second_rounds.layout import TEAMS
    from automations.raf_second_rounds.run import board_leaders
    board = board_leaders(dt.date.today(), logfn=lambda *_: None)
    # older blocks share the header but hold counts / legends -- real teams only
    known = set(TEAMS) | {p.team.strip() for p in board if p.team.strip()}
    out = {}
    grid = open_by_key(SHEET_ID).worksheet(AIO_TAB).get_values("A1:DZ120")
    for hr, row in enumerate(grid):
        for c, v in enumerate(row[:-1]):
            if v.strip() == "Team Name" and row[c + 1].strip() == "Leader Name":
                for r in grid[hr + 1:]:
                    r = r + [""] * (c + 2)
                    who, team = r[c + 1].strip(), r[c].strip()
                    if team in known and any(ch.isalpha() for ch in who):
                        out.setdefault(who.lower(), (who, team))
    for p in board:
        if p.team.strip():
            out[p.name.strip().lower()] = (p.name.strip(), p.team.strip())
    return dict(out.values())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="build the tab")
    ap.add_argument("--test-sheet", action="store_true", help="'Daily Update 2026 - LUCY'")
    ap.add_argument("--rebuild", action="store_true", help="test sheet only: delete + re-make the tab")
    args = ap.parse_args(argv)
    if args.rebuild and not args.test_sheet:
        sys.exit("--rebuild is for the test sheet only")
    sh = open_by_key(TEST_SHEET if args.test_sheet else REAL_SHEET)
    have = [w for w in sh.worksheets() if w.title == TAB]
    if have and not args.rebuild:
        sys.exit("%r already exists -- not touching it" % TAB)
    tot = FIRST - 1
    today = dt.date.today()
    this_month = "%s %d" % (MONTH_NAMES[today.month - 1], today.year)
    teams = sorted(seed_teams().items(), key=lambda kv: kv[0].lower())
    last = "ABCDEFGHIJ"[W - 1]
    values = [
        {"range": "A1", "values": [["2nd Rounds — BOB Call / Stats"]]},
        {"range": "A2:C2", "values": [["Month ▸", this_month,
                                       '=IF($L$2="","No tab for this month yet","")']]},
        {"range": HELPER, "values": [[_tab_finder()]]},
        {"range": "A4:%s4" % last, "values": [HEAD]},
        {"range": "B%d" % tot, "values": [["TOTALS"]]},
        # the month's interviewers, A-Z (spills down from B6)
        {"range": "B%d" % FIRST, "values": [[
            '=IF($L$2="","",IFERROR(SORT(UNIQUE(FILTER(%s,%s<>""))),""))' % (col("C"), col("C"))]]},
    ]
    rows = [row_formulas(r) for r in range(FIRST, LAST + 1)]
    values.append({"range": "A%d:A%d" % (FIRST, LAST), "values": [[x[0]] for x in rows]})
    values.append({"range": "C%d:%s%d" % (FIRST, last, LAST), "values": [x[1:] for x in rows]})
    t = ["=SUM(C{f}:C{l})", "=SUM(D{f}:D{l})", '=IF(C{r}=0,"",D{r}/C{r})', "=SUM(F{f}:F{l})",
         '=IF(D{r}=0,"",F{r}/D{r})', "=SUM(H{f}:H{l})", "=SUM(I{f}:I{l})", '=IF(H{r}=0,"",I{r}/H{r})']
    values.append({"range": "C%d:%s%d" % (tot, last, tot),
                   "values": [[x.format(f=FIRST, l=LAST, r=tot) for x in t]]})
    # goals legend, right of the table
    values.append({"range": "N4:Q7", "values": [
        ["Metric Goals", "Job Offered", "BOB", "New starts showed"],
        ["Green", "75%+", "70%+", "65%+"],
        ["Yellow", "65% - 74.9%", "50% - 69.9%", "50% - 64.9%"],
        ["Red", "64.9% or below", "49.9% or below", "49.9% or below"]]})
    # Leader -> Team list; Raf adds a new leader at the bottom
    values.append({"range": "S3", "values": [["Teams — add a new leader + team at the bottom"]]})
    values.append({"range": "S4:T%d" % (4 + len(teams)),
                   "values": [["Leader Name", "Team Name"]] + [list(kv) for kv in teams]})

    if not args.write:
        print("DRY RUN -- would %s tab %r in %s" % ("re-make" if have else "add", TAB, sh.title))
        print("  teams: %d leaders, e.g. %s" % (len(teams), teams[:3]))
        print("  row %d:" % FIRST, rows[0][:3])
        return

    if have:
        sh.del_worksheet(have[0])
    ws = sh.add_worksheet(TAB, rows=max(LAST, 4 + len(teams)) + 40, cols=21)
    sid = ws.id
    ws.batch_update(values, value_input_option="USER_ENTERED")
    reqs = [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "index": 0,
                                                  "gridProperties": {"frozenRowCount": 5}},
                                   "fields": "index,gridProperties.frozenRowCount"}},
        {"mergeCells": {"range": rng(sid, 0, 1, 0, W), "mergeType": "MERGE_ALL"}},
        fmt(sid, 0, 1, 0, W, {"backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                              "textFormat": {"bold": True, "fontSize": 13, "foregroundColor": WHITE}}),
        fmt(sid, 1, 2, 0, 1, {"textFormat": {"bold": True}, "horizontalAlignment": "RIGHT"}),
        fmt(sid, 1, 2, 1, 2, {"backgroundColor": YELLOW, "textFormat": {"bold": True, "fontSize": 11},
                              "horizontalAlignment": "CENTER"}),
        fmt(sid, 1, 2, 2, 3, {"textFormat": {"italic": True, "foregroundColor": {"red": 0.6, "green": 0.1, "blue": 0.1}}}),
        {"setDataValidation": {"range": rng(sid, 1, 2, 1, 2), "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": m} for m in MONTHS]},
            "strict": True, "showCustomUi": True}}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                 "startIndex": 11, "endIndex": 12},
                                       "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        fmt(sid, 3, 4, 0, W, {"backgroundColor": HDR, "wrapStrategy": "WRAP", "horizontalAlignment": "CENTER",
                              "verticalAlignment": "MIDDLE",
                              "textFormat": {"bold": True, "foregroundColor": WHITE}}),
        fmt(sid, tot - 1, tot, 0, W, {"backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                                      "textFormat": {"bold": True, "foregroundColor": WHITE}}),
        fmt(sid, FIRST - 1, LAST, 2, W, {"horizontalAlignment": "CENTER"}),
        fmt(sid, 3, 4, 13, 17, {"backgroundColor": HDR, "horizontalAlignment": "CENTER",
                                "textFormat": {"bold": True, "foregroundColor": WHITE}}),
        fmt(sid, 4, 5, 13, 17, {"backgroundColor": GREEN, "horizontalAlignment": "CENTER"}),
        fmt(sid, 5, 6, 13, 17, {"backgroundColor": YELLOW, "horizontalAlignment": "CENTER"}),
        fmt(sid, 6, 7, 13, 17, {"backgroundColor": RED, "horizontalAlignment": "CENTER"}),
        fmt(sid, 2, 3, TEAMS_AT, TEAMS_AT + 1, {"textFormat": {"italic": True}}),
        fmt(sid, 3, 4, TEAMS_AT, TEAMS_AT + 2, {"backgroundColor": HDR,
                                                "textFormat": {"bold": True, "foregroundColor": WHITE}}),
        {"updateBorders": {"range": rng(sid, 3, LAST, 0, W), "top": {"style": "SOLID", "color": LINE},
                           "bottom": {"style": "SOLID", "color": LINE}, "left": {"style": "SOLID", "color": LINE},
                           "right": {"style": "SOLID", "color": LINE},
                           "innerHorizontal": {"style": "SOLID", "color": LINE},
                           "innerVertical": {"style": "SOLID", "color": LINE}}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                 "startIndex": 3, "endIndex": 4},
                                       "properties": {"pixelSize": 44}, "fields": "pixelSize"}},
    ]
    for c0, c1, px in ((0, 1, 130), (1, 2, 190), (13, 17, 120),
                       (TEAMS_AT, TEAMS_AT + 1, 190), (TEAMS_AT + 1, TEAMS_AT + 2, 130)):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                             "startIndex": c0, "endIndex": c1},
                                                   "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    for c, (g, rd) in CUTS.items():
        reqs.append(fmt(sid, tot - 1, LAST, c, c + 1, {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}))
        cell = "$%s%d" % ("ABCDEFGHIJ"[c], tot)
        for color, f in ((GREEN, '=AND(ISNUMBER(%s),%s>=%s)' % (cell, cell, g)),
                         (YELLOW, '=AND(ISNUMBER(%s),%s>=%s,%s<%s)' % (cell, cell, rd, cell, g)),
                         (RED, '=AND(ISNUMBER(%s),%s<%s)' % (cell, cell, rd))):
            reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [rng(sid, tot - 1, LAST, c, c + 1)],
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": f}]},
                                "format": {"backgroundColor": color}}}}})
    sh.batch_update({"requests": reqs})
    print("built %r in %s (gid %d), %d leader teams" % (TAB, sh.title, sid, len(teams)))


if __name__ == "__main__":
    main()

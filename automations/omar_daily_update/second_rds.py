"""Omar's '2nd Rds' tab (Raf, Loom 2026-10-26): "a drop-down of the month,
so it's pulling all of this data directly from the daily update. Same KPIs."

A Month dropdown -> one row per 2nd-round interviewer with the month's KPIs,
all FORMULAS over his 'Daily Update' tab (filled by run.py), so it updates by
itself -- built once, no daily job. Same KPIs + color cuts as Raf's
'2nd rds %'s'. Counting rules = the Daily Update tab's own formulas:
  2nd rds   = rows whose C (2nd Round Interviewer) is the leader, A in month
  Offered   = those with F (Follow Up Status) not "*Leader said no*"
  Accepted  = F starts with "BOB"
  NS sched  = F starts with "BOB" and G (BOB Date) filled
  NS showed = I (SHOWED TO DAY 1) = "YES"
Verified on the sandbox copy 2026-10-26 with test rows (Oct vs Sept).
Refuses to touch the tab if it already exists.

    python -m automations.omar_daily_update.second_rds --sandbox          # dry
    python -m automations.omar_daily_update.second_rds --sandbox --write
    python -m automations.omar_daily_update.second_rds --write            # real sheet
"""
import argparse
import datetime as dt
import sys

from automations.omar_daily_update.run import REAL_SHEET, SANDBOX_SHEET
from automations.recruiting_report.fill import open_by_key

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

TAB = "2nd Rds"
DU = "'Daily Update'"
FIRST, LAST = 6, 80                 # leader rows
MONTHS = ["%s %d" % (m, y) for y in range(2026, 2031) for m in (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December")]
HEAD = ["Leader Name", "2nd rds conducted", "Job offered", "Job Offered %",
        "BOB # / Accepted", "BOB %", "New Start Scheduled", "New starts showed",
        "NS Showed %"]
# % column index (0-based in HEAD) -> (green at/above, red below)
CUTS = {3: (0.75, 0.65), 5: (0.70, 0.50), 8: (0.65, 0.50)}

NAVY = {"red": 0.161, "green": 0.235, "blue": 0.333}
HDR = {"red": 0.267, "green": 0.384, "blue": 0.537}
WHITE = {"red": 1, "green": 1, "blue": 1}
GREEN = {"red": 0.718, "green": 0.882, "blue": 0.804}
YELLOW = {"red": 0.988, "green": 0.910, "blue": 0.698}
RED = {"red": 0.957, "green": 0.780, "blue": 0.765}
LINE = {"red": 0.800, "green": 0.812, "blue": 0.835}

# month window: H2 = first day, I2 = last day (hidden helpers; B2 = the picker)
IN_MONTH = '%s!$A$2:$A,">="&$H$2,%s!$A$2:$A,"<="&$I$2' % (DU, DU)


def row_formulas(r):
    who = '%s!$C$2:$C,$A%d' % (DU, r)
    base = "%s,%s" % (who, IN_MONTH)
    blank = '=IF($A%d="","",' % r
    return [
        blank + "COUNTIFS(%s))" % base,
        blank + 'COUNTIFS(%s,%s!$F$2:$F,"<>*Leader said no*"))' % (base, DU),
        blank + 'IF(B%d=0,"",C%d/B%d))' % (r, r, r),
        blank + 'COUNTIFS(%s,%s!$F$2:$F,"BOB*"))' % (base, DU),
        blank + 'IF(C%d=0,"",E%d/C%d))' % (r, r, r),
        blank + 'COUNTIFS(%s,%s!$F$2:$F,"BOB*",%s!$G$2:$G,"<>"))' % (base, DU, DU),
        blank + 'COUNTIFS(%s,%s!$I$2:$I,"YES"))' % (base, DU),
        blank + 'IF(G%d=0,"",H%d/G%d))' % (r, r, r),
    ]


def rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def fmt(sid, r0, r1, c0, c1, f):
    return {"repeatCell": {"range": rng(sid, r0, r1, c0, c1), "cell": {"userEnteredFormat": f},
                           "fields": ",".join("userEnteredFormat." + k for k in f)}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="build the tab")
    ap.add_argument("--sandbox", action="store_true", help="Eve's test copy")
    args = ap.parse_args(argv)
    write = args.write
    sh = open_by_key(SANDBOX_SHEET if args.sandbox else REAL_SHEET)
    if TAB in [w.title for w in sh.worksheets()]:
        sys.exit("%r already exists -- not touching it" % TAB)
    tot = FIRST - 1
    this_month = "%s %d" % (dt.date.today().strftime("%B"), dt.date.today().year)
    values = [
        {"range": "A1", "values": [["2nd Rounds — BOB Call / Stats"]]},
        {"range": "A2:I2", "values": [["Month ▸", this_month, "", "", "", "", "",
                                        '=DATE(VALUE(RIGHT(B2,4)),MATCH(LEFT(B2,LEN(B2)-5),{"January","February","March","April","May","June","July","August","September","October","November","December"},0),1)', "=EOMONTH(H2,0)"]]},
        {"range": "A4:I4", "values": [HEAD]},
        {"range": "A%d" % tot, "values": [["TOTALS"]]},
        # the month's interviewers, A-Z (spills down from A6)
        {"range": "A%d" % FIRST, "values": [[
            '=IFERROR(SORT(UNIQUE(FILTER(%s!$C$2:$C,%s!$C$2:$C<>"",'
            '%s!$A$2:$A>=$H$2,%s!$A$2:$A<=$I$2))),"")' % (DU, DU, DU, DU)]]},
    ]
    rows = [row_formulas(r) for r in range(FIRST, LAST + 1)]
    values.append({"range": "B%d:I%d" % (FIRST, LAST), "values": rows})
    t = ["=SUM(B{f}:B{l})", "=SUM(C{f}:C{l})", '=IF(B{r}=0,"",C{r}/B{r})', "=SUM(E{f}:E{l})",
         '=IF(C{r}=0,"",E{r}/C{r})', "=SUM(G{f}:G{l})", "=SUM(H{f}:H{l})", '=IF(G{r}=0,"",H{r}/G{r})']
    values.append({"range": "B%d:I%d" % (tot, tot),
                   "values": [[x.format(f=FIRST, l=LAST, r=tot) for x in t]]})
    # goals legend, right of the table
    values.append({"range": "K4:N7", "values": [
        ["Metric Goals", "Job Offered", "BOB", "New starts showed"],
        ["Green", "75%+", "70%+", "65%+"],
        ["Yellow", "65% - 74.9%", "50% - 69.9%", "50% - 64.9%"],
        ["Red", "64.9% or below", "49.9% or below", "49.9% or below"]]})

    if not write:
        print("DRY RUN -- would add tab %r to %s" % (TAB, sh.title))
        for v in values[:5]:
            print(" ", v["range"], v["values"][0][:3])
        print("  row %d:" % FIRST, rows[0][:2])
        return

    ws = sh.add_worksheet(TAB, rows=LAST + 5, cols=14)
    sid = ws.id
    ws.batch_update(values, value_input_option="USER_ENTERED")
    reqs = [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 5}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"mergeCells": {"range": rng(sid, 0, 1, 0, 9), "mergeType": "MERGE_ALL"}},
        fmt(sid, 0, 1, 0, 9, {"backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                              "textFormat": {"bold": True, "fontSize": 13, "foregroundColor": WHITE}}),
        fmt(sid, 1, 2, 0, 1, {"textFormat": {"bold": True}, "horizontalAlignment": "RIGHT"}),
        fmt(sid, 1, 2, 1, 2, {"backgroundColor": YELLOW, "textFormat": {"bold": True, "fontSize": 11},
                              "horizontalAlignment": "CENTER"}),
        {"setDataValidation": {"range": rng(sid, 1, 2, 1, 2), "rule": {
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": m} for m in MONTHS]},
            "strict": True, "showCustomUi": True}}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                 "startIndex": 7, "endIndex": 9},
                                       "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        fmt(sid, 1, 2, 7, 9, {"numberFormat": {"type": "DATE", "pattern": "m/d/yyyy"}}),
        fmt(sid, 3, 4, 0, 9, {"backgroundColor": HDR, "wrapStrategy": "WRAP", "horizontalAlignment": "CENTER",
                              "verticalAlignment": "MIDDLE",
                              "textFormat": {"bold": True, "foregroundColor": WHITE}}),
        fmt(sid, tot - 1, tot, 0, 9, {"backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                                      "textFormat": {"bold": True, "foregroundColor": WHITE}}),
        fmt(sid, FIRST - 1, LAST, 1, 9, {"horizontalAlignment": "CENTER"}),
        fmt(sid, 3, 4, 10, 14, {"backgroundColor": HDR, "horizontalAlignment": "CENTER",
                                "textFormat": {"bold": True, "foregroundColor": WHITE}}),
        fmt(sid, 4, 5, 10, 14, {"backgroundColor": GREEN, "horizontalAlignment": "CENTER"}),
        fmt(sid, 5, 6, 10, 14, {"backgroundColor": YELLOW, "horizontalAlignment": "CENTER"}),
        fmt(sid, 6, 7, 10, 14, {"backgroundColor": RED, "horizontalAlignment": "CENTER"}),
        {"updateBorders": {"range": rng(sid, 3, LAST, 0, 9), "top": {"style": "SOLID", "color": LINE},
                           "bottom": {"style": "SOLID", "color": LINE}, "left": {"style": "SOLID", "color": LINE},
                           "right": {"style": "SOLID", "color": LINE},
                           "innerHorizontal": {"style": "SOLID", "color": LINE},
                           "innerVertical": {"style": "SOLID", "color": LINE}}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                 "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 190}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                 "startIndex": 10, "endIndex": 14},
                                       "properties": {"pixelSize": 120}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                 "startIndex": 3, "endIndex": 4},
                                       "properties": {"pixelSize": 44}, "fields": "pixelSize"}},
    ]
    for c, (g, rd) in CUTS.items():
        reqs.append(fmt(sid, tot - 1, LAST, c, c + 1, {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}))
        col = "ABCDEFGHI"[c]
        cell = "$%s%d" % (col, tot)
        for color, f in ((GREEN, '=AND(ISNUMBER(%s),%s>=%s)' % (cell, cell, g)),
                         (YELLOW, '=AND(ISNUMBER(%s),%s>=%s,%s<%s)' % (cell, cell, rd, cell, g)),
                         (RED, '=AND(ISNUMBER(%s),%s<%s)' % (cell, cell, rd))):
            reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [rng(sid, tot - 1, LAST, c, c + 1)],
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": f}]},
                                "format": {"backgroundColor": color}}}}})
    sh.batch_update({"requests": reqs})
    print("built %r in %s (gid %d)" % (TAB, sh.title, sid))


if __name__ == "__main__":
    main()

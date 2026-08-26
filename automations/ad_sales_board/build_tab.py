"""ONE-TIME BUILD of the Ad Sales Board tabs on the Recruiting Dashboard.

    PYTHONPATH=. .venv/bin/python -m automations.ad_sales_board.build_tab
    PYTHONPATH=. .venv/bin/python -m automations.ad_sales_board.build_tab --force-view

Creates the hidden 'Ad Sales Data' tab (20,000 x 27; headers + W/X lists +
Y/Z rosters + AA active-list + AB1 picked-week helper) and dresses the visible
'Ad Sales Board' tab AS A SALES BOARD — Carlos's correction 2026-08-26: "it
needs to look like a sales board". The layout is lifted from the live AT&T B2B
Sales Board mirror in this same workbook:

  row 1  dark-grey control strip: VIEWING ▸ manager · GROUP ▸ Org/Captainship
  row 2  navy title banner: AD SALES BOARD
  row 3  blue WE strip: week picker in the cream cell + computed week label
  row 4  navy bordered header: # | AD | Pull | Names | Wed..Tue | Account |
         City | Names (week)
  row 5+ bordered grid, spilled by one FILTER at B5; day cells = how many
         names that ad got THAT DAY; TOTAL row grey, unmatched row amber.

`--force-view` wipes and redresses the visible tab (values, formats,
validations, CF) and refreshes the data tab's helper formulas — it NEVER
touches the data rows (A2:R). The scheduled job never rebuilds layout.
"""
from __future__ import annotations  # mini runs Python 3.9

import argparse
import json

from automations.funnel_board.roster import CAPTAINSHIP, ORG

from . import sheet

NAVY = {"red": 0.12156863, "green": 0.21960784, "blue": 0.39215687}
BLUE = {"red": 0.18039216, "green": 0.32941177, "blue": 0.5882353}
STRIP = {"red": 0.2627451, "green": 0.2627451, "blue": 0.2627451}
CREAM = {"red": 1, "green": 0.9490196, "blue": 0.8}
WHITE = {"red": 1, "green": 1, "blue": 1}
GREY = {"red": 0.8509804, "green": 0.8509804, "blue": 0.8509804}
AMBER = {"red": 1, "green": 0.95, "blue": 0.8}
CAPTION = {"red": 0.8, "green": 0.8, "blue": 0.8}
BORDER = {"red": 0.7176471, "green": 0.7176471, "blue": 0.7176471}

D = sheet.DATA_TAB
# Spill: AD, Pull, # Names, the 7 day counts, Account, City, week names list.
B5 = ("=IFNA(FILTER({'%(d)s'!$E$2:$E,'%(d)s'!$G$2:$G,'%(d)s'!$I$2:$I,"
      "'%(d)s'!$L$2:$R,'%(d)s'!$C$2:$C,'%(d)s'!$F$2:$F,'%(d)s'!$J$2:$J},"
      "('%(d)s'!$A$2:$A=$B$1)*('%(d)s'!$B$2:$B=$B$3)))" % {"d": D})
A5 = ('=ARRAYFORMULA(IF(($B$5:$B$600="")+($B$5:$B$600="TOTAL"),"",'
      'ROW($B$5:$B$600)-4))')
# Picked week's start date, resolved on the DATA tab (AB1) so every header
# formula reads one cell instead of re-running the MATCH seven times.
AB1 = ("=IFERROR(DATEVALUE(INDEX($K$2:$K,MATCH('%s'!$B$3,$B$2:$B,0))),\"\")"
       % sheet.VIEW_TAB)
WEEK_LABEL = ("=IF('%(d)s'!$AB$1=\"\",\"\",\" Week of \"&TEXT('%(d)s'!$AB$1,"
              "\"mmm d\")&\" – \"&TEXT('%(d)s'!$AB$1+6,\"mmm d\"))" % {"d": D})
DAY_FALLBACK = ["Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
                "Monday", "Tuesday"]


def day_header(i):
    return ("=IF('%(d)s'!$AB$1=\"\",\"%(f)s\",TEXT('%(d)s'!$AB$1+%(i)d,\"dddd\")"
            "&CHAR(10)&TEXT('%(d)s'!$AB$1+%(i)d,\"m/d\"))"
            % {"d": D, "f": DAY_FALLBACK[i], "i": i})


CAPTION_TEXT = ("names per ad per DAY · Pull = processed emails that week · "
                "names = sent to call list (org offices only; Saturdays missing "
                "upstream) · amber row = names matching no ad")


def _grid(sess):
    r = sess.get("%s/%s" % (sheet.API, sheet.SPREADSHEET_ID),
                 params={"fields": "sheets(properties(sheetId,title,index),"
                                   "conditionalFormats)"})
    r.raise_for_status()
    return {s["properties"]["title"]: dict(s["properties"],
                                           n_cf=len(s.get("conditionalFormats", [])))
            for s in r.json()["sheets"]}


def _batch(sess, requests):
    if not requests:
        return None
    r = sess.post("%s/%s:batchUpdate" % (sheet.API, sheet.SPREADSHEET_ID),
                  json={"requests": requests})
    if not r.ok:
        raise RuntimeError(r.text[:600])
    return r.json()


def _uf(sess, rng, values):
    """USER_ENTERED put — for formulas."""
    r = sess.put("%s/%s/values/%s" % (sheet.API, sheet.SPREADSHEET_ID, rng),
                 params={"valueInputOption": "USER_ENTERED"},
                 json={"majorDimension": "ROWS", "values": values})
    r.raise_for_status()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-view", action="store_true",
                    help="wipe and redress the visible tab (data rows untouched)")
    a = ap.parse_args(argv)

    sess = sheet.session(verbose=True)
    tabs = _grid(sess)

    # --- create missing tabs -------------------------------------------------
    reqs = []
    if sheet.DATA_TAB not in tabs:
        reqs.append({"addSheet": {"properties": {
            "title": sheet.DATA_TAB, "hidden": True,
            "gridProperties": {"rowCount": 20000, "columnCount": 27}}}})
    if sheet.VIEW_TAB not in tabs:
        after = tabs.get("Source Report - Indeed", {}).get("index")
        props = {"title": sheet.VIEW_TAB,
                 "gridProperties": {"rowCount": 1000, "columnCount": 16}}
        if after is not None:
            props["index"] = after + 1
        reqs.append({"addSheet": {"properties": props}})
    made = bool(reqs)
    if reqs:
        _batch(sess, reqs)
        tabs = _grid(sess)
    data_id = tabs[sheet.DATA_TAB]["sheetId"]
    view_id = tabs[sheet.VIEW_TAB]["sheetId"]
    print("tabs ready: data=%s view=%s (created: %s)" % (data_id, view_id, made))

    if not made and not a.force_view:
        print("both tabs already existed — pass --force-view to redress the "
              "visible tab; the data rows are never rewritten here")
        return 0

    # --- data tab: headers + helper columns (data rows untouched) ------------
    org = [n for n, _o, _w in ORG]
    cap = [n for n, _o, _w in CAPTAINSHIP]
    sheet.put_values(sess, sheet.data_range("A1"), [sheet.DATA_HEADERS])
    sheet.put_values(sess, sheet.data_range("W1"),
                     [["managers", "weeks", "org", "captainship",
                       "active manager list", "picked week start"]])
    n = max(len(org), len(cap))
    sheet.put_values(sess, sheet.data_range("Y2"),
                     [[org[i] if i < len(org) else "",
                       cap[i] if i < len(cap) else ""] for i in range(n)])
    _uf(sess, sheet.data_range("AA2"),
        [['=IF(\'%s\'!$D$1="Captainship",FILTER($Z$2:$Z$40,$Z$2:$Z$40<>""),'
          'FILTER($Y$2:$Y$40,$Y$2:$Y$40<>""))' % sheet.VIEW_TAB]])
    _uf(sess, sheet.data_range("AB1"), [[AB1]])

    # --- visible tab: wipe everything visual, keep nothing -------------------
    n_cf = tabs[sheet.VIEW_TAB].get("n_cf", 0)
    wipe = [{"updateCells": {"range": {"sheetId": view_id},
                             "fields": "userEnteredValue,userEnteredFormat,"
                                       "dataValidation"}}]
    wipe += [{"deleteConditionalFormatRule": {"sheetId": view_id, "index": 0}}
             for _ in range(n_cf)]
    try:
        _batch(sess, [{"clearBasicFilter": {"sheetId": view_id}}])
    except RuntimeError:
        pass                      # no filter set — fine
    _batch(sess, wipe)
    # Grid geometry FIRST — the header/value writes below land past column H,
    # which 400s while the freshly-created tab is still 8 columns wide.
    _batch(sess, [{"updateSheetProperties": {"properties": {
        "sheetId": view_id,
        "gridProperties": {"rowCount": 1000, "columnCount": 16,
                           "frozenRowCount": 4, "frozenColumnCount": 2}},
        "fields": "gridProperties(rowCount,columnCount,frozenRowCount,"
                  "frozenColumnCount)"}}])

    # --- values --------------------------------------------------------------
    from . import weeks as _wk
    prev_label = _wk.windows_back(2)[1][0]      # the completed week
    sheet.put_values(sess, sheet.view_range("A1"),
                     [["VIEWING ▶", "Carlos Hidalgo", "GROUP ▶", "Org",
                       CAPTION_TEXT]])
    sheet.put_values(sess, sheet.view_range("A2"), [["AD SALES BOARD"]])
    sheet.put_values(sess, sheet.view_range("A3"), [["WE", prev_label]])
    _uf(sess, sheet.view_range("C3"), [[WEEK_LABEL]])
    sheet.put_values(sess, sheet.view_range("A4"),
                     [["#", "AD", "Pull", "Names"]])
    _uf(sess, sheet.view_range("E4"), [[day_header(i) for i in range(7)]])
    sheet.put_values(sess, sheet.view_range("L4"),
                     [["Account", "City", "Names (week)"]])
    _uf(sess, sheet.view_range("A5"), [[A5]])
    _uf(sess, sheet.view_range("B5"), [[B5]])

    # --- dress ---------------------------------------------------------------
    def fmt(r1, c1, r2, c2, cell, fields):
        return {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": r1, "endRowIndex": r2,
                      "startColumnIndex": c1, "endColumnIndex": c2},
            "cell": cell, "fields": fields}}

    def width(c1, c2, px):
        return {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": c1, "endIndex": c2},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}}

    def dv(row, col, rule):
        return {"setDataValidation": {
            "range": {"sheetId": view_id, "startRowIndex": row, "endRowIndex": row + 1,
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "rule": rule}}

    arial = lambda **kw: dict({"fontFamily": "Arial"}, **kw)
    reqs = [
        # row 1 — dark control strip
        fmt(0, 0, 1, 16, {"userEnteredFormat": {
                "backgroundColor": STRIP, "horizontalAlignment": "CENTER",
                "textFormat": arial(bold=True, foregroundColor=WHITE)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"),
        fmt(0, 1, 1, 2, {"userEnteredFormat": {
                "backgroundColor": WHITE,
                "textFormat": arial(bold=True, foregroundColor=NAVY)}},
            "userEnteredFormat(backgroundColor,textFormat)"),
        fmt(0, 3, 1, 4, {"userEnteredFormat": {
                "backgroundColor": WHITE,
                "textFormat": arial(bold=True, foregroundColor=NAVY)}},
            "userEnteredFormat(backgroundColor,textFormat)"),
        fmt(0, 4, 1, 16, {"userEnteredFormat": {
                "backgroundColor": STRIP, "horizontalAlignment": "LEFT",
                "textFormat": arial(bold=False, fontSize=9,
                                    foregroundColor=CAPTION)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"),
        # row 2 — navy banner
        fmt(1, 0, 2, 16, {"userEnteredFormat": {
                "backgroundColor": NAVY, "horizontalAlignment": "LEFT",
                "textFormat": arial(bold=True, fontSize=14,
                                    foregroundColor=WHITE)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"),
        # row 3 — WE strip
        fmt(2, 0, 3, 16, {"userEnteredFormat": {
                "backgroundColor": BLUE, "horizontalAlignment": "LEFT",
                "textFormat": arial(bold=True, foregroundColor=WHITE)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"),
        fmt(2, 0, 3, 1, {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "userEnteredFormat.horizontalAlignment"),
        fmt(2, 1, 3, 2, {"userEnteredFormat": {
                "backgroundColor": CREAM, "horizontalAlignment": "CENTER",
                "textFormat": arial(bold=True, fontSize=11,
                                    foregroundColor={"red": 0, "green": 0, "blue": 0}),
                "numberFormat": {"type": "TEXT", "pattern": "@"}}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat,"
            "numberFormat)"),
        # row 4 — header
        fmt(3, 0, 4, 14, {"userEnteredFormat": {
                "backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                "textFormat": arial(bold=True, fontSize=10,
                                    foregroundColor=WHITE)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,"
            "verticalAlignment,wrapStrategy,textFormat)"),
        # grid body
        fmt(4, 0, 320, 1, {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "textFormat": arial(foregroundColor={"red": 0.45, "green": 0.45,
                                                     "blue": 0.45})}},
            "userEnteredFormat(horizontalAlignment,textFormat)"),
        fmt(4, 2, 320, 11, {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "numberFormat": {"type": "NUMBER", "pattern": "0"}}},
            "userEnteredFormat(horizontalAlignment,numberFormat)"),
        fmt(4, 1, 320, 2, {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
            "userEnteredFormat.wrapStrategy"),
        fmt(4, 11, 320, 13, {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
            "userEnteredFormat.wrapStrategy"),
        fmt(4, 13, 320, 14, {"userEnteredFormat": {
                "wrapStrategy": "WRAP",
                "textFormat": arial(fontSize=9)}},
            "userEnteredFormat(wrapStrategy,textFormat)"),
        # borders over the whole board grid
        {"updateBorders": {
            "range": {"sheetId": view_id, "startRowIndex": 3, "endRowIndex": 320,
                      "startColumnIndex": 0, "endColumnIndex": 14},
            "top": {"style": "SOLID", "color": BORDER},
            "bottom": {"style": "SOLID", "color": BORDER},
            "left": {"style": "SOLID", "color": BORDER},
            "right": {"style": "SOLID", "color": BORDER},
            "innerHorizontal": {"style": "SOLID", "color": BORDER},
            "innerVertical": {"style": "SOLID", "color": BORDER}}},
        # column widths
        width(0, 1, 34), width(1, 2, 300), width(2, 3, 62), width(3, 4, 62),
        width(4, 11, 86), width(11, 12, 150), width(12, 13, 120),
        width(13, 14, 480), width(14, 16, 40),
        # dropdowns: manager B1, group D1, week B3
        dv(0, 1, {"condition": {"type": "ONE_OF_RANGE", "values": [
                    {"userEnteredValue": "='%s'!$AA$2:$AA$40" % D}]},
                  "showCustomUi": True, "strict": False}),
        dv(0, 3, {"condition": {"type": "ONE_OF_LIST", "values": [
                    {"userEnteredValue": "Org"},
                    {"userEnteredValue": "Captainship"}]},
                  "showCustomUi": True, "strict": False}),
        dv(2, 1, {"condition": {"type": "ONE_OF_RANGE", "values": [
                    {"userEnteredValue": "='%s'!$X$2:$X$200" % D}]},
                  "showCustomUi": True, "strict": False}),
        # TOTAL row grey/bold; unmatched-names row amber
        {"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": 4, "endRowIndex": 320,
                        "startColumnIndex": 0, "endColumnIndex": 14}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": '=$B5="TOTAL"'}]},
                "format": {"backgroundColor": GREY,
                           "textFormat": {"bold": True}}}}}},
        {"addConditionalFormatRule": {"index": 1, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": 4, "endRowIndex": 320,
                        "startColumnIndex": 0, "endColumnIndex": 14}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": '=LEFT($B5,1)="—"'}]},
                "format": {"backgroundColor": AMBER}}}}},
    ]
    _batch(sess, reqs)
    print("visible tab dressed as a sales board; week cell seeded to %s" % prev_label)
    print(json.dumps({"data_sheet_id": data_id, "view_sheet_id": view_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

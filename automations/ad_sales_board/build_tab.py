"""ONE-TIME BUILD of the Ad Sales Board tabs on the Recruiting Dashboard.

    PYTHONPATH=. .venv/bin/python -m automations.ad_sales_board.build_tab

Creates (idempotently — an existing tab is left alone unless --force-view
rewrites the visible tab's formulas/formats in place):

  * 'Ad Sales Data'  — hidden, 20,000 x 16. Row 1 headers, W/X manager+week
    lists, Y/Z org+captainship rosters, AA the picker-driven active list.
  * 'Ad Sales Board' — visible, right after 'Source Report - Indeed'. Pickers
    C1 (Org/Captainship) C2 (Week) C3 (Manager), one FILTER spill at A6, the
    same look as the monthly tab (cream pickers, navy header, TOTAL rule).

The scheduled job never rebuilds any of this — it writes A2:K on the data tab,
the W/X lists, and C2 on Wednesdays. If this layout is ever redone, reproduce
the monthly tab's three picker-coercion layers (see indeed_source_report
README); the week labels here are not date-like, but the belt is free.
"""
from __future__ import annotations  # mini runs Python 3.9

import argparse
import json

from automations.funnel_board.roster import CAPTAINSHIP, ORG

from . import sheet, weeks

NAVY = {"red": 0.12156863, "green": 0.21960784, "blue": 0.39215687}
CREAM = {"red": 1, "green": 0.9490196, "blue": 0.8}
WHITE = {"red": 1, "green": 1, "blue": 1}
GREY = {"red": 0.8509804, "green": 0.8509804, "blue": 0.8509804}

VIEW_HEADERS = ["Account", "Ad Title", "City", "Pull", "Names"]
A6 = ("=IFNA(FILTER({'%(d)s'!$C$2:$C,'%(d)s'!$E$2:$F,'%(d)s'!$G$2:$G,"
      "'%(d)s'!$J$2:$J},('%(d)s'!$A$2:$A=$C$3)*('%(d)s'!$B$2:$B=$C$2)))"
      % {"d": sheet.DATA_TAB})
NOTE = ("Pick a Manager and a Week above · an ad-week runs Wednesday → Tuesday, "
        "so Wednesday morning shows the week that just finished · Pull = processed "
        "emails (applicants) from that ad · Names = who was sent to the call list "
        "(org offices only; captainship-only offices have no name feed; Saturday "
        "arrivals are missing upstream) · TOTAL is the last row")


def _grid(sess):
    r = sess.get("%s/%s" % (sheet.API, sheet.SPREADSHEET_ID),
                 params={"fields": "sheets(properties(sheetId,title,index))"})
    r.raise_for_status()
    return {s["properties"]["title"]: s["properties"] for s in r.json()["sheets"]}


def _batch(sess, requests):
    r = sess.post("%s/%s:batchUpdate" % (sheet.API, sheet.SPREADSHEET_ID),
                  json={"requests": requests})
    if not r.ok:
        raise RuntimeError(r.text[:600])
    return r.json()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-view", action="store_true",
                    help="rewrite the visible tab's values/formats even if it exists")
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
                 "gridProperties": {"rowCount": 1000, "columnCount": 8,
                                    "frozenRowCount": 5}}
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
              "visible tab; the data tab is never rewritten here")
        return 0

    # --- data tab: headers + helper columns ----------------------------------
    org = [n for n, _o, _w in ORG]
    cap = [n for n, _o, _w in CAPTAINSHIP]
    sheet.put_values(sess, sheet.data_range("A1"), [sheet.DATA_HEADERS])
    sheet.put_values(sess, sheet.data_range("W1"),
                     [["managers", "weeks", "org", "captainship", "active manager list"]])
    n = max(len(org), len(cap))
    sheet.put_values(sess, sheet.data_range("Y2"),
                     [[org[i] if i < len(org) else "",
                       cap[i] if i < len(cap) else ""] for i in range(n)])
    # AA mirrors the monthly tab: the C1 group picker chooses which roster
    # spills into the manager dropdown's range.
    r = sess.put("%s/%s/values/%s" % (sheet.API, sheet.SPREADSHEET_ID,
                                      sheet.data_range("AA2")),
                 params={"valueInputOption": "USER_ENTERED"},
                 json={"majorDimension": "ROWS", "values": [[
                     '=IF(\'%s\'!$C$1="Captainship",FILTER($Z$2:$Z$40,$Z$2:$Z$40<>""),'
                     'FILTER($Y$2:$Y$40,$Y$2:$Y$40<>""))' % sheet.VIEW_TAB]]})
    r.raise_for_status()

    # --- visible tab: values -------------------------------------------------
    prev_label = weeks.windows_back(2)[1][0]     # the completed week
    sheet.put_values(sess, sheet.view_range("A1"), [["Ad Sales Board"]])
    sheet.put_values(sess, sheet.view_range("A2"), [["Week:"], ["Manager:"]])
    sheet.put_values(sess, sheet.view_range("C1"), [["Org"], [prev_label],
                                                    ["Carlos Hidalgo"]])
    sheet.put_values(sess, sheet.view_range("A4"), [[NOTE]])
    sheet.put_values(sess, sheet.view_range("A5"), [VIEW_HEADERS])
    r = sess.put("%s/%s/values/%s" % (sheet.API, sheet.SPREADSHEET_ID,
                                      sheet.view_range("A6")),
                 params={"valueInputOption": "USER_ENTERED"},
                 json={"majorDimension": "ROWS", "values": [[A6]]})
    r.raise_for_status()

    # --- visible tab: dress it -----------------------------------------------
    def fmt(row1, col1, row2, col2, cell, fields):
        return {"repeatCell": {
            "range": {"sheetId": view_id, "startRowIndex": row1, "endRowIndex": row2,
                      "startColumnIndex": col1, "endColumnIndex": col2},
            "cell": cell, "fields": fields}}

    reqs = [
        fmt(0, 0, 1, 1, {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 16}}},
            "userEnteredFormat.textFormat"),
        fmt(1, 0, 3, 1, {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "userEnteredFormat.textFormat"),
        # picker cells: cream, bold, and PLAIN TEXT format (the monthly tab's
        # date-coercion belt; free even though these labels aren't date-like)
        fmt(0, 2, 3, 3, {"userEnteredFormat": {
                "backgroundColor": CREAM,
                "textFormat": {"bold": True, "fontSize": 12},
                "numberFormat": {"type": "TEXT", "pattern": "@"}}},
            "userEnteredFormat(backgroundColor,textFormat,numberFormat)"),
        fmt(3, 0, 4, 1, {"userEnteredFormat": {"textFormat": {
                "italic": True, "fontSize": 9,
                "foregroundColor": {"red": 0.4, "green": 0.4, "blue": 0.4}}}},
            "userEnteredFormat.textFormat"),
        fmt(4, 0, 5, 5, {"userEnteredFormat": {
                "backgroundColor": NAVY,
                "textFormat": {"bold": True, "foregroundColor": WHITE},
                "horizontalAlignment": "CENTER"}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"),
        fmt(5, 3, 600, 4, {"userEnteredFormat": {
                "numberFormat": {"type": "NUMBER", "pattern": "0"}}},
            "userEnteredFormat.numberFormat"),
        fmt(5, 4, 600, 5, {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
            "userEnteredFormat.wrapStrategy"),
        fmt(5, 0, 600, 3, {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
            "userEnteredFormat.wrapStrategy"),
        # column widths: Account 150 / Ad 300 / City 140 / Pull 70 / Names 820
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 150}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 300}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": 2, "endIndex": 3},
            "properties": {"pixelSize": 140}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": 3, "endIndex": 4},
            "properties": {"pixelSize": 70}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "COLUMNS",
                      "startIndex": 4, "endIndex": 5},
            "properties": {"pixelSize": 820}, "fields": "pixelSize"}},
        # dropdowns
        {"setDataValidation": {
            "range": {"sheetId": view_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 2, "endColumnIndex": 3},
            "rule": {"condition": {"type": "ONE_OF_LIST", "values": [
                        {"userEnteredValue": "Org"},
                        {"userEnteredValue": "Captainship"}]},
                     "showCustomUi": True, "strict": False}}},
        {"setDataValidation": {
            "range": {"sheetId": view_id, "startRowIndex": 1, "endRowIndex": 2,
                      "startColumnIndex": 2, "endColumnIndex": 3},
            "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [
                        {"userEnteredValue": "='%s'!$X$2:$X$200" % sheet.DATA_TAB}]},
                     "showCustomUi": True, "strict": False}}},
        {"setDataValidation": {
            "range": {"sheetId": view_id, "startRowIndex": 2, "endRowIndex": 3,
                      "startColumnIndex": 2, "endColumnIndex": 3},
            "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [
                        {"userEnteredValue": "='%s'!$AA$2:$AA$40" % sheet.DATA_TAB}]},
                     "showCustomUi": True, "strict": False}}},
        # TOTAL row: grey + bold wherever the block ends (same rule as monthly)
        {"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": 5, "endRowIndex": 600,
                        "startColumnIndex": 0, "endColumnIndex": 5}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": '=$A6="TOTAL"'}]},
                "format": {"backgroundColor": GREY, "textFormat": {"bold": True}}}}}},
        # unmatched-names row: soft amber so it reads as a flag, not an ad
        {"addConditionalFormatRule": {"index": 1, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": 5, "endRowIndex": 600,
                        "startColumnIndex": 0, "endColumnIndex": 5}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": '=$A6="—"'}]},
                "format": {"backgroundColor": {"red": 1, "green": 0.95,
                                               "blue": 0.8}}}}}},
        # header filter buttons, like the monthly tab
        {"setBasicFilter": {"filter": {"range": {
            "sheetId": view_id, "startRowIndex": 4, "endRowIndex": 600,
            "startColumnIndex": 0, "endColumnIndex": 5}}}},
    ]
    _batch(sess, reqs)
    print("visible tab dressed; picker seeded to %s / Carlos Hidalgo" % prev_label)
    print(json.dumps({"data_sheet_id": data_id, "view_sheet_id": view_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

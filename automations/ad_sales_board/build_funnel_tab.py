"""One-time layout for the 'Ad Funnel Board' tab (Carlos, 2026-09-25: weekly
trends "for all of the other metrics" — removal %, first/second rounds).

Same stacked-scroll design as the Ad Sales Board (same bands, tints, pickers),
but the day columns are replaced by the funnel columns the weekly Source
Report already carries:

  # | Account | City | AD | Pull | Removed | Rem% | FR Bkd | FR Shw | Show% |
  SR Bkd | SR Shw | To Call List

The percentages are computed IN THE VIEW from the raw counts on 'Ad Sales
Data' (AJ..AR, written by run.py since 2026-09-25), so a TOTAL row's Rem% is
removed-sum over pull-sum — never an average of ratios. A week whose metrics
were never pulled (history before the backfill) shows blank, not 0%.

Run on the laptop:  PYTHONPATH=. .venv/bin/python -m automations.ad_sales_board.build_funnel_tab
Safe to re-run with --force-view: wipes and redresses the view only; it never
touches data rows. It also widens the data grid for AJ..AR and writes those
headers, which is idempotent.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import json

from . import sheet
from .build_tab import (ACCOUNT_TINTS, AMBER, BLUE, BORDER, CAPTION, GREY,
                        HINT_TEXT, INK, NAVY, STRIP, WHITE, _batch, _grid, _uf)

D = sheet.DATA_TAB
V = sheet.FUNNEL_TAB

# Blank-not-zero carries through: a ratio is blank when its denominator is
# blank/zero OR the numerator column was never pulled for that week (history
# from before 2026-09-25 until the weekly backfill reaches it).
REMPCT = ("ARRAYFORMULA(IF(('%(d)s'!$AJ$2:$AJ=\"\")+(N('%(d)s'!$G$2:$G)=0),,"
          "'%(d)s'!$AJ$2:$AJ/'%(d)s'!$G$2:$G))" % {"d": D})
SHOWPCT = ("ARRAYFORMULA(IF(N('%(d)s'!$AK$2:$AK)=0,,"
           "'%(d)s'!$AL$2:$AL/'%(d)s'!$AK$2:$AK))" % {"d": D})
A5 = ("=IFNA(FILTER({'%(d)s'!$S$2:$S,'%(d)s'!$C$2:$C,'%(d)s'!$F$2:$F,"
      "'%(d)s'!$E$2:$E,'%(d)s'!$G$2:$G,'%(d)s'!$AJ$2:$AJ,%(rem)s,"
      "'%(d)s'!$AK$2:$AK,'%(d)s'!$AL$2:$AL,%(show)s,"
      "'%(d)s'!$AM$2:$AM,'%(d)s'!$AN$2:$AN,'%(d)s'!$H$2:$H},"
      "'%(d)s'!$A$2:$A=$B$1))" % {"d": D, "rem": REMPCT, "show": SHOWPCT})
N5 = ('=ARRAYFORMULA(IFERROR(MATCH($B$5:$B$600,'
      'UNIQUE(FILTER($B$5:$B$600,$B$5:$B$600<>"")),0),""))')

HEADER = ["#", "Account", "City", "AD", "Pull", "Removed", "Rem %",
          "FR Booked", "FR Showed", "Show %", "SR Booked", "SR Showed",
          "To Call List"]
CAPTION_TEXT = ("weekly funnel per ad, from the same Source Report pull · "
                "Rem% = removed of pull · Show% = FR showed of FR booked · "
                "blank = that week's funnel not pulled yet · last 2-3 weeks "
                "keep maturing as interviews happen")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-view", action="store_true",
                    help="wipe and redress the funnel tab (data rows untouched)")
    a = ap.parse_args(argv)

    sess = sheet.session(verbose=True)
    tabs = _grid(sess)

    # --- data tab: room + headers for AJ..AR (idempotent) --------------------
    data_id = tabs[sheet.DATA_TAB]["sheetId"]
    _batch(sess, [{"updateSheetProperties": {"properties": {
        "sheetId": data_id, "gridProperties": {"rowCount": 20000,
                                               "columnCount": 46}},
        "fields": "gridProperties(rowCount,columnCount)"}}])
    sheet.put_values(sess, sheet.data_range("AJ1"), [sheet.METRIC_HEADERS])
    # The funnel tab needs its own manager list keyed to ITS group picker —
    # AA follows the Sales board's D1. AB was retired; it takes the job.
    sheet.put_values(sess, sheet.data_range("AB1"), [["funnel manager list"]])
    _uf(sess, sheet.data_range("AB2"),
        [['=IF(\'%s\'!$D$1="Captainship",FILTER($Z$2:$Z$40,$Z$2:$Z$40<>""),'
          'FILTER($Y$2:$Y$40,$Y$2:$Y$40<>""))' % V]])

    # --- create the view tab next to the Ad Sales Board ----------------------
    made = False
    if V not in tabs:
        after = tabs.get(sheet.VIEW_TAB, {}).get("index")
        props = {"title": V, "gridProperties": {"rowCount": 2000,
                                                "columnCount": 16}}
        if after is not None:
            props["index"] = after + 1
        _batch(sess, [{"addSheet": {"properties": props}}])
        tabs = _grid(sess)
        made = True
    view_id = tabs[V]["sheetId"]
    print("tabs ready: data=%s funnel=%s (created: %s)" % (data_id, view_id, made))
    if not made and not a.force_view:
        print("funnel tab already existed — pass --force-view to redress it")
        return 0

    # --- wipe + geometry (same order as build_tab: geometry BEFORE writes) ---
    n_cf = tabs[V].get("n_cf", 0)
    wipe = [{"updateCells": {"range": {"sheetId": view_id},
                             "fields": "userEnteredValue,userEnteredFormat,"
                                       "dataValidation"}},
            {"unmergeCells": {"range": {"sheetId": view_id}}}]
    wipe += [{"deleteConditionalFormatRule": {"sheetId": view_id, "index": 0}}
             for _ in range(n_cf)]
    try:
        _batch(sess, [{"clearBasicFilter": {"sheetId": view_id}}])
    except RuntimeError:
        pass
    _batch(sess, wipe)
    _batch(sess, [{"updateSheetProperties": {"properties": {
        "sheetId": view_id,
        "gridProperties": {"rowCount": 2000, "columnCount": 14,
                           "frozenRowCount": 4, "frozenColumnCount": 0}},
        "fields": "gridProperties(rowCount,columnCount,frozenRowCount,"
                  "frozenColumnCount)"}}])

    # --- values --------------------------------------------------------------
    vr = lambda a1: "'%s'!%s" % (V, a1)
    sheet.put_values(sess, vr("A1"),
                     [["VIEWING ▶", "Carlos Hidalgo", "GROUP ▶", "Org",
                       CAPTION_TEXT]])
    sheet.put_values(sess, vr("A2"), [["AD FUNNEL BOARD"]])
    sheet.put_values(sess, vr("A3"), [[HINT_TEXT]])
    sheet.put_values(sess, vr("A4"), [HEADER])
    _uf(sess, vr("A5"), [[A5]])
    _uf(sess, vr("N5"), [[N5]])

    # --- dress (mirrors build_tab so the two boards read as siblings) --------
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
            "range": {"sheetId": view_id, "startRowIndex": row,
                      "endRowIndex": row + 1,
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "rule": rule}}

    arial = lambda **kw: dict({"fontFamily": "Arial"}, **kw)
    reqs = [
        fmt(0, 0, 1, 14, {"userEnteredFormat": {
                "backgroundColor": STRIP, "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": arial(bold=True, foregroundColor=WHITE)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,"
            "verticalAlignment,textFormat)"),
        fmt(0, 1, 1, 2, {"userEnteredFormat": {
                "backgroundColor": WHITE,
                "textFormat": arial(bold=True, foregroundColor=NAVY)}},
            "userEnteredFormat(backgroundColor,textFormat)"),
        fmt(0, 3, 1, 4, {"userEnteredFormat": {
                "backgroundColor": WHITE,
                "textFormat": arial(bold=True, foregroundColor=NAVY)}},
            "userEnteredFormat(backgroundColor,textFormat)"),
        fmt(0, 4, 1, 14, {"userEnteredFormat": {
                "backgroundColor": STRIP, "horizontalAlignment": "CENTER",
                "textFormat": arial(bold=False, fontSize=9,
                                    foregroundColor=CAPTION)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"),
        {"mergeCells": {"range": {"sheetId": view_id, "startRowIndex": 1,
                                  "endRowIndex": 2, "startColumnIndex": 0,
                                  "endColumnIndex": 14},
                        "mergeType": "MERGE_ALL"}},
        fmt(1, 0, 2, 14, {"userEnteredFormat": {
                "backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": arial(bold=True, fontSize=14,
                                    foregroundColor=WHITE)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,"
            "verticalAlignment,textFormat)"),
        fmt(2, 0, 3, 14, {"userEnteredFormat": {
                "backgroundColor": BLUE, "horizontalAlignment": "LEFT",
                "verticalAlignment": "MIDDLE",
                "textFormat": arial(bold=True, fontSize=10,
                                    foregroundColor=WHITE)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,"
            "verticalAlignment,textFormat)"),
        fmt(3, 0, 4, 13, {"userEnteredFormat": {
                "backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                "textFormat": arial(bold=True, fontSize=11,
                                    foregroundColor=WHITE)}},
            "userEnteredFormat(backgroundColor,horizontalAlignment,"
            "verticalAlignment,wrapStrategy,textFormat)"),
        fmt(4, 0, 1500, 13, {"userEnteredFormat": {
                "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                "wrapStrategy": "CLIP",
                "textFormat": arial(bold=True, fontSize=11,
                                    foregroundColor=INK)}},
            "userEnteredFormat(horizontalAlignment,verticalAlignment,"
            "wrapStrategy,textFormat)"),
        fmt(4, 0, 1500, 1, {"userEnteredFormat": {
                "textFormat": arial(bold=True, fontSize=11,
                                    foregroundColor={"red": 0.42, "green": 0.42,
                                                     "blue": 0.42})}},
            "userEnteredFormat.textFormat"),
        # counts plain integers; the two ratio columns as percentages
        fmt(4, 4, 1500, 6, {"userEnteredFormat": {
                "numberFormat": {"type": "NUMBER", "pattern": "0"}}},
            "userEnteredFormat.numberFormat"),
        fmt(4, 6, 1500, 7, {"userEnteredFormat": {
                "numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
            "userEnteredFormat.numberFormat"),
        fmt(4, 7, 1500, 9, {"userEnteredFormat": {
                "numberFormat": {"type": "NUMBER", "pattern": "0"}}},
            "userEnteredFormat.numberFormat"),
        fmt(4, 9, 1500, 10, {"userEnteredFormat": {
                "numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
            "userEnteredFormat.numberFormat"),
        fmt(4, 10, 1500, 13, {"userEnteredFormat": {
                "numberFormat": {"type": "NUMBER", "pattern": "0"}}},
            "userEnteredFormat.numberFormat"),
        {"updateBorders": {
            "range": {"sheetId": view_id, "startRowIndex": 3, "endRowIndex": 1500,
                      "startColumnIndex": 0, "endColumnIndex": 13},
            "top": {"style": "SOLID", "color": BORDER},
            "bottom": {"style": "SOLID", "color": BORDER},
            "left": {"style": "SOLID", "color": BORDER},
            "right": {"style": "SOLID", "color": BORDER},
            "innerHorizontal": {"style": "SOLID", "color": BORDER},
            "innerVertical": {"style": "SOLID", "color": BORDER}}},
        width(0, 1, 34), width(1, 2, 170), width(2, 3, 130), width(3, 4, 290),
        width(4, 13, 78), width(13, 14, 40),
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "ROWS",
                      "startIndex": 3, "endIndex": 4},
            "properties": {"pixelSize": 40}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "ROWS",
                      "startIndex": 4, "endIndex": 1500},
            "properties": {"pixelSize": 26}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": view_id, "dimension": "ROWS",
                      "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 34}, "fields": "pixelSize"}},
        # its own manager list (AB) so this tab's group picker works alone
        dv(0, 1, {"condition": {"type": "ONE_OF_RANGE", "values": [
                    {"userEnteredValue": "='%s'!$AB$2:$AB$40" % D}]},
                  "showCustomUi": True, "strict": False}),
        dv(0, 3, {"condition": {"type": "ONE_OF_LIST", "values": [
                    {"userEnteredValue": "Org"},
                    {"userEnteredValue": "Captainship"}]},
                  "showCustomUi": True, "strict": False}),
        {"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": 4, "endRowIndex": 1500,
                        "startColumnIndex": 0, "endColumnIndex": 13}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue":
                                          '=LEFT($D5,11)="WEEK ENDING"'}]},
                "format": {"backgroundColor": BLUE,
                           "textFormat": {"bold": True,
                                          "foregroundColor": WHITE}}}}}},
        {"addConditionalFormatRule": {"index": 1, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": 4, "endRowIndex": 1500,
                        "startColumnIndex": 0, "endColumnIndex": 13}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": '=$D5="TOTAL"'}]},
                "format": {"backgroundColor": GREY,
                           "textFormat": {"bold": True}}}}}},
        {"addConditionalFormatRule": {"index": 1, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": 4, "endRowIndex": 1500,
                        "startColumnIndex": 0, "endColumnIndex": 13}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": '=LEFT($D5,1)="—"'}]},
                "format": {"backgroundColor": AMBER}}}}},
    ]
    for i, (r_, g_, b_) in enumerate(ACCOUNT_TINTS, 1):
        reqs.append({"addConditionalFormatRule": {"index": 2 + i, "rule": {
            "ranges": [{"sheetId": view_id, "startRowIndex": 4,
                        "endRowIndex": 1500, "startColumnIndex": 1,
                        "endColumnIndex": 4}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA", "values": [
                    {"userEnteredValue": '=AND($N5=%d,$B5<>"")' % i}]},
                "format": {"backgroundColor": {"red": r_, "green": g_,
                                               "blue": b_}}}}}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": view_id, "dimension": "COLUMNS",
                  "startIndex": 13, "endIndex": 14},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
    _batch(sess, reqs)
    print("funnel tab dressed")
    print(json.dumps({"data_sheet_id": data_id, "funnel_sheet_id": view_id}))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

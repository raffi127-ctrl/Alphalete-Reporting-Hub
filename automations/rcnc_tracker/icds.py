"""'Our ICDs' tab of Carlos's Residential Rep Count Tracker.

Per-ICD weekly headcount for the two Hidalgo orgs (Carlos 2026-08-30: "show us
all of our ICDs ... on the left something that shows whose org they're a part
of ... their individual headcount by the week ending").

Source: the xlsx attachment's 'ICD Headcount (by Campaign)' tab (one row per
ICD owner with Unique Headcount + Org Leader), via
residential_rep_count.parse.parse_headcounts. Layout:

  row 3 header:  Org | ICD | WE ... (chronological, newest right, amber wash)
  rows 4+:       one row per ICD ever seen under either org; blank where the
                 ICD has no row that week. New ICDs append at the bottom —
                 the header filter lets Carlos re-sort any week high-to-low.

Weekly upkeep is upsert(); --backfill-icds on run.py rebuilds the whole tab
from every email of the year in one shot.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Tuple

from automations.rcnc_tracker import run as _run

TAB = "Our ICDs"
HDR_ROW = 3
FIRST_ROW = 4
ORG_FILTER = ("rafaelhidalgo", "carloshidalgo")   # norm_name keys, org leaders

INK = {"red": 0.043, "green": 0.071, "blue": 0.125}
WHITE = {"red": 1, "green": 1, "blue": 1}
TABCOLOR = {"red": 0.851, "green": 0.467, "blue": 0.024}


def parse_week(xlsx_path) -> Dict[str, Tuple[str, int]]:
    """{icd owner name: (org leader, unique headcount)} for the two orgs."""
    from automations.residential_rep_count.parse import parse_headcounts, norm_name
    out: Dict[str, Tuple[str, int]] = {}
    for rec in parse_headcounts(xlsx_path).values():
        org = (rec.get("org_leader") or "").strip()
        if norm_name(org) in ORG_FILTER:
            out[rec["name"]] = (org, rec["headcount"])
    return out


def _ensure_tab(sh):
    try:
        return sh.worksheet(TAB)
    except Exception:  # noqa: BLE001 - WorksheetNotFound
        ws = sh.add_worksheet(title=TAB, rows=80, cols=60, index=2)
        ws.update(values=[
            ["OUR ICDS — UNIQUE HEADCOUNT BY WEEK ENDING"],
            ["One row per ICD in Raf's and Carlos's orgs; sort any week with "
             "the header filter."],
            ["Org", "ICD"],
        ], range_name="A1", raw=False)
        sh.batch_update({"requests": [
            {"updateSheetProperties": {"properties": {
                "sheetId": ws.id, "tabColor": TABCOLOR,
                "gridProperties": {"rowCount": 80, "columnCount": 60,
                                   "frozenRowCount": HDR_ROW,
                                   "frozenColumnCount": 2}},
                "fields": "tabColor,gridProperties(rowCount,columnCount,"
                          "frozenRowCount,frozenColumnCount)"}},
            {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0,
                                      "endRowIndex": 1, "startColumnIndex": 0,
                                      "endColumnIndex": 8},
                "cell": {"userEnteredFormat": {"textFormat": {
                    "bold": True, "fontSize": 16, "foregroundColor": INK}}},
                "fields": "userEnteredFormat.textFormat"}},
            {"updateDimensionProperties": {"range": {
                "sheetId": ws.id, "dimension": "COLUMNS",
                "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {
                "sheetId": ws.id, "dimension": "COLUMNS",
                "startIndex": 1, "endIndex": 2},
                "properties": {"pixelSize": 180}, "fields": "pixelSize"}},
        ]})
        return ws


def _rows(ws) -> Dict[str, int]:
    """{icd name: 1-based row} from col B."""
    vals = ws.get(f"B{FIRST_ROW}:B300")
    return {r[0].strip(): FIRST_ROW + i
            for i, r in enumerate(vals) if r and r[0].strip()}


def _restyle(sh, ws, n_weeks: int, n_rows: int) -> None:
    """Deterministic full restyle: banding, filter, header, date formats,
    amber wash on the newest week. Cheap enough to re-issue every run."""
    last_col = 2 + n_weeks                       # 1-based
    last_row = FIRST_ROW + n_rows - 1
    g = lambda sr, er, sc, ec: {"sheetId": ws.id, "startRowIndex": sr,
                                "endRowIndex": er, "startColumnIndex": sc,
                                "endColumnIndex": ec}
    meta = sh.fetch_sheet_metadata(params={
        "fields": "sheets(properties.sheetId,bandedRanges.bandedRangeId)"})
    reqs = []
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == ws.id:
            for b in s.get("bandedRanges", []):
                reqs.append({"deleteBanding": {
                    "bandedRangeId": b["bandedRangeId"]}})
    reqs += [
        {"repeatCell": {"range": g(HDR_ROW - 1, HDR_ROW, 0, last_col),
            "cell": {"userEnteredFormat": {
                "backgroundColor": INK, "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 11,
                               "foregroundColor": WHITE}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                      "textFormat)"}},
        {"repeatCell": {"range": g(HDR_ROW - 1, HDR_ROW, 2, last_col),
            "cell": {"userEnteredFormat": {"numberFormat": {
                "type": "DATE", "pattern": "d-mmm"}}},
            "fields": "userEnteredFormat.numberFormat"}},
        {"repeatCell": {"range": g(FIRST_ROW - 1, last_row, 0, last_col),
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                "textFormat": {"fontSize": 11}}},
            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,"
                      "textFormat.fontSize)"}},
        # clear stale amber before re-applying to the newest column
        {"repeatCell": {"range": g(FIRST_ROW - 1, last_row, 2, last_col),
            "cell": {}, "fields": "userEnteredFormat.backgroundColor,"
                                  "userEnteredFormat.textFormat.bold"}},
        {"repeatCell": {"range": g(FIRST_ROW - 1, last_row, last_col - 1, last_col),
            "cell": {"userEnteredFormat": {"backgroundColor": _run.HILITE,
                     "textFormat": {"bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat.bold)"}},
        {"repeatCell": {"range": g(FIRST_ROW - 1, last_row, 2, last_col),
            "cell": {"userEnteredFormat": {"numberFormat": {
                "type": "NUMBER", "pattern": "#,##0"}}},
            "fields": "userEnteredFormat.numberFormat"}},
        {"addBanding": {"bandedRange": {"range": g(FIRST_ROW - 1, last_row, 0,
                                                   last_col),
            "rowProperties": {"firstBandColor": WHITE,
                              "secondBandColor": _run.BAND}}}},
        {"setBasicFilter": {"filter": {"range": g(HDR_ROW - 1, last_row, 0,
                                                  last_col)}}},
        {"updateDimensionProperties": {"range": {
            "sheetId": ws.id, "dimension": "COLUMNS",
            "startIndex": 2, "endIndex": last_col},
            "properties": {"pixelSize": 64}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {
            "sheetId": ws.id, "dimension": "ROWS",
            "startIndex": FIRST_ROW - 1, "endIndex": last_row},
            "properties": {"pixelSize": 24}, "fields": "pixelSize"}},
    ]
    sh.batch_update({"requests": reqs})


def rebuild(sh, weeks_data: Dict[dt.date, Dict[str, Tuple[str, int]]],
            dry: bool) -> None:
    """One-shot: wipe the tab's data area and write every week. Row order:
    org (Raf first), then newest-week headcount high-to-low."""
    weeks = sorted(weeks_data)
    newest = weeks_data[weeks[-1]]
    all_icds: Dict[str, str] = {}
    for wk in weeks:
        for nm, (org, _hc) in weeks_data[wk].items():
            all_icds[nm] = org                   # last seen org wins
    order = sorted(all_icds, key=lambda nm: (
        all_icds[nm] != "Rafael Hidalgo",
        -(newest.get(nm, ("", -1))[1])))
    print(f"  Our ICDs: {len(order)} ICDs x {len(weeks)} weeks")
    if dry:
        return
    ws = _ensure_tab(sh)
    grid: List[List] = [["Org", "ICD"] +
                        [f"{w.month}/{w.day}/{w.year}" for w in weeks]]
    for nm in order:
        row: List = [all_icds[nm], nm]
        for wk in weeks:
            rec = weeks_data[wk].get(nm)
            row.append("" if rec is None else rec[1])
        grid.append(row)
    ws.batch_clear([f"A{HDR_ROW}:ZZ300"])
    ws.update(values=grid, range_name=f"A{HDR_ROW}", raw=False)
    _restyle(sh, ws, len(weeks), len(order))


def upsert(sh, week: dt.date, icds: Dict[str, Tuple[str, int]],
           dry: bool) -> None:
    """Weekly: add/overwrite one week column; append never-seen ICDs."""
    if not icds:
        print("  Our ICDs: nothing parsed for the two orgs — skipped")
        return
    ws = _ensure_tab(sh)
    cols = _run._week_cols_from(ws.get(f"C{HDR_ROW}:ZZ{HDR_ROW}",
                                       value_render_option="UNFORMATTED_VALUE"),
                                base_col=3)
    if week in cols:
        col = cols[week]
    else:
        if cols and week < max(cols):
            raise RuntimeError(f"{TAB}: WE {week} older than newest column — "
                               f"use --backfill-icds instead")
        col = (max(cols.values()) + 1) if cols else 3
    rows = _rows(ws)
    print(f"  Our ICDs: col {_run._colletter(col)} "
          f"({'update' if week in cols else 'append'}), "
          f"{len([n for n in icds if n not in rows])} new ICDs")
    if dry:
        return
    new = [n for n in icds if n not in rows]
    if new:
        start = (max(rows.values()) + 1) if rows else FIRST_ROW
        ws.update(values=[[icds[n][0], n] for n in new],
                  range_name=f"A{start}:B{start + len(new) - 1}", raw=False)
        rows = _rows(ws)
    updates = [{"range": f"{_run._colletter(col)}{HDR_ROW}",
                "values": [[f"{week.month}/{week.day}/{week.year}"]]}]
    for nm, r in rows.items():
        rec = icds.get(nm)
        updates.append({"range": f"{_run._colletter(col)}{r}",
                        "values": [["" if rec is None else rec[1]]]})
    ws.batch_update(updates, value_input_option="USER_ENTERED")
    _restyle(sh, ws, col - 2, len(rows))

"""SCI RC/NC org-level headcount → the 'SCI RC/NC Headcount' tab.

Source: the xlsx attachment's 'Org Snapshot (by Campaign)' tab — one row per
Org Leader with that week's 'Unique Headcount' (the SAME number shown in the
email body's 'RC/NC Org Snapshot' table; NOT the 5-week cohort 'Headcount' on
the RC/NC Org Snapshot tabs). Megan 2026-06-27.

Layout (Megan/Raf): Org Leader rows × one column per week, ~1 year of history.
  A 'Org Leader' | B 'ICD Office' | C 'Group' | D.. 'WE m/d/yy' (oldest→newest)
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Tuple

import openpyxl
from gspread.utils import rowcol_to_a1

from automations.recruiting_report import fill as rfill
from automations.residential_rep_count.parse import norm_name
from automations.residential_rep_count.fill import (
    SPREADSHEET_ID, we_label, we_label_to_date)

ORG_TAB = "Org Snapshot (by Campaign)"        # tab inside the xlsx attachment
SCI_TAB = "SCI RC/NC Headcount"               # destination tab
SCI_SANDBOX_TAB = "SCI RC/NC Headcount SANDBOX"


def parse_org_snapshot(xlsx_path) -> Dict[str, dict]:
    """{norm_leader: {name, headcount, office, group}} from the
    'Org Snapshot (by Campaign)' tab (one row per Org Leader)."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    if ORG_TAB not in wb.sheetnames:
        raise ValueError(f"tab {ORG_TAB!r} not found. Tabs: {wb.sheetnames}")
    ws = wb[ORG_TAB]
    hrow = hdr = None
    for ri, row in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True), 1):
        low = [(str(c).lower() if c else "") for c in row]
        if any("org leader" in c for c in low) and any(
                "unique headcount" in c for c in low):
            hrow, hdr = ri, list(row)
            break
    if hdr is None:
        raise ValueError(f"{ORG_TAB!r}: no 'Org Leader' + 'Unique Headcount' header")
    ci = {(str(h).strip().lower() if h else ""): j for j, h in enumerate(hdr)}
    cl, chc = ci["org leader"], ci["unique headcount"]
    co, cg = ci.get("icd office"), ci.get("group")
    out: Dict[str, dict] = {}
    for row in ws.iter_rows(min_row=hrow + 1, values_only=True):
        nm = row[cl] if cl < len(row) else None
        if not nm or not str(nm).strip():
            continue
        try:
            hc = int(float(row[chc])) if (chc < len(row) and row[chc] not in (None, "")) else 0
        except (TypeError, ValueError):
            hc = 0
        out[norm_name(str(nm))] = {
            "name": str(nm).strip(),
            "headcount": hc,
            "office": (str(row[co]).strip() if co is not None and co < len(row) and row[co] else ""),
            "group": (str(row[cg]).strip() if cg is not None and cg < len(row) and row[cg] else ""),
        }
    return out


def build_rows(weeks: List[Tuple[dt.date, Dict[str, dict]]]) -> List[list]:
    """weeks = [(week_date, parsed)] OLDEST→NEWEST → the full A1 block to write.

    One row per Org Leader (union across all weeks; office/group taken from the
    newest week they appear), sorted by leader name. Each week column holds that
    leader's Unique Headcount (blank if absent that week)."""
    latest: Dict[str, dict] = {}
    for _d, parsed in weeks:            # oldest→newest, so newest wins
        latest.update(parsed)
    order = sorted(latest.values(), key=lambda r: norm_name(r["name"]))
    header = ["Org Leader", "ICD Office", "Group"] + [we_label(d) for d, _ in weeks]
    rows = [header]
    for rec in order:
        k = norm_name(rec["name"])
        line = [rec["name"], rec["office"], rec["group"]]
        for _d, parsed in weeks:
            r = parsed.get(k)
            line.append(r["headcount"] if r else "")
        rows.append(line)
    return rows


def open_tab(sandbox: bool = True):
    sh = rfill.open_by_key(SPREADSHEET_ID)
    title = SCI_SANDBOX_TAB if sandbox else SCI_TAB
    try:
        ws = sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows=200, cols=80)
    return ws, sh


def write_backfill(ws, weeks, dry_run: bool = True) -> dict:
    """Write the full Org-Leader × weekly grid into an (empty) SCI tab."""
    rows = build_rows(weeks)
    n_leaders, n_weeks = len(rows) - 1, len(weeks)
    if not dry_run:
        rfill._retry(ws.update, values=rows, range_name="A1",
                     value_input_option="USER_ENTERED")
        # tidy: bold header, freeze header row + the 3 label columns
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [
            {"repeatCell": {
                "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                               "horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat(textFormat,horizontalAlignment)"}},
            {"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "gridProperties": {
                    "frozenRowCount": 1, "frozenColumnCount": 3}},
                "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}}]})
    return {"leaders": n_leaders, "weeks": n_weeks,
            "first_week": weeks[0][0], "last_week": weeks[-1][0], "rows": rows}


def update_week(ws, week_date, parsed: Dict[str, dict],
                dry_run: bool = True) -> dict:
    """Append/refresh ONE week's column on the SCI tab (the weekly Friday upkeep).
    Adds the week column in chronological position (inheriting the prior week's
    format), writes each leader's Unique Headcount, appends any brand-new org
    leaders, and re-sorts leaders alphabetically if any were added."""
    grid = rfill._retry(ws.get_all_values)
    if not grid or not (grid[0] and (grid[0][0] or "").strip()):
        return write_backfill(ws, [(week_date, parsed)], dry_run=dry_run)

    header = grid[0]
    label = we_label(week_date)
    we_cols = {h: j for j, h in enumerate(header) if (h or "").startswith("WE ")}

    if label in we_cols:
        wk = we_cols[label]
    else:
        dated = sorted(((d, c) for l, c in we_cols.items()
                        if (d := we_label_to_date(l)) is not None),
                       key=lambda x: x[0])
        wk = next((c for d, c in dated if d > week_date), None)
        if wk is None:
            wk = (max(we_cols.values()) + 1) if we_cols else 3
        if not dry_run:
            reqs = [{"insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": wk, "endIndex": wk + 1},
                "inheritFromBefore": True}}]
            left = header[wk - 1] if wk - 1 < len(header) else ""
            if wk >= 1 and (left or "").startswith("WE "):
                reqs.append({"copyPaste": {
                    "source": {"sheetId": ws.id, "startRowIndex": 0,
                               "endRowIndex": len(grid), "startColumnIndex": wk - 1,
                               "endColumnIndex": wk},
                    "destination": {"sheetId": ws.id, "startRowIndex": 0,
                                    "endRowIndex": len(grid), "startColumnIndex": wk,
                                    "endColumnIndex": wk + 1},
                    "pasteType": "PASTE_FORMAT"}})
            rfill._retry(ws.spreadsheet.batch_update, {"requests": reqs})

    rowof = {norm_name(grid[r][0]): r for r in range(1, len(grid))
             if grid[r] and (grid[r][0] or "").strip()}
    updates = [{"range": rowcol_to_a1(1, wk + 1), "values": [[label]]}]
    appended = 0
    at = len(grid)                       # next free row (0-based)
    for k, rec in parsed.items():
        if k in rowof:
            updates.append({"range": rowcol_to_a1(rowof[k] + 1, wk + 1),
                            "values": [[rec["headcount"]]]})
        else:
            updates.append({"range": f"A{at + 1}:C{at + 1}",
                            "values": [[rec["name"], rec["office"], rec["group"]]]})
            updates.append({"range": rowcol_to_a1(at + 1, wk + 1),
                            "values": [[rec["headcount"]]]})
            at += 1
            appended += 1

    if dry_run:
        return {"label": label, "cells": len(updates), "appended": appended}
    rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
    if appended:                          # keep leaders alphabetical
        g2 = rfill._retry(ws.get_all_values)
        nc = max(len(r) for r in g2)
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [{"sortRange": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": len(g2),
                      "startColumnIndex": 0, "endColumnIndex": nc},
            "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "ASCENDING"}]}}]})
    return {"label": label, "cells": len(updates), "appended": appended}

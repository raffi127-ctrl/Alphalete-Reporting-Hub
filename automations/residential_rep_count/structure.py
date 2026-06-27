"""Structural edits to `Rep Count 24-26`, applied BEFORE the weekly fill.

Layout rules (Megan 2026-06-27):
  * Active section = ONE FLAT list, alphabetized by ICD first name (col A).
    No captainship sub-groupings. (Org Ongoing Data still totals by col B.)
  * Inactive ("No longer active") section = alphabetized + wrapped in a single
    COLLAPSED row group, tucked out of the way.

Three structural ops each week:
  * ADD   — an ICD in the email with data, whose Org Leader is one of our RC
            captains (Carlos / Colten / Rafael), with no row yet.
  * UP     — an inactive ICD that shows data this week → back into active.
  * DOWN   — an active ICD that logged 0 for 3 weeks running → into inactive.

Dedup: an inactive row that resolves (via ICD Aliases) to a person already
ACTIVE is NOT moved up or counted — e.g. 'Eveliz Roca' (maiden name) stays
inactive while 'Eveliz Wright' stays active.

Moves relocate the WHOLE row (history preserved), never delete. Ops apply one
at a time to a fixpoint (re-read between each) so index shifts can't corrupt;
then both sections are sorted and the inactive group collapsed.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from automations.recruiting_report import fill as rfill
from automations.residential_rep_count.parse import norm_name
from automations.residential_rep_count.fill import (
    ONGOING_ORDER, ZERO_STREAK_TO_INACTIVE, resolve_layout, we_label)

_OUR = {norm_name(l) for l in ONGOING_ORDER}


def _find_row_by_name(grid, name) -> Optional[int]:
    n = norm_name(name)
    for i, row in enumerate(grid):
        if row and norm_name(row[0]) == n:
            return i
    return None


def _active_keys(grid, layout, lookup) -> set:
    """Email-record keys already represented by an ACTIVE row (used to dedup
    maiden-name / alias duplicates sitting in the inactive section)."""
    a0, a1 = layout["active"]
    keys = set()
    for r in range(a0, a1 + 1):
        name = (grid[r][0] if grid[r] else "").strip()
        if not name:
            continue
        rec = lookup(name)
        if rec:
            keys.add(norm_name(rec["name"]))
    return keys


def plan_ops(grid, layout, lookup, email_data, we_date) -> List[dict]:
    ops: List[dict] = []
    a0, a1 = layout["active"]
    i0, i1 = layout["inactive"]
    target = we_label(we_date)
    prior = [c for lbl, c in sorted(layout["we_cols"].items(), key=lambda kv: kv[1])
             if lbl != target][-2:]
    existing = {norm_name(grid[r][0]) for r in range(len(grid))
                if grid[r] and (grid[r][0] or "").strip()}
    active_keys = _active_keys(grid, layout, lookup)

    # DOWN: active, 0 this week + 0/blank both prior columns.
    for r in range(a0, a1 + 1):
        name = (grid[r][0] if grid[r] else "").strip()
        if not name:
            continue
        rec = lookup(name)
        if (rec["headcount"] if rec else 0) == 0:
            prev = [str(grid[r][c]).strip() if c < len(grid[r]) else "" for c in prior]
            if len(prior) >= (ZERO_STREAK_TO_INACTIVE - 1) and all(
                    p in ("", "0") for p in prev):
                ops.append({"type": "down", "name": name})

    # UP: inactive with data — UNLESS the same person is already active.
    for r in range(i0, i1 + 1):
        name = (grid[r][0] if grid[r] else "").strip()
        if not name:
            continue
        rec = lookup(name)
        if rec and rec["headcount"] >= 1 and norm_name(rec["name"]) not in active_keys:
            ops.append({"type": "up", "name": name, "leader": rec["org_leader"]})

    # ADD: email ICD with data, our captain, not already on the sheet.
    for k, rec in email_data.items():
        if rec["headcount"] < 1 or norm_name(rec["org_leader"]) not in _OUR:
            continue
        if k in existing or k in active_keys:
            continue
        ops.append({"type": "add", "name": rec["name"], "leader": rec["org_leader"]})
    return ops


def _set_cells(ws, a1_range, values):
    rfill._retry(ws.update, values=values, range_name=a1_range,
                 value_input_option="USER_ENTERED")


def _apply_one(ws, sheet_id, grid, layout, op) -> str:
    a0, a1 = layout["active"]
    if op["type"] == "add":
        ins = a0                                   # top of active; sort reorders
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
            "insertDimension": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS",
                          "startIndex": ins, "endIndex": ins + 1},
                "inheritFromBefore": False}}]})
        _set_cells(ws, f"A{ins + 1}:B{ins + 1}", [[op["name"], op["leader"]]])
        return f"+ added {op['name']!r} ({op['leader']})"

    src = _find_row_by_name(grid, op["name"])
    if src is None:
        return f"  (skip {op['name']!r}: row vanished)"

    if op["type"] == "up":
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
            "moveDimension": {
                "source": {"sheetId": sheet_id, "dimension": "ROWS",
                           "startIndex": src, "endIndex": src + 1},
                "destinationIndex": a0}}]})
        g2 = rfill._retry(ws.get_all_values)
        r2 = _find_row_by_name(g2, op["name"])
        _set_cells(ws, f"B{r2 + 1}", [[op["leader"]]])
        return f"↑ moved {op['name']!r} up to active ({op['leader']})"

    # down: into the inactive section, clear Org Leader.
    dest = layout["nla"] + 1
    rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
        "moveDimension": {
            "source": {"sheetId": sheet_id, "dimension": "ROWS",
                       "startIndex": src, "endIndex": src + 1},
            "destinationIndex": dest}}]})
    g2 = rfill._retry(ws.get_all_values)
    r2 = _find_row_by_name(g2, op["name"])
    _set_cells(ws, f"B{r2 + 1}", [[""]])
    return f"↓ moved {op['name']!r} to 'No longer active'"


def _sort_and_group(ws, sheet_id):
    """Sort active + inactive by ICD first name (col A); wrap the inactive rows
    in a single collapsed row group.

    Order matters: a COLLAPSED group hides its rows, and Sheets' sortRange will
    not reorder hidden rows. So we (1) drop any existing group + unhide, then
    (2) sort, then (3) re-add the group collapsed."""
    grid = rfill._retry(ws.get_all_values)
    layout = resolve_layout(grid)
    ncols = max(len(r) for r in grid)
    a0, a1 = layout["active"]
    i0, i1 = layout["inactive"]
    grp = {"sheetId": sheet_id, "dimension": "ROWS",
           "startIndex": i0, "endIndex": i1 + 1}

    # 1) un-collapse: remove the existing group + unhide the rows.
    for req in ([{"deleteDimensionGroup": {"range": grp}}],
                [{"updateDimensionProperties": {
                    "range": grp, "properties": {"hiddenByUser": False},
                    "fields": "hiddenByUser"}}]):
        try:
            rfill._retry(ws.spreadsheet.batch_update, {"requests": req})
        except Exception:
            pass

    # 2) sort both sections by first name (col A).
    rfill._retry(ws.spreadsheet.batch_update, {"requests": [
        {"sortRange": {
            "range": {"sheetId": sheet_id, "startRowIndex": a0,
                      "endRowIndex": a1 + 1, "startColumnIndex": 0,
                      "endColumnIndex": ncols},
            "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "ASCENDING"}]}},
        {"sortRange": {
            "range": {"sheetId": sheet_id, "startRowIndex": i0,
                      "endRowIndex": i1 + 1, "startColumnIndex": 0,
                      "endColumnIndex": ncols},
            "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "ASCENDING"}]}}]})

    # 3) re-add the inactive group, collapsed.
    try:
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [
            {"addDimensionGroup": {"range": grp}},
            {"updateDimensionGroup": {
                "dimensionGroup": {"range": grp, "depth": 1, "collapsed": True},
                "fields": "collapsed"}}]})
    except Exception as e:
        print(f"  (inactive collapse skipped: {e})")


def apply_structure(ws, sheet_id, lookup, email_data, we_date,
                    dry_run: bool = True, max_ops: int = 60) -> List[str]:
    """Dry-run: return the planned ops (no writes). Live: apply ops to a
    fixpoint, then sort both sections + collapse inactive."""
    grid = rfill._retry(ws.get_all_values)
    layout = resolve_layout(grid)
    if dry_run:
        ops = plan_ops(grid, layout, lookup, email_data, we_date)
        return [f"[plan] {o['type'].upper()} {o['name']}"
                + (f" → {o.get('leader')}" if o.get("leader") else "")
                for o in ops] or ["(no structural changes)"]

    done: List[str] = []
    for _ in range(max_ops):
        grid = rfill._retry(ws.get_all_values)
        layout = resolve_layout(grid)
        ops = plan_ops(grid, layout, lookup, email_data, we_date)
        if not ops:
            break
        done.append(_apply_one(ws, sheet_id, grid, layout, ops[0]))
    _sort_and_group(ws, sheet_id)
    done.append("✓ sorted both sections by first name; inactive collapsed")
    return done

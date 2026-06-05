"""Extend the elapsed-day grand-total formulas on the 'X ORG - Current vs Prior
Weeks' tables.

The 'Sales (Last Week)' and 'Sales (4 Week AVG)' rows compare last week / the
4-week average to THIS week over the SAME elapsed days. Their Grand-Total cell
must therefore sum only the day columns that have elapsed this week (Mon ..
yesterday) — e.g. on a Thursday: =C+D+E (Mon+Tue+Wed). The VAs extend this by
hand each day; the automation did not, so Wednesday was dropped (Eve 2026-06-04,
formula stuck at =C+D). This rebuilds it every run from `today`.

Pure planner (`plan_elapsed_totals`) + a thin writer so it can be previewed.
"""
from __future__ import annotations

import datetime as dt
from typing import List

import gspread.utils as _gu

_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"}
# Row labels (col A or B, lowercased) whose Grand Total is an elapsed-day sum.
# ONLY the 'Sales (...)' comparison rows — NOT the bare 'Last Week' / 'Prior
# Week' static history rows (those are the VAs' weekly shift-down, kept static).
_ELAPSED_ROWS = ("sales (last week)", "sales ( 4 week avg)", "sales (4 week avg)")


def _a1(col: int) -> str:
    return _gu.rowcol_to_a1(1, col).rstrip("0123456789")


def elapsed_day_count(today: dt.date) -> int:
    """How many days of THIS week have completed (Mon..yesterday). Mon=0 →
    0 completed, Thu=3 → Mon/Tue/Wed = 3. Today itself is in-progress."""
    return today.weekday()


def plan_elapsed_totals(grid: List[List[str]], today: dt.date) -> List[dict]:
    """Return [{range, formula}] for every 'Current vs Prior' table's elapsed
    grand-total rows, sized to the days completed so far this week."""
    n = elapsed_day_count(today)
    updates: List[dict] = []
    for i, row in enumerate(grid):
        if not any("ORG - Current vs Prior" in (c or "") for c in row[:6]):
            continue
        hdr = i + 1
        # day-header row = first row within 4 with >=4 weekday names
        dayrow = next((r for r in range(hdr, min(hdr + 4, len(grid) + 1))
                       if sum(1 for c in grid[r - 1]
                              if (c or "").strip().lower() in _WEEKDAYS) >= 4),
                      None)
        if dayrow is None:
            continue
        daycols = [c + 1 for c, v in enumerate(grid[dayrow - 1])
                   if (v or "").strip().lower() in _WEEKDAYS]
        gt = max(daycols) + 1                       # Grand-Total col
        elapsed = sorted(daycols)[:n]               # Mon..yesterday columns
        for r in range(hdr, min(hdr + 12, len(grid) + 1)):
            lab = ((grid[r - 1][0] or "") + (grid[r - 1][1] or "")).strip().lower()
            if lab in _ELAPSED_ROWS:
                formula = ("=" + "+".join(f"{_a1(c)}{r}" for c in elapsed)
                           if elapsed else 0)
                updates.append({"range": f"{_a1(gt)}{r}", "values": [[formula]]})
    return updates


def plan_delta_lastweek(grid: List[List[str]], today: dt.date) -> List[dict]:
    """Return [{range, formula}] for every per-captainship DELTA table's
    'Last week' TOTAL cell (col D under 'Total for week'). It must sum the
    per-day 'Last week' sub-columns (G, J, M, ...) for the days completed so
    far — currently it drops the latest day (=G+J on a Wednesday). 'Total this
    week' (col C) already sums every day (future = 0) so it needs no fix."""
    n = elapsed_day_count(today)
    updates: List[dict] = []
    for i, row in enumerate(grid):
        if not any("Total for week" in (c or "") for c in row[:6]):
            continue
        sub = i + 1                                  # sub-header row (0-based i = header; +1 = next)
        if sub >= len(grid):
            continue
        lw_cols = [c + 1 for c, v in enumerate(grid[sub])
                   if (v or "").strip().lower() == "last week"]
        if len(lw_cols) < 2:
            continue
        total_col, per_day = lw_cols[0], lw_cols[1:]   # D = total; G/J/M.. = per-day
        elapsed = per_day[:n]
        if not elapsed:
            continue
        r = sub + 2                                   # first data row (1-based)
        while r <= len(grid):
            rv = grid[r - 1]
            b = (rv[1] if len(rv) > 1 else "").strip()
            if not b or any("Total for week" in (c or "") for c in rv[:6]):
                break
            formula = "=" + "+".join(f"{_a1(c)}{r}" for c in elapsed)
            updates.append({"range": f"{_a1(total_col)}{r}", "values": [[formula]]})
            r += 1
    return updates


def apply_elapsed_totals(ws, today: dt.date | None = None,
                         dry_run: bool = False, logfn=print) -> List[dict]:
    """Find + set the elapsed-day grand-total formulas on `ws`: the 'Current vs
    Prior' tables (Sales Last Week / 4 Week AVG) AND the per-captainship delta
    tables ('Last week' total). COPY/REAL tab chosen by the caller."""
    today = today or dt.date.today()
    grid = ws.get_all_values()
    updates = plan_elapsed_totals(grid, today) + plan_delta_lastweek(grid, today)
    n = elapsed_day_count(today)
    logfn(f"  elapsed-day totals ({n} day(s) completed): {len(updates)} cell(s)")
    for u in updates:
        logfn(f"    {u['range']} = {u['values'][0][0]}")
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logfn(f"  [OK] wrote {len(updates)} formula(s)")
    return updates

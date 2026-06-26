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
    """How many days of the active reporting week have completed. Uses the
    board's reporting-week model (rolls Tuesday), so on MONDAY all 7 of last
    week count (the week is finished); Tue=1 … Sun=6. Today is in-progress."""
    from automations.org_sales_board import week as _wk
    return len(_wk.completed_days(today))


def plan_elapsed_totals(grid: List[List[str]], today: dt.date) -> List[dict]:
    """Return [{range, formula}] for every 'Current vs Prior' table's elapsed
    grand-total rows, sized to the days completed so far this week.

    Matches ANY 'Current vs Prior' header — the ORG summaries ('X ORG -
    Current vs Prior Weeks' + 'RAF ORG (w/out Carlos & Colten) - …', where the
    'ORG -' isn't contiguous) AND every captainship box's bare 'Current vs
    Prior Weeks'. Broadening is safe because `_ELAPSED_ROWS` is what actually
    selects cells — only the 'Sales (Last Week)' / 'Sales (4 Week AVG)' rows
    get a formula; the static 'Last Week' / 'Prior Week' history rows never do
    (Eve 2026-06-26: closes the captainship + w/out-Carlos&Colten gap that the
    VAs were fixing by hand)."""
    n = elapsed_day_count(today)
    updates: List[dict] = []
    for i, row in enumerate(grid):
        if not any("Current vs Prior" in (c or "") for c in row[:6]):
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
    week' (col C) already sums every day (future = 0) so it needs no fix.

    Covers BOTH the rep rows AND the table's TOTALS row. The totals row is
    labelled inconsistently: Raf/Wayne carry "Captainship" in col B (a normal
    non-blank row, grown in the loop), but Starr/Chan/Tony/Sahil/Khalil/Luis
    leave col B BLANK on the totals row (their "<name>'s Captainship" label
    sits a few rows below). A blank col-B row would normally end the table, so
    we special-case it: if a blank-B row still carries a 'Total this week'
    value, it's that totals row — grow its 'Last week' total, then stop (Eve
    2026-06-26: their totals 'Last week' wasn't growing with the new day)."""
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
        # 'Total this week' column (C) — marks the totals row when col B is blank.
        tw_col = next((c + 1 for c, v in enumerate(grid[sub])
                       if (v or "").strip().lower() == "total this week"), None)

        def _grow(r):
            return {"range": f"{_a1(total_col)}{r}",
                    "values": [["=" + "+".join(f"{_a1(c)}{r}" for c in elapsed)]]}

        r = sub + 2                                   # first data row (1-based)
        while r <= len(grid):
            rv = grid[r - 1]
            b = (rv[1] if len(rv) > 1 else "").strip()
            if any("Total for week" in (c or "") for c in rv[:6]):
                break                                 # next table's header
            if not b:
                # A blank col-B row ends the table UNLESS it's the label-less
                # totals row (still has a 'Total this week' value) — grow it,
                # then stop. Raf/Wayne's totals carry a col-B label so they
                # never reach here; their trailing blank row has no tw value.
                tw = (rv[tw_col - 1].strip()
                      if tw_col and len(rv) >= tw_col else "")
                if tw:
                    updates.append(_grow(r))
                break
            updates.append(_grow(r))
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

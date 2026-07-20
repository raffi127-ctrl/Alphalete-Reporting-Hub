"""Plan the Country Sales Board's cell writes.

The whole report is seven columns wide. The tab's day block (col-A label
'Fiber - All Units', weekday headers, day-number row beneath, ICD rows down to
a 'Totals' row) is the ONLY place raw numbers land; every other figure on the
tab derives from it by formula:

    leaderboard col C   =SUMIF($B$98:$B$172, B18, …)
    Totals row          =SUM(C98:C172)
    Product Summary     =C173 … =I173
    Current vs Prior    =C5 … and the WE history stack
    'Total for week'    =SUMIF($B$98:$B$172, "<name>", …)

So we write the day cells and let the sheet recompute the rest — nothing else
is touched.

Row/column discipline: the block is located with org_sales_board.fill_section's
`find_daily_section`, which matches the col-A label AND the presence of a
'RUNNING WEEK TOTALS' header, then reads the day columns off the day-number row.
Verified against the live tab 2026-07-20: header 96, day-numbers 97, totals 173,
running-total col 10, day columns C..I -> days 20..26, 75 ICD rows. No index is
hardcoded here. [[feedback_no_hardcoded_columns]]

WHY THIS DOESN'T JUST CALL plan_section_fill: that planner resolves the week
through org_sales_board.week.reporting_week (the ORG board's Tuesday-rolling
week, wrong here) and rewrites the running-total column as =SUM(C:I). This tab
keeps its own enumerated =SUM(C98,D98,E98,G98,F98,…) there, so we leave column J
alone entirely rather than restyle a formula the VAs maintain.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.org_sales_board.fill_section import (
    FillPlan, _candidates_for, _col, find_daily_section)
from automations.focus_office_att.aliases import load_aliases

from automations.country_sales_board import week as wk

BLOCK_LABEL = "Fiber - All Units"


def audit_aggregate_coverage(formula_grid: List[List[str]],
                             grid: List[List[str]],
                             block_label: str = BLOCK_LABEL) -> List[str]:
    """Warn when the day block has rows the tab's own aggregates don't cover.

    Every headline figure on this tab reads the day block through a FIXED range
    (`=SUMIF($B$98:$B$172,…)`, `=SUM(C98:C172)`). Google Sheets grows such a
    range when a row is inserted INSIDE it, but NOT when one is appended at the
    end. Verified on the sandbox 2026-07-20:

        insert at row 150 (middle) -> $B$98:$B$173   ✓ extends
        insert at row 173 (bottom) -> $B$98:$B$172   ✗ does not

    So a rep added on the last line — the natural place for a VA to add one —
    gets their day cells filled by this report and then counts toward NOTHING:
    not the leaderboard, not the Totals row, not the Product Summary. The
    numbers look right on the row and the board silently under-reports.

    We can't fix the sheet's formulas from here without rewriting cells the VAs
    own, so we detect it and say so loudly. Returns a list of warning lines.
    """
    import re

    anchor = find_daily_section(grid, block_label)
    first, last = min(anchor.icd_rows.values()), max(anchor.icd_rows.values())
    warn: List[str] = []
    # The leaderboard's SUMIF is the canonical consumer; the Totals row =SUM is
    # the other. Read whichever formulas mention the block's own columns.
    pat = re.compile(r"\$?B\$?(\d+):\$?B\$?(\d+)|\bC(\d+):C(\d+)")
    seen = set()
    for r, row in enumerate(formula_grid, 1):
        for cell in row[:12]:
            if not isinstance(cell, str) or not cell.startswith("="):
                continue
            if "SUMIF" not in cell.upper() and "SUM(" not in cell.upper():
                continue
            for m in pat.finditer(cell):
                lo, hi = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                lo, hi = int(lo), int(hi)
                # only ranges that clearly address the day block
                if abs(lo - first) > 3 or hi > anchor.totals_row:
                    continue
                if (lo, hi) in seen:
                    continue
                seen.add((lo, hi))
                if hi < last:
                    missed = [n for n, rr in anchor.icd_rows.items() if rr > hi]
                    warn.append(
                        f"  ❌ the day block runs to row {last} but an aggregate "
                        f"range stops at {hi} (row {r}: {cell[:44]!r}) — "
                        f"{len(missed)} rep(s) are filled but "
                        f"counted NOWHERE: {missed}. Fix: delete those rows and "
                        f"re-insert them ABOVE the last rep so the ranges grow.")
    return warn


def plan_day_fill(
    grid: List[List[str]],
    pull: Dict[str, Dict[str, Dict[dt.date, int]]],
    *,
    metric: str = "Total",
    raw_aliases: Optional[dict] = None,
    today: Optional[dt.date] = None,
    block_label: str = BLOCK_LABEL,
) -> FillPlan:
    """Build the batch of day-cell writes. Pure — no Sheet or network I/O, so
    the caller can preview it before anything is written."""
    raw_aliases = raw_aliases if raw_aliases is not None else load_aliases()
    today = today or dt.date.today()
    anchor = find_daily_section(grid, block_label)
    plan = FillPlan(section=block_label)

    # The week the BOARD is showing, read back out of its own day-number row.
    board_dates = wk.sheet_week(anchor.day_col_by_daynum, today)
    plan.log.append(
        f"  board week = {board_dates[0].isoformat()}..{board_dates[-1].isoformat()} "
        f"({wk.we_label(board_dates[-1])})")

    # Which days does the pull carry, and which of those land on this board week?
    present: set[dt.date] = set()
    for metrics in pull.values():
        present.update(metrics.get(metric, {}).keys())
    on_board = {d: anchor.day_col_by_daynum[d.day]
                for d in present if d in board_dates}
    off_board = sorted(d for d in present if d not in board_dates)
    if off_board:
        plan.log.append(
            f"  ⚠ pull covers {off_board[0].isoformat()}..{off_board[-1].isoformat()}, "
            f"which is NOT the week this board is showing — {len(off_board)} "
            f"day(s) skipped (nothing written for them)")
    if not on_board:
        plan.log.append(
            "  no overlap between the pull's week and the board's week — "
            "nothing to fill (this is the normal state early in a new week, "
            "before any sales land)")
        return plan

    # Only COMPLETED days carry data. Today is still in progress and future days
    # haven't happened, so both are blanked — otherwise a prior run's numbers
    # linger in a cell whose day hasn't finished.
    future_cols = [anchor.day_col_by_daynum[d.day] for d in board_dates
                   if d >= today and d.day in anchor.day_col_by_daynum]
    fill_cols = {d: c for d, c in on_board.items() if d < today}

    for name, row in anchor.icd_rows.items():
        cands = _candidates_for(name, raw_aliases)
        owner_key = next((k for k in pull if k in cands), None)
        if owner_key is None:
            plan.unmatched.append(name)
        per_day = pull.get(owner_key, {}).get(metric, {}) if owner_key else {}
        for day, col in sorted(fill_cols.items(), key=lambda kv: kv[1]):
            # SHEET-DRIVEN: a listed ICD absent from the pull sold 0 that day,
            # which is a real 0 the VAs key — not a blank.
            val = int(per_day.get(day, 0))
            plan.updates.append({"range": f"{_col(col)}{row}", "values": [[val]]})
            plan.day_totals[day.day] = plan.day_totals.get(day.day, 0) + val
        for col in future_cols:
            plan.updates.append({"range": f"{_col(col)}{row}", "values": [[""]]})

    plan.log.append(
        f"  {block_label}: {len(anchor.icd_rows)} ICDs x {len(fill_cols)} "
        f"completed day(s); day totals (by day-of-month) = "
        f"{dict(sorted(plan.day_totals.items()))}")
    if future_cols:
        plan.log.append(
            f"  {len(future_cols)} in-progress/future day column(s) blanked")
    if plan.unmatched:
        plan.log.append(
            f"  ⚠ {len(plan.unmatched)} board ICD(s) absent from the pull "
            f"(filled 0 — verify or add an alias): {plan.unmatched}")
    return plan

"""Sort every leaderboard high->low — the VAs do this by hand; the automation
now matches (Eve 2026-06-04). Two kinds of block, both found by structure so it
covers the campaign sections AND all 10 captainships:

  * DAILY section  — header row carries a 'RUNNING WEEK TOTALS' column; ICD rows
    (rank A, name B, Mon-Sun C..I, J==SUM running, K.. history). Sort by J desc;
    move the whole row, reset J to its row-relative =SUM.
  * WEEKLY leaderboard — a col-A section label (col B empty) followed by
    rank-numbered rows whose col C is the this-week total (a =SUMIF over the
    daily section) and D.. are static weekly history. Sort by C desc; move
    B + D..last, leave C (recomputes for the new name).

Pure planners return [{range, values}]; apply_sort writes them (caller picks the
COPY/REAL tab).
"""
from __future__ import annotations

from typing import List, Tuple
import gspread.utils as _gu

_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"}
_RUNNING = "running week totals"
_END_LABELS = {"totals", "total", "last week", "prior week",
               "2 weeks prior", "3 weeks prior", "grand total"}


def _a1(col: int) -> str:
    return _gu.rowcol_to_a1(1, col).rstrip("0123456789")


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").replace("$", "").strip() or 0)
    except ValueError:
        return 0.0


def _cell(grid, r, c) -> str:
    return grid[r][c] if (r < len(grid) and c < len(grid[r])) else ""


def _row_last_col(grid, r1: int) -> int:
    row = grid[r1 - 1] if r1 - 1 < len(grid) else []
    return max((i + 1 for i, v in enumerate(row) if str(v).strip()), default=0)


def plan_daily_sorts(grid: List[List[str]]) -> List[dict]:
    """Sort every daily section by its Running-Week-Total column, descending."""
    updates: List[dict] = []
    for i, row in enumerate(grid):
        run_c = next((c + 1 for c, v in enumerate(row)
                      if (v or "").strip().lower() == _RUNNING), None)
        if run_c is None:
            continue
        hdr = i + 1
        daynum = hdr + 1
        first = daynum + 1
        # ICD rows: rank in A or a name in B, until an end label appears.
        r = first
        while r <= len(grid):
            a = _cell(grid, r - 1, 0).strip().lower()
            b = _cell(grid, r - 1, 1).strip()
            if a in _END_LABELS or (not a and not b):
                break
            r += 1
        last = r - 1
        if last < first:
            continue
        lastcol = max(_row_last_col(grid, rr) for rr in range(first, last + 1))
        block = [[(grid[rr - 1] + [""] * lastcol)[:lastcol]
                  for rr in [rrr]][0] for rrr in range(first, last + 1)]
        order = sorted(block, key=lambda rr: _num(rr[run_c - 1]), reverse=True)
        out = []
        for k, rr in enumerate(order):
            nr = list(rr)
            nr[0] = k + 1                                           # rank
            nr[run_c - 1] = f"=SUM({_a1(3)}{first + k}:{_a1(run_c - 1)}{first + k})"
            out.append(nr)
        updates.append({"range": f"A{first}:{_a1(lastcol)}{last}", "values": out})
    return updates


def plan_leaderboard_sorts(grid: List[List[str]],
                           fgrid: List[List[str]]) -> List[dict]:
    """Sort every weekly leaderboard section by col C (this-week total), desc.

    Col C differs by block: the CAMPAIGN leaderboards use a name-keyed =SUMIF
    (leave it — it recomputes for the new name), but the CAPTAINSHIP leaderboards
    store a STATIC value in C (it must MOVE with the ICD). We detect which via
    the formula grid and move B (+C if static) + D..last accordingly."""
    updates: List[dict] = []
    i = 0
    while i < len(grid):
        a = _cell(grid, i, 0).strip()
        b = _cell(grid, i, 1).strip()
        nxt_a = _cell(grid, i + 1, 0).strip()
        nxt_b = _cell(grid, i + 1, 1).strip()
        if (a and not b and a.lower() not in _END_LABELS
                and nxt_a == "1" and nxt_b
                and str(_cell(grid, i + 1, 2)).strip()):
            first = i + 2
            r = first
            while r <= len(grid) and _cell(grid, r - 1, 0).strip().isdigit():
                r += 1
            last = r - 1
            lastcol = max(_row_last_col(grid, rr) for rr in range(first, last + 1))
            if lastcol >= 4:
                block = [(grid[rr - 1] + [""] * lastcol)[:lastcol]
                         for rr in range(first, last + 1)]
                order = sorted(block, key=lambda rr: _num(rr[2]), reverse=True)
                ranks = [[k + 1] for k in range(len(order))]
                names = [[rr[1]] for rr in order]
                updates.append({"range": f"A{first}:A{last}", "values": ranks})
                updates.append({"range": f"B{first}:B{last}", "values": names})
                c_is_formula = str(_cell(fgrid, first - 1, 2)).startswith("=")
                if c_is_formula:
                    # C is a row-keyed =SUMIF — leave it, move only D..last
                    hist = [rr[3:lastcol] for rr in order]
                    updates.append({"range": f"D{first}:{_a1(lastcol)}{last}",
                                    "values": hist})
                else:
                    # C is a static value — move C..last with the ICD
                    body = [rr[2:lastcol] for rr in order]
                    updates.append({"range": f"C{first}:{_a1(lastcol)}{last}",
                                    "values": body})
            i = last
        i += 1
    return updates


def apply_sort(ws, dry_run: bool = False, logfn=print) -> List[dict]:
    grid = ws.get_all_values()
    fgrid = ws.get(f"A1:{_a1(108)}{len(grid)}", value_render_option="FORMULA")
    updates = plan_daily_sorts(grid) + plan_leaderboard_sorts(grid, fgrid)
    logfn(f"  sort: {len(updates)} range(s) across daily + leaderboard blocks")
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logfn(f"  [OK] sorted {len(updates)} block(s)")
    return updates

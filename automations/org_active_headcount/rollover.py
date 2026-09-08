"""Roll the tab one week: C -> D, and D's old week out into the history.

THE MODEL (Eve, 2026-09-07). Three live columns and a run of history:

    C  'Total this week'  the week that just closed - what the fill writes
    D  'Last week'        the week before it, held as VALUES, not a formula
    E  'Delta'            =(C-D)/D
    F.. the history, NEWEST FIRST, each headed 'WE mm.dd'

So the two visible numbers are always the last two closed weeks, and D is why
WE 08.30 has no column of its own: it IS 'Last week' right now. Eve, asked
whether to restore the column: "no la repongas porque WE 8.30 es 'Last Week'".

THE ROLL, in the order it has to happen:
  1. the week leaving D is written into the history column HEADED with that
     week. Eve keeps such columns ready ahead of time (WE 9.20 / 9.13 / 9.6 were
     sitting empty on the day this was written), and filling a reserved column
     is the normal case - "1B". Only when no column carries that week's label is
     a new one inserted, in its chronological place among the others.
  2. C's values move into D as LITERALS. D stops being derived the moment it
     holds a week nothing else on the tab remembers.
  3. C is cleared, ready for the fill.

WHAT IT NEVER TOUCHES. The totals row's `=IF(COUNT(..)=0,"",SUM(..))` and the
per-row Delta. Both are per-column or per-row and re-derive themselves; writing
them back as literals would freeze each on today's number, and nothing would
look wrong afterwards because a frozen value is correct for the moment it froze.
That is the bug that sat on the ORG Sales Board's delta boxes for a week
(`org_sales_board/delta_sort.py` tells it).

IDEMPOTENT. The tab says which week it is on - D's own header week, tracked by
the label of the newest history column plus what C holds - so a second run the
same morning does nothing. Week labels are compared as STRINGS ('WE 09.06'):
the headers carry no year, and parsing one in late December means guessing.

    python -m automations.org_active_headcount.rollover            # dry-run
    python -m automations.org_active_headcount.rollover --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List, Optional, Tuple

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_sales_board.week import reporting_sunday
from automations.org_active_headcount import structure as st

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

MAX_CATCHUP = 4      # weeks; past this something is wrong - say so, don't guess


def _shift(label: str, days: int) -> str:
    """'WE 08.30' moved by N days. A leap year is used as the calendar so Feb 29
    exists; the year never reaches the output."""
    d = st.parse_we(label, 2024)
    return label if d is None else st.we_label(d + dt.timedelta(days=days))


def newest_filled(grid: List[List]) -> Optional[str]:
    """The newest history week that actually HAS numbers.

    Not simply the leftmost header. Eve keeps columns for future weeks ready and
    empty (WE 9.20 / 9.13 / 9.6 the day this was written), so the leftmost LABEL
    is a week that has not happened. Reading that as the tab's position put the
    roll two weeks off and it still produced a confident, wrong plan.

    A column counts as filled when any ICD in any box has a value in it - the
    totals row is excluded, since its formula answers 0 for an empty week.
    """
    for box in st.find_boxes(grid):
        for c, lbl in box["week_cols"]:
            if any(st.cell(grid, r, c) for r, _ in box["rows"]):
                return lbl
    return None


def live_week(grid: List[List]) -> Optional[str]:
    """The week column C is holding.

    Derived from the roll's own arithmetic rather than stored: the newest FILLED
    history week left D two rolls ago, so D is one week newer than it and C is
    one newer again.
    """
    newest = newest_filled(grid)
    return None if newest is None else _shift(newest, 14)


def target_week(today: Optional[dt.date] = None) -> str:
    return st.we_label(reporting_sunday(today or dt.date.today()))


def needs_roll(grid: List[List], today: Optional[dt.date] = None) -> bool:
    """Has the reporting week moved past what C is holding?"""
    live = live_week(grid)
    return live is not None and live != target_week(today)


def plan_roll(grid: List[List], departing: str, moving: str
              ) -> Tuple[List[Tuple[str, object]], List[str]]:
    """([(A1, value)], [weeks needing a NEW column]) for one roll.

    `departing` is the week leaving D and `moving` is the week going from C into
    D. Pure - no I/O. A week with nowhere to land is REPORTED rather than
    written somewhere approximate; the caller inserts the column and re-plans.
    """
    out: List[Tuple[str, object]] = []
    need: List[str] = []
    for box in st.find_boxes(grid):
        col = next((c for c, lbl in box["week_cols"] if lbl == departing), None)
        if col is None:
            if departing not in need:
                need.append(departing)
            continue
        d_col, c_col = box["last_col"], box["this_col"]
        for row, _icd in box["rows"]:
            out.append((f"{st.a1col(col)}{row}", st.cell(grid, row, d_col)))
            out.append((f"{st.a1col(d_col)}{row}", st.cell(grid, row, c_col)))
            out.append((f"{st.a1col(c_col)}{row}", ""))
        out.append((f"{st.a1col(box['header_row'] and col)}"
                    f"{box['header_row']}", departing))
    _ = moving
    return out, need


def plan_insert(grid: List[List], week: str, sheet_id: int) -> List[dict]:
    """`insertDimension` requests putting `week` in its chronological place.

    Newest-first, so the new column goes immediately LEFT of the first existing
    week older than it - which for the ordinary roll is right after the Delta
    column, exactly where Eve asked for it. Inserting by position rather than
    always at F keeps the run of weeks in order even when a reserved column for
    a future week is already sitting there.
    """
    reqs: List[dict] = []
    for box in st.find_boxes(grid):
        d = st.parse_we(week, 2024)
        at = None
        for c, lbl in box["week_cols"]:
            other = st.parse_we(lbl, 2024)
            if other is not None and d is not None and other < d:
                at = c
                break
        if at is None:
            at = (max(c for c, _ in box["week_cols"]) + 1
                  if box["week_cols"] else box["delta_col"] + 1)
        reqs.append({"insertDimension": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": at - 1, "endIndex": at},
            "inheritFromBefore": True}})
    return reqs


def run(*, apply_changes: bool = False, live_tab: bool = True,
        today: dt.date | None = None, logfn=print) -> dict:
    today = today or dt.date.today()
    tab = st.BOARD_TAB if live_tab else st.SANDBOX_TAB
    sh = open_by_key(st.SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.title.strip() == tab), None)
    if ws is None:
        raise ValueError(f"tab {tab!r} not found in the workbook")
    grid = ws.get_all_values()
    want = target_week(today)
    newest = newest_filled(grid) or "?"
    logfn(f"tab: {ws.title!r}   C holds: {live_week(grid) or '?'}   "
          f"newest filled history: {newest}   target: {want}   "
          f"{'APPLY' if apply_changes else 'DRY-RUN'}")
    if not needs_roll(grid, today):
        logfn("  already on the target week - nothing to roll.")
        return {"rolled": False, "written": 0}

    # C holds the week before the target; D holds the one before that.
    moving = _shift(want, -7)
    departing = _shift(want, -14)
    logfn(f"  {departing} leaves 'Last week'; {moving} moves C -> D; "
          f"C cleared for {want}")

    updates, need = plan_roll(grid, departing, moving)
    if need:
        logfn(f"  no column headed {need[0]!r} - inserting one in date order")
        if apply_changes:
            _retry(ws.spreadsheet.batch_update,
                   {"requests": plan_insert(grid, need[0], ws.id)})
            grid = ws.get_all_values()
            updates, need = plan_roll(grid, departing, moving)
        else:
            logfn("  (dry-run: cannot plan the writes until the column exists)")
            return {"rolled": False, "written": 0, "needs_column": need}

    for a1, v in updates[:12]:
        logfn(f"    {a1:>6s} <- {v!r}")
    if len(updates) > 12:
        logfn(f"    ... {len(updates) - 12} more")
    n = 0
    if apply_changes and updates:
        _retry(ws.batch_update,
               [{"range": a1, "values": [[v]]} for a1, v in updates],
               value_input_option="USER_ENTERED")
        n = len(updates)
    logfn(f"{len(updates)} cell(s) planned, {n} written.")
    return {"rolled": True, "written": n}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sandbox", action="store_true",
                    help="target the sandbox copy instead of the live tab")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD")
    a = ap.parse_args()
    today = dt.datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else None
    run(apply_changes=a.apply, live_tab=not a.sandbox, today=today)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

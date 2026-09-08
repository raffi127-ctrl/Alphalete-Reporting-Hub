"""Make every backward-looking formula follow the DATA, not a fixed column.

Eve, 2026-09-07: "modifica las formulas para que siempre cubran las ultimas 4
semanas que tienen datos".

WHY IT MATTERS RIGHT NOW. The history columns are newest-first, and Eve keeps
empty ones ready on the left for weeks that have not happened yet (WE 9.20,
9.13, 9.6 on the day this was written). Every formula that named a column by
letter broke the moment those appeared: `D` was `=H`, H was the empty WE 9.6,
so 'Last week' read blank and EVERY delta on the tab showed 0%. Nothing errored.
A formula that points at a letter is a formula that goes wrong silently the next
time somebody inserts a column.

THE FIX is to ask for the first history cell that HAS a number, not the cell in
a particular place:

    Prior Week      = the 1st non-empty history cell on that row
    2 Weeks Prior   = the 2nd
    3 Weeks Prior   = the 3rd
    4 Week AVG      = the mean of 'Last week' and the first three

`D` ('Last week') is NOT among them: it holds VALUES the roll moves across from
`C`, which is the whole reason WE 08.30 needs no column of its own (Eve: "no la
repongas porque WE 8.30 es 'Last Week'"). Making it a formula was wrong and is
what this file used to do.

`FILTER` drops the blanks and `ARRAY_CONSTRAIN` takes the newest four of what is
left, so reserved columns are skipped while they are empty and join in by
themselves the week they are filled. No formula has to be rewritten on a roll.

ONE THING THIS NEEDS FROM THE TOTALS ROW. Its history cells are `=SUM(...)`,
which returns 0 — not blank — for a week whose ICDs are all empty, so a plain
`<>""` test would count an empty reserved week as a real zero and drag the
average down. So the totals row gets `=IF(COUNT(range)=0,"",SUM(range))`: no
data in, nothing out. That is also why the test is emptiness and not `>0` — a
week where genuinely nobody sold IS a zero and has to keep counting.

    python -m automations.org_active_headcount.dynamic_formulas            # dry-run
    python -m automations.org_active_headcount.dynamic_formulas --apply
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Tuple

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_active_headcount import structure as st

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

# Summary column -> which of the row's non-empty history weeks it shows.
# 'Last week' is the 1st, so 'Prior Week' is the 2nd, and so on.
SUMMARY_NTH = {"Prior Week": 1, "2 Weeks Prior": 2, "3 Weeks Prior": 3}
AVG_HEADER = "4 Week AVG"
AVG_WEEKS = 4


def _hist(row: int, first: int, last: int) -> str:
    """The row's history range, absolute in the columns so a copy across keeps
    looking at the same weeks."""
    return f"${st.a1col(first)}{row}:${st.a1col(last)}{row}"


def _nth(row: int, first: int, last: int, n: int) -> str:
    """The Nth history value on this row that actually has one."""
    r = _hist(row, first, last)
    return f'=IFERROR(INDEX(FILTER({r},{r}<>""),{n}),"")'


def plan(grid: List[List]) -> List[Tuple[str, object]]:
    """[(A1, formula)] — pure, no I/O."""
    out: List[Tuple[str, object]] = []
    boxes = st.find_boxes(grid)
    for box in boxes:
        cols = [c for c, _ in box["week_cols"]]
        if not cols:
            continue
        first, last = min(cols), max(cols)
        t = box["total_row"]
        # Totals: blank in, blank out, so an untouched week is skipped rather
        # than counted as a zero.
        for c in cols:
            rng = (f"{st.a1col(c)}{box['rows'][0][0]}:"
                   f"{st.a1col(c)}{box['rows'][-1][0]}")
            out.append((f"{st.a1col(c)}{t}",
                        f'=IF(COUNT({rng})=0,"",SUM({rng}))'))
        out.append((f"{st.a1col(box['last_col'])}{t}",
                    f"=IF(COUNT({st.a1col(box['last_col'])}{box['rows'][0][0]}:"
                    f"{st.a1col(box['last_col'])}{box['rows'][-1][0]})=0,\"\","
                    f"SUM({st.a1col(box['last_col'])}{box['rows'][0][0]}:"
                    f"{st.a1col(box['last_col'])}{box['rows'][-1][0]}))"))
        _ = first, last

    summary = st.find_summary(grid)
    if not summary:
        return out
    cols = summary["cols"]
    for campaign, row in summary["rows"].items():
        box = st.find_box(boxes, campaign)
        if not box:
            raise ValueError(f"summary row {row} says {campaign!r} - no such box")
        bcols = [c for c, _ in box["week_cols"]]
        if not bcols:
            continue
        bf, bl, t = min(bcols), max(bcols), box["total_row"]
        for label, n in SUMMARY_NTH.items():
            if label in cols:
                out.append((f"{st.a1col(cols[label])}{row}", _nth(t, bf, bl, n)))
        if AVG_HEADER in cols:
            # 'Last week' (col D of the summary) plus the newest three history
            # weeks that have data = the last four closed weeks.
            r = _hist(t, bf, bl)
            d = f"{st.a1col(cols['Last week'])}{row}"
            out.append((f"{st.a1col(cols[AVG_HEADER])}{row}",
                        f'=IFERROR(AVERAGE({d},ARRAY_CONSTRAIN('
                        f'FILTER({r},{r}<>""),1,{AVG_WEEKS - 1})),"")'))
    return out


def run(*, apply_changes: bool = False, live_tab: bool = True,
        logfn=print) -> dict:
    tab = st.BOARD_TAB if live_tab else st.SANDBOX_TAB
    sh = open_by_key(st.SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.title.strip() == tab), None)
    if ws is None:
        raise ValueError(f"tab {tab!r} not found in the workbook")
    updates = plan(ws.get_all_values())
    for a1, v in updates:
        logfn(f"  {a1:>6s} <- {v}")
    if apply_changes and updates:
        _retry(ws.batch_update,
               [{"range": a1, "values": [[v]]} for a1, v in updates],
               value_input_option="USER_ENTERED")
    logfn(f"{len(updates)} formula(s) planned, "
          f"{len(updates) if apply_changes else 0} written.")
    return {"planned": len(updates)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sandbox", action="store_true",
                    help="target the sandbox copy instead of the live tab")
    a = ap.parse_args()
    run(apply_changes=a.apply, live_tab=not a.sandbox)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

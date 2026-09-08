"""Write the week's active headcount into each box's `C` column. Nothing else.

C IS THE ONLY COLUMN THIS TOUCHES. `D` is `=F`, `E` is the delta, the totals row
is `=SUM(...)`, and `F..L` are history the rollover owns. Every one of those
re-derives itself the moment C changes, so writing a single column per ICD is
the whole fill — and writing any of the others back as a literal would freeze a
live formula, which is the exact bug that cost the ORG board a week
(`org_sales_board/delta_sort.py` keeps that story).

AN ICD THE SOURCE DOESN'T MENTION IS LEFT ALONE AND REPORTED. Absent is not
zero: a view that dropped an owner, a name the aliases don't cover yet, and an
ICD whose reps genuinely all sold nothing are three different facts, and only
one of them is a 0. Writing 0 for the first two is how a campaign quietly reads
as dead while every total still balances. So a missing ICD keeps last week's
cell, and its name comes back in `missing` for the run to report.

MATCHING IS BY NORMALISED NAME, with the campaign's alias applied first
(`sources.source_name`). The board says 'Muhammad Haque' and the ATT crosstab
says 'Hammad Haque'; that mapping lives in `sources.ALIASES`, once, instead of
being a per-report patch [[project_icd-aliases-direction]].
"""
from __future__ import annotations

import sys
from typing import Dict, List, Tuple

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_active_headcount import sources as src
from automations.org_active_headcount import structure as st

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass


def plan(grid: List[List], counts: Dict[str, Dict[str, int]]
         ) -> Tuple[List[Tuple[str, object]], Dict[str, List[str]]]:
    """([(A1, value)], {box: [ICDs the source didn't carry]}). Pure, no I/O.

    `counts` is {box label: {normalised ICD name: headcount}} — what
    `pull.collect` returns. A box with no entry at all (its pull failed) is
    skipped whole, not zeroed.
    """
    updates: List[Tuple[str, object]] = []
    missing: Dict[str, List[str]] = {}
    for box in st.find_boxes(grid):
        got = next((v for k, v in counts.items()
                    if st.match_box(k, box["campaign"])), None)
        if got is None:
            continue                       # no pull for this campaign this run
        # Does absence mean zero on this campaign, or mean unknown? See
        # `sources.Campaign.absent_is_zero`.
        zero_ok = any(c.absent_is_zero for c in src.CAMPAIGNS
                      if st.match_box(c.box, box["campaign"]))
        gaps: List[str] = []
        for row, icd in box["rows"]:
            key = src.norm(src.source_name(icd))
            if key not in got:
                if zero_ok:
                    updates.append((f"{st.a1col(box['this_col'])}{row}", 0))
                gaps.append(icd)
                continue
            updates.append((f"{st.a1col(box['this_col'])}{row}", got[key]))
        if gaps:
            missing[box["campaign"]] = gaps
    return updates, missing


def apply(ws, updates: List[Tuple[str, object]]) -> int:
    if not updates:
        return 0
    body = [{"range": a1, "values": [[v]]} for a1, v in updates]
    _retry(ws.batch_update, body, value_input_option="USER_ENTERED")
    return len(updates)


def run(*, counts: Dict[str, Dict[str, int]], apply_changes: bool = False,
        live_tab: bool = True, logfn=print) -> dict:
    tab = st.BOARD_TAB if live_tab else st.SANDBOX_TAB
    sh = open_by_key(st.SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.title.strip() == tab), None)
    if ws is None:
        raise ValueError(f"tab {tab!r} not found in the workbook")
    grid = ws.get_all_values()
    updates, missing = plan(grid, counts)
    for a1, v in updates:
        logfn(f"  {a1:>6s} <- {v}")
    for campaign, names in missing.items():
        logfn(f"  [not in source] {campaign}: {', '.join(names)}")
    n = apply(ws, updates) if apply_changes else 0
    logfn(f"{len(updates)} cell(s) planned, {n} written, "
          f"{sum(len(v) for v in missing.values())} ICD(s) not in their source.")
    return {"planned": len(updates), "written": n, "missing": missing,
            "tab": ws.title}

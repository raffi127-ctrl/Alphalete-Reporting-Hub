"""Fix the hand-built tab's summary block — the six things it got wrong.

The tab was built by copying the ORG Sales Board's 'Product Summary' + delta-box
formatting. The copy carried over formulas that are right for UNITS PER DAY and
wrong for PEOPLE PER WEEK, plus three plain mistakes. All six are in the summary
block (rows 3-17); the boxes themselves are fine.

WHAT IT FIXES, and why each one matters:

1. BOX POINTED AT B2B. `C10` … `G10` read the B2B totals row, so the summary
   showed B2B's number twice and BOX's never. Every summary row is now rebuilt
   from the box the finder actually located, so the two can't drift again.

2. THE SUMMARY SKIPPED A WEEK. 'Last week' read `D<total>` and 'Prior Week' read
   `F<total>` — but `D` IS `=F`, so both showed the same week and 'Prior Week',
   '2 Weeks Prior' and '3 Weeks Prior' were each one week too new. Now:
   This Week=C, Last week=D, Prior=G, 2wk=H, 3wk=I.

3. 'GRAND TOTAL' SUMMED FIVE WEEKS OF PEOPLE. `=SUM(C5:G5)` is the right idea for
   a week of unit sales and meaningless for headcount — 40 heads five weeks
   running displayed as 200. It becomes a 4-WEEK AVERAGE over the four closed
   weeks (`=AVERAGE(D5:G5)`), which is also the number row 17 wants to compare
   against. Eve, 2026-09-07. Header relabelled '4 Week AVG'.

4. `#REF!` IN E16:G16 — three of the five 'This Week vs' cells were broken
   references. The row is rebuilt as one % per week COLUMN it compares against
   (D=vs Last week, E=vs Prior, F=vs 2wk, G=vs 3wk), so each number sits under
   the week it is measured against instead of all five crowding under 'This Week'.

5. `vs 4 WeekAVG` COMPARED A PERCENTAGE TO AN EMPTY CELL
   (`=IFERROR((C16-D13)/D13,0)`). It now compares this week's total to the new
   4-week average in H12.

6. TWO TOTALS ROWS HAD NO NAME. The BOX and Retail Internet boxes' totals rows
   were blank in col A while the other five said 'Captainship'. Nothing breaks
   today (the finders are structural), but a blank row label in a stack of seven
   named ones is the kind of thing someone "tidies up" into a real hole later.

Also normalises the col-A rank gutter to literals. Two boxes carried an
'=A45+1' chain: it survives a sort (the ranks stay 1..N while rows move under
them) but not a row INSERT, which is how a new ICD arrives.

    python -m automations.org_active_headcount.skeleton_repair            # dry-run
    python -m automations.org_active_headcount.skeleton_repair --apply
    python -m automations.org_active_headcount.skeleton_repair --apply --live-tab
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Tuple

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_active_headcount import structure as st

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

# Summary column header -> which column of a campaign's BOX it reads.
#   C 'Total this week' | D 'Last week' (=F) | F..L the seven history weeks
# so Prior Week is the box's SECOND history column (G), and so on.
SUMMARY_SOURCE = {
    "This Week":      "C",
    "Last week":      "D",
    "Prior Week":     "G",
    "2 Weeks Prior":  "H",
    "3 Weeks Prior":  "I",
}
AVG_HEADER = "4 Week AVG"          # replaces the old 'Grand Total'
VS_ROW_LABEL = "This Week HC"      # was 'This Week vs' (Eve, 2026-09-07)
TOTALS_LABEL = "Captainship"


def plan(grid: List[List], formulas: List[List] | None = None
         ) -> List[Tuple[str, object]]:
    """[(A1, value)] — every cell this repair would write. Pure, no I/O.

    `formulas` is the same rectangle rendered as FORMULA. It is what makes the
    rank-gutter check work: `get_all_values` returns what a cell DISPLAYS, so an
    '=A45+1' chain reads back as '2' and looks already-correct."""
    formulas = formulas or grid
    all_boxes = st.find_boxes(grid)
    boxes = {b["campaign"]: b for b in all_boxes}
    summary = st.find_summary(grid)
    if not summary:
        raise ValueError("no 'Headcount Summary' block on the tab")
    cols = summary["cols"]
    missing = [k for k in SUMMARY_SOURCE if k not in cols]
    if missing:
        raise ValueError(f"summary is missing column(s): {missing}")
    # The old 'Grand Total' column, whatever letter it sits in.
    avg_col = cols.get("Grand Total") or cols.get(AVG_HEADER)
    if avg_col is None:
        raise ValueError("summary has no 'Grand Total' / '4 Week AVG' column")
    first = min(cols[k] for k in SUMMARY_SOURCE)          # C
    last = max(cols[k] for k in SUMMARY_SOURCE)           # G

    out: List[Tuple[str, object]] = []
    a1 = st.a1col

    # --- 1+2+3: one summary row per campaign, rebuilt from its own box -------
    for campaign, row in summary["rows"].items():
        box = st.find_box(all_boxes, campaign)
        if not box:
            raise ValueError(
                f"summary row {row} says {campaign!r} but there is no such box")
        t = box["total_row"]
        for label, src in SUMMARY_SOURCE.items():
            out.append((f"{a1(cols[label])}{row}", f"={src}{t}"))
        out.append((f"{a1(avg_col)}{row}",
                    f"=AVERAGE({a1(cols['Last week'])}{row}:"
                    f"{a1(last)}{row})"))

    # --- the Grand Total row: sum down each week column, average across -------
    g = summary["grand_total_row"]
    if g:
        rows = sorted(summary["rows"].values())
        r0, rN = rows[0], rows[-1]
        for c in range(first, last + 1):
            out.append((f"{a1(c)}{g}", f"=SUM({a1(c)}{r0}:{a1(c)}{rN})"))
        out.append((f"{a1(avg_col)}{g}",
                    f"=AVERAGE({a1(cols['Last week'])}{g}:{a1(last)}{g})"))

    # --- header: 'Grand Total' -> '4 Week AVG' on the summary block ----------
    if st.cell(grid, summary["header_row"], avg_col).strip().lower() == "grand total":
        out.append((f"{a1(avg_col)}{summary['header_row']}", AVG_HEADER))

    # --- 4+5: the 'This Week HC' comparison row ------------------------------
    # Eve's layout, 2026-09-07: the block drops its own 'This Week' column (it
    # was always blank — this week compared against itself) and starts straight
    # at 'Last week', so its five columns are Last week / Prior Week / 2 Weeks
    # Prior / 3 Weeks Prior / 4 Week AVG. Each cell is this week's grand total
    # DIVIDED BY that column's grand total — a ratio ("519 is 114% of last
    # week"), not a percent change. The old 'vs 4 WeekAVG' row below is retired:
    # the 4-week average is now this row's last column.
    if g:
        vs_row = _find_label_row(grid, VS_ROW_LABEL, after=g) or \
            _find_label_row(grid, "This Week vs", after=g)
        if vs_row:
            # The row LABEL is Eve's, not ours. It was renamed by hand after the
            # first pass ('This Week HC' -> 'This Week vs' with 'All Campaigns
            # HC' above it), and a repair that keeps rewriting somebody's wording
            # is a repair they stop running. Only the formulas are ours.
            headers = [k for k in SUMMARY_SOURCE if k != "This Week"] + [AVG_HEADER]
            srcs = [cols[k] for k in SUMMARY_SOURCE if k != "This Week"] + [avg_col]
            # The block's OWN header row is the one directly above it. Deriving
            # it beats an offset from the summary header: the two blocks are
            # eleven rows apart today and one inserted row makes that a lie.
            hdr_row = vs_row - 1
            for n, (hdr, sc) in enumerate(zip(headers, srcs)):
                col = first + n
                out.append((f"{a1(col)}{hdr_row}", hdr))
                out.append((f"{a1(col)}{vs_row}",
                            f"=IFERROR(${a1(first)}${g}/{a1(sc)}{g},0)"))
            # anything past the five columns is left over from the old layout
            for col in range(first + len(headers), avg_col + 1):
                out.append((f"{a1(col)}{hdr_row}", ""))
                out.append((f"{a1(col)}{vs_row}", ""))
        avg_row = _find_label_row(grid, "vs 4 WeekAVG", after=g)
        if avg_row:
            out.append((f"B{avg_row}", ""))
            out.append((f"{a1(first)}{avg_row}", ""))

    # --- 6: name the two unnamed totals rows, and settle the rank gutter -----
    for box in boxes.values():
        t = box["total_row"]
        if not st.cell(grid, t, 1):
            out.append((f"A{t}", TOTALS_LABEL))
        for n, (row, _name) in enumerate(box["rows"], start=1):
            if st.cell(formulas, row, 1) != str(n):
                out.append((f"A{row}", n))
    return out


def _find_label_row(grid: List[List], label: str, after: int) -> int | None:
    want = label.strip().lower()
    for i in range(after, min(after + 12, len(grid)) + 1):
        if st.cell(grid, i, 2).strip().lower() == want:
            return i
    return None


def apply(ws, updates: List[Tuple[str, object]]) -> int:
    """Write the planned cells. USER_ENTERED so '=...' lands as a formula."""
    if not updates:
        return 0
    body = [{"range": a1, "values": [[v]]} for a1, v in updates]
    _retry(ws.batch_update, body, value_input_option="USER_ENTERED")
    return len(updates)


def hide_history(ws, grid: List[List], *, apply_changes: bool,
                 logfn=print) -> int:
    """Hide the history week columns so only This Week / Last Week show.

    Eve's spec: "las columnas visibles siempre son This Week y Last Week". The
    seven history columns stay on the tab and keep feeding the summary — they
    are just folded away, and anyone can unhide them to read the run of weeks.

    The range is DERIVED from the boxes' own week headers, not typed: hiding
    'F:L' by name would start hiding the wrong thing the day a column is
    inserted. Hiding COLUMNS is safe here — the trap in this workbook is a
    hidden TAB, which exports as a blank PDF [[project_sheets-pdf-export-hidden-tab-is-blank]].
    """
    cols = sorted({c for b in st.find_boxes(grid) for c, _ in b["week_cols"]})
    if not cols:
        logfn("  hide: no week columns found — nothing hidden")
        return 0
    first, last = cols[0], cols[-1]
    logfn(f"  hide: columns {st.a1col(first)}:{st.a1col(last)} "
          f"({len(cols)} history weeks)")
    if not apply_changes:
        return 0
    _retry(ws.spreadsheet.batch_update, {"requests": [{"updateDimensionProperties": {
        "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                  "startIndex": first - 1, "endIndex": last},
        "properties": {"hiddenByUser": True},
        "fields": "hiddenByUser"}}]})
    return last - first + 1


def run(*, apply_changes: bool = False, live_tab: bool = True,
        hide: bool = False, logfn=print) -> dict:
    tab = st.BOARD_TAB if live_tab else st.SANDBOX_TAB
    sh = open_by_key(st.SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.title.strip() == tab), None)
    if ws is None:
        raise ValueError(f"tab {tab!r} not found in the workbook")
    logfn(f"tab: {ws.title!r}   {'APPLY' if apply_changes else 'DRY-RUN'}")
    grid = ws.get_all_values()
    formulas = _retry(ws.get, f"A1:{st.a1col(ws.col_count)}{len(grid)}",
                      value_render_option="FORMULA")
    updates = plan(grid, formulas)
    for a1, v in updates:
        logfn(f"  {a1:>6s} <- {v!r}")
    n = apply(ws, updates) if apply_changes else 0
    hidden = hide_history(ws, grid, apply_changes=apply_changes,
                          logfn=logfn) if hide else 0
    logfn(f"{len(updates)} cell(s) planned, {n} written, {hidden} column(s) hidden.")
    return {"planned": len(updates), "written": n, "hidden": hidden,
            "tab": ws.title}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the cells")
    ap.add_argument("--sandbox", action="store_true",
                    help="target the sandbox copy instead of the live tab")
    ap.add_argument("--hide", action="store_true",
                    help="fold the history week columns away (F..L)")
    a = ap.parse_args()
    run(apply_changes=a.apply, live_tab=not a.sandbox, hide=a.hide)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

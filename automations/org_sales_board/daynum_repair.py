"""Repair the day-number rows on the 1IpDs2 boards when they stop matching
real dates.

WHAT BREAKS
-----------
Under each daily section's Monday…Sunday header sits a row of day-of-month
numbers, and `fill_section.find_daily_section` maps `pull date → column` by
reading it. On both boards of this workbook that row shipped as a CHAIN: one
literal in the first day column and `=<prev cell>+1` across the other six.
Every other section MIRRORS the master row cell-for-cell (`=C77`, `=D77`, …),
so the whole tab hangs off those seven cells.

The chain has two failure modes, and we have now had both:

  • **Month end (2026-09-02, this module's reason for existing).** 31 + 1 = 32.
    The week of Mon 8/31 rolled to `31 32 33 34 35 36 37`, so every day from
    9/1 on had no column anywhere on either tab. The fill logged its ⚠, wrote
    nothing for those days and the ORG board went out SEVEN sections short —
    Retail NL, Retail Internet, ATT Fiber Team, ATT NDS Team, B2B, BOX and
    Retail JE all dropped 2026-09-01 and the board did not post.

  • **A typed literal (2026-08-09).** Because the chain cannot cross a month
    end, someone eventually types the right number over one of those cells by
    hand. That fixes the week in front of them and freezes that day — and
    every day after it — on the old week from the next roll onward
    ([[project_board-daynum-chain-frozen-drops-days]]).

THE FIX, AND WHY THIS MODULE IS THE SMALL HALF OF IT
----------------------------------------------------
The real fix is in the rollovers: `org_sales_board.rollover` step 5/5 and
`all_campaigns_board.rollover` step 6/6 now rewrite the day-number row WHOLE,
as seven literals (`fill_section.daynum_row_update`), instead of setting the
anchor cell and trusting the chain. Seven literals cannot drift and cannot hit
32. That is what the Country board has always done, and it has never lost a
day.

This module repairs a row that is ALREADY wrong — today's board, or any week a
stray chain is found again — without waiting for Tuesday:

  • a MIRROR row (every day cell an `=<col><other row>` reference) is left
    alone; it is correct by construction and follows its source.
  • a row that mirrors in its first cell and then chains off ITSELF
    (`C1580 = =C77`, `D1580 = =C1580+1`, …) is rewritten as a full mirror of
    the row it already points at. That shape is the leftover of a hand repair.
  • anything else — the master anchor — is rewritten as seven literals for the
    section's OWN week (`fill_section.section_week`, so Frontier's Sun–Sat
    span is honoured rather than "fixed" onto Monday).

Idempotent: a correct tab writes nothing. Dry-run by default.

    python -m automations.org_sales_board.daynum_repair            # show
    python -m automations.org_sales_board.daynum_repair --apply    # write
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import List, Optional

from automations.recruiting_report.fill import open_by_key
from automations.org_sales_board import fill_section as fs
from automations.org_sales_board.tabs import BOARD_TAB

SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
# The All Campaigns tab's live title carries a trailing space (see
# all_campaigns_board.run.TARGET_TAB) — keep it verbatim or the open fails.
ALL_CAMPAIGNS_TAB = "All Campaigns Org Sales Board "
DEFAULT_TABS = [BOARD_TAB, ALL_CAMPAIGNS_TAB]

_REF = re.compile(r"^=\s*\$?([A-Z]{1,2})\$?(\d+)\s*$")


def _fcell(form: List[List], r0: int, c0: int) -> str:
    """FORMULA-rendered cell as text. The FORMULA render hands back real ints
    for literal numbers, so `fs._cell` (which .strip()s) blows up on them."""
    if 0 <= r0 < len(form) and 0 <= c0 < len(form[r0]):
        return str(form[r0][c0] if form[r0][c0] is not None else "").strip()
    return ""


def _sections(grid: List[List[str]]) -> List[dict]:
    """Every daily section on the tab, by SHAPE not by label.

    Labels repeat — there are four 'ATT NDS - All Units' sections and six
    'Fiber - All Units' — and `find_daily_section` returns the first match, so
    a label-driven check cannot see the broken one (Eve 2026-08-09). A daily
    section is any row carrying the 'RUNNING WEEK TOTALS' header with weekday
    columns beside it.
    """
    out = []
    for i, row in enumerate(grid):
        if not any(c.strip().lower() == fs.RUNNING_TOTAL_HDR for c in row):
            continue
        day_cols = [j + 1 for j, c in enumerate(row)
                    if c.strip().lower() in fs.WEEKDAYS]
        if not day_cols:
            continue
        first_wd = fs.WEEKDAY_ORDER.index(
            row[min(day_cols) - 1].strip().lower())
        out.append({"label": (row[0] or "").strip() or "(unlabelled)",
                    "header_row": i + 1, "daynum_row": i + 2,
                    "day_cols": day_cols, "first_weekday": first_wd})
    return out


def _week_start(sec: dict, today: dt.date) -> dt.date:
    """The date the section's leftmost day column should carry — its OWN week
    (Frontier runs Sun–Sat), reusing `fill_section.section_week`."""
    anchor = fs.SectionAnchor(
        header_row=sec["header_row"], daynum_row=sec["daynum_row"],
        totals_row=sec["daynum_row"] + 1,
        day_col_by_daynum={1: min(sec["day_cols"])}, running_total_col=1,
        icd_rows={}, first_weekday=sec["first_weekday"])
    return fs.section_week(anchor, today)[0]


def plan(grid: List[List[str]], form: List[List[str]],
         today: Optional[dt.date] = None) -> List[dict]:
    """`batch_update` entries needed to make every day-number row read the
    real dates. Empty list = the tab is already right."""
    today = today or dt.date.today()
    updates = []
    for sec in _sections(grid):
        dn = sec["daynum_row"]
        cols = sorted(sec["day_cols"])
        cells = [_fcell(form, dn - 1, c - 1) for c in cols]
        refs = [_REF.match(c) for c in cells]

        # A pure mirror of ONE other row: correct by construction, and fixing
        # its source fixes it. Leave it — rewriting these to `=prev+1` is how
        # the 8/9 incident got a second broken chain.
        if all(refs) and len({m.group(2) for m in refs}) == 1:
            src = refs[0].group(2)
            if src != str(dn):
                continue

        want_first = refs[0] and refs[0].group(2) != str(dn)
        if want_first:
            # Mirrors in col C, then chains off itself. Make it a full mirror
            # of the row it already points at.
            src = int(refs[0].group(2))
            vals = [f"={fs._col(c)}{src}" for c in cols]
            why = f"mirror row {src}"
        else:
            start = _week_start(sec, today)
            vals = fs.daynum_row_values(start, len(cols))
            why = f"literals, week of {start.isoformat()}"

        have = [fs._cell(grid, dn - 1, c - 1) for c in cols]
        shown = [str(v) for v in
                 (vals if not want_first
                  else [(_week_start(sec, today) + dt.timedelta(days=i)).day
                        for i in range(len(cols))])]
        # The row is only DONE when its FORMULAS are right too, not just the
        # numbers it happens to be showing. A human who types the correct day
        # over ONE cell of a live chain leaves a row that reads perfectly this
        # week and freezes that day — and every day after it — on the next roll
        # ([[project_board-daynum-chain-frozen-drops-days]], 2026-08-09; it
        # happened again mid-repair on 2026-09-02, someone typed `1` into D77
        # while the chain still ran from E77 on). Checking values alone walks
        # straight past that, so compare what is actually IN the cells.
        if have == shown and cells == [str(v) for v in vals]:
            continue
        updates.append({
            "range": f"{fs._col(cols[0])}{dn}:{fs._col(cols[-1])}{dn}",
            "values": [vals],
            "_label": sec["label"], "_why": why,
            "_have": have, "_want": shown})
    return updates


def repair(ws, today: Optional[dt.date] = None, dry_run: bool = True,
           logfn=print) -> dict:
    grid = ws.get_all_values()
    form = ws.get_all_values(value_render_option="FORMULA")
    upd = plan(grid, form, today=today)
    if not upd:
        logfn(f"  {ws.title}: day-number rows already correct — nothing to do")
        return {"tab": ws.title, "updates": 0}
    for u in upd:
        logfn(f"  {ws.title}: {u['range']} ({u['_label']}) "
              f"{u['_have']} -> {u['_want']}  [{u['_why']}]")
    if not dry_run:
        ws.batch_update([{"range": u["range"], "values": u["values"]}
                         for u in upd], value_input_option="USER_ENTERED")
        logfn(f"  {ws.title}: {len(upd)} day-number row(s) rewritten")
    else:
        logfn(f"  {ws.title}: DRY RUN — {len(upd)} row(s) would be rewritten")
    return {"tab": ws.title, "updates": len(upd)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default: dry run)")
    ap.add_argument("--tab", action="append", dest="tabs",
                    help="tab to repair (repeatable; default: both boards)")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing")
    a = ap.parse_args(argv)

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    sh = open_by_key(SHEET_ID)
    total = 0
    for tab in (a.tabs or DEFAULT_TABS):
        total += repair(sh.worksheet(tab), today=today,
                        dry_run=not a.apply)["updates"]
    if total and not a.apply:
        print("\nRe-run with --apply to write, then re-run the fill "
              "(`python -m automations.org_sales_board.run --step daily`).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

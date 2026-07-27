"""Weekly rollover for the Country Sales Board.

Closes the week the board is showing and opens the next one. This is the
DESTRUCTIVE step of the report — it shifts columns, inserts a row and blanks
the day cells — so it snapshots the tab first and refuses to run twice.

Structure verified against the live tab 2026-07-20/21 by running
org_sales_board's own finders against it. What that showed:

  SAME as the ORG board
    • the delta chart is structurally identical — org's `find_delta_tables`
      locates it unchanged (header row 230, this_cols [6,9,12,15,18,21,24],
      This week / Last week / Delta triplets), so `plan_delta_rollover` is
      reused VERBATIM rather than reimplemented
    • leaderboard = live col C + static history to its right -> shift right
    • blank the day cells, advance the day-number anchor

  ABSENT here (4 of the ORG board's 9 steps don't apply)
    • no captainships          (discover_captainships -> 0)
    • no 'X ORG - Current vs Prior Weeks' static history tables (-> 0)
    • no per-campaign history blocks (-> 0)
    • no ORG leaderboard block of org's shape (find_org_block raises)

  NEW here (the ORG board has no equivalent)
    • the day block carries per-rep LAST WEEK'S / PREVIOUS WEEK'S TOTALS in
      cols K and L as STATIC values -> they shift L<-K, K<-J
    • the Current-vs-Prior block anchors into the WE stack by ROW:
          C12 = =C$174                  Sales (Last Week)
          C13 = =AVERAGE(C$174:C$177)   Sales (4 Week AVG)
      Inserting the closed week at row 174 makes Google Sheets rewrite those to
      =C$175 / =AVERAGE(C$175:C$178) — i.e. still pointing at the OLD week. They
      must be re-anchored back afterwards or every percentage on the board
      silently compares against the wrong week.

Order matters: the leaderboard shift, the delta freeze and the K/L shift all
read live values that the daily clear zeroes, so the clear runs LAST. The WE
stack insert shifts every row below it, so it runs after the passes that use
absolute row numbers and the grid is re-read afterwards.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from gspread.utils import rowcol_to_a1

from automations.org_sales_board import rollover as org_ro
from automations.org_sales_board.fill_section import find_daily_section
from automations.country_sales_board import week as wk
from automations.country_sales_board.fill import BLOCK_LABEL

BACKUP_TAB = "Country Sales Board (pre-rollover backup)"
LEADERBOARD_HDR_LABEL = "AT&T FIBER TEAM"     # col A of the leaderboard header


def _cell(grid, r1: int, c1: int) -> str:
    row = grid[r1 - 1] if 0 < r1 <= len(grid) else []
    return str(row[c1 - 1]).strip() if 0 < c1 <= len(row) else ""


def find_leaderboard(grid) -> dict:
    """The weekly leaderboard: its header row (col A == the team label, WE
    labels running right from col C), its data rows, and its last used column.

    Located by label + the presence of WE headers — never by row number."""
    hdr = None
    for r in range(1, len(grid) + 1):
        if _cell(grid, r, 1) == LEADERBOARD_HDR_LABEL and \
                _cell(grid, r, 3).upper().startswith("WE "):
            hdr = r
            break
    if hdr is None:
        raise ValueError(f"no leaderboard header row (col A == "
                         f"{LEADERBOARD_HDR_LABEL!r} with a 'WE …' in col C)")
    last_col = max((c for c in range(3, len(grid[hdr - 1]) + 1)
                    if _cell(grid, hdr, c).upper().startswith("WE ")),
                   default=3)
    # Data rows: the ranked rows below, down to and including the TOTALS row.
    rows, totals = [], None
    r = hdr + 1
    while r <= len(grid):
        a, b = _cell(grid, r, 1), _cell(grid, r, 2)
        if a.upper() == "TOTALS":
            totals = r
            break
        if b:
            rows.append(r)
        r += 1
    if totals is None:
        raise ValueError("no TOTALS row under the leaderboard")
    return {"header_row": hdr, "data_rows": rows, "totals_row": totals,
            "last_col": last_col}


def find_we_stack(grid, totals_row: int) -> dict:
    """The WE history stack directly under the day block's Totals row: one row
    per closed week, most recent first, labelled 'WE M.D' in col A."""
    top = totals_row + 1
    r, rows = top, []
    while r <= len(grid) and org_ro._WE_ROW_RE.match(_cell(grid, r, 1)):
        rows.append(r)
        r += 1
    if not rows:
        raise ValueError(f"no 'WE …' history rows under row {totals_row}")
    return {"top_row": rows[0], "rows": rows}


def board_label(grid) -> str:
    """The week label the board is currently showing (leaderboard col C)."""
    return _cell(grid, find_leaderboard(grid)["header_row"], 3)


def needs_rollover(grid, today: Optional[dt.date] = None) -> tuple[bool, str]:
    """(should_roll, why). TUESDAY rollover, self-healing.

    Rolls when the board is NOT on the week the fill is about to write —
    `week.reporting_sunday`, which lags one day on Monday. So the first run of
    the new reporting week (Tuesday) rolls, every later run that week is a
    no-op, and a MISSED Tuesday just rolls on Wednesday instead. Same system as
    all_campaigns_board / the ORG Copy tab. [[project_all-campaigns-board]]

    Two guards keep a mistimed run from destroying data:
      • MONDAY never rolls — `reporting_sunday` still points at the closing
        week, so Monday's fill (which writes SUNDAY's production) lands in the
        columns it belongs to. Rolling Monday would lose every Sunday.
      • a board whose displayed week HASN'T ENDED is never rolled, even if the
        labels disagree — that means the board is ahead of us, not behind.
    """
    today = today or dt.date.today()
    anchor = find_daily_section(grid, BLOCK_LABEL)
    board_dates = wk.sheet_week(anchor.day_col_by_daynum, today)
    board_sunday = board_dates[-1]
    target = wk.reporting_sunday(today)
    cur = board_label(grid)
    if wk.label_matches(cur, target) or board_sunday == target:
        return False, (f"already on {cur} (reporting week ends "
                       f"{target.isoformat()}) — nothing to roll")
    if board_sunday >= target:
        return False, (f"the board's week ({cur}) hasn't ended yet "
                       f"(ends {board_sunday.isoformat()}, reporting week ends "
                       f"{target.isoformat()}) — refusing to roll mid-week")
    return True, (f"board is on {cur} (ended {board_sunday.isoformat()}); "
                  f"target {wk.we_label(target)}")


def snapshot(sh, ws, *, dry_run: bool, logfn=print) -> str:
    """Copy the tab to a fixed backup tab before touching it. Raises if it
    fails — better to abort than to shift columns with no way back."""
    if dry_run:
        logfn(f"  [dry-run] would snapshot -> {BACKUP_TAB!r}")
        return BACKUP_TAB
    for w in sh.worksheets():
        if w.title == BACKUP_TAB:
            sh.del_worksheet(w)
            break
    sh.duplicate_sheet(source_sheet_id=ws.id, new_sheet_name=BACKUP_TAB)
    logfn(f"  snapshot -> {BACKUP_TAB!r}")
    return BACKUP_TAB


def plan_leaderboard_shift(grid, lb: dict, new_label: str) -> List[dict]:
    """Shift the leaderboard's week columns one to the right and write the new
    week's header into col C.

    Col C holds a live =SUMIF (and =SUM on the TOTALS row); we move its COMPUTED
    value into col D and leave the formula in place, so it recomputes to 0 once
    the day cells are cleared and then fills as the new week lands."""
    updates: List[dict] = []
    first, last = 3, lb["last_col"]
    for r in [lb["header_row"], *lb["data_rows"], lb["totals_row"]]:
        vals = [_cell(grid, r, c) for c in range(first, last + 1)]
        rng = f"{rowcol_to_a1(r, first + 1)}:{rowcol_to_a1(r, last + 1)}"
        updates.append({"range": rng, "values": [vals]})
    updates.append({"range": rowcol_to_a1(lb["header_row"], first),
                    "values": [[new_label]]})
    return updates


def plan_kl_shift(grid, anchor) -> List[dict]:
    """Day block: PREVIOUS WEEK'S TOTALS <- LAST WEEK'S <- RUNNING WEEK TOTALS.

    All three are per-rep; J is a formula, K and L are static, so we move
    COMPUTED values rightwards. Columns are found off the header row by label,
    not by index."""
    hdr = anchor.header_row
    def col_of(label):
        for c in range(1, len(grid[hdr - 1]) + 1):
            if _cell(grid, hdr, c).upper().startswith(label):
                return c
        return None
    j = anchor.running_total_col
    k = col_of("LAST WEEK'S TOTAL")
    l = col_of("PREVIOUS WEEK'S TOTAL")
    if not (k and l):
        return []
    updates = []
    for row in anchor.icd_rows.values():
        # Read BOTH before writing either — L takes K's current value and K
        # takes J's, so writing K first would feed the new K into L.
        old_j, old_k = _cell(grid, row, j), _cell(grid, row, k)
        updates.append({"range": rowcol_to_a1(row, l), "values": [[old_k]]})
        updates.append({"range": rowcol_to_a1(row, k), "values": [[old_j]]})
    return updates


def find_cvp_anchors(formula_grid) -> dict:
    """The Current-vs-Prior rows that point INTO the WE stack by row number.

    Found by their col-B label, then by reading the formula to learn which row
    it anchors on — so a moved block or a renumbered stack is still handled.
    Returns {'last_week': (row, col, formula), 'avg': (...)} for the first data
    column; the same rewrite is applied across the block's day columns."""
    import re
    out: dict = {}
    for r in range(1, len(formula_grid) + 1):
        row = formula_grid[r - 1]
        label = str(row[1]).strip().lower() if len(row) > 1 else ""
        if label.startswith("sales (last week"):
            out["last_week"] = r
        elif label.startswith("sales ( 4 week") or label.startswith("sales (4 week"):
            out["avg"] = r
    return out


def plan_cvp_reanchor(formula_grid, cvp: dict, stack_top: int) -> List[dict]:
    """Re-point the Current-vs-Prior formulas at the NEW top of the WE stack.

    Inserting a row at `stack_top` makes Sheets rewrite `=C$174` -> `=C$175`,
    which keeps them aimed at the week that just got pushed DOWN. We rewrite the
    row numbers back so 'Sales (Last Week)' means the week we just closed and
    the 4-week average covers the newest four."""
    import re
    updates: List[dict] = []
    for key, row in cvp.items():
        if not row:
            continue
        cells = formula_grid[row - 1]
        for c in range(1, len(cells) + 1):
            f = str(cells[c - 1])
            if not f.startswith("="):
                continue
            if key == "last_week":
                new = re.sub(r"(\$?[A-Z]{1,2}\$?)\d+", rf"\g<1>{stack_top}", f)
            else:
                new = re.sub(
                    r"(\$?[A-Z]{1,2}\$?)\d+:(\$?[A-Z]{1,2}\$?)\d+",
                    rf"\g<1>{stack_top}:\g<2>{stack_top + 3}", f)
            if new != f:
                updates.append({"range": rowcol_to_a1(row, c),
                                "values": [[new]]})
    return updates


def plan_daily_clear(anchor) -> List[dict]:
    """Blank every rep's Mon..Sun cells so the formula-driven totals drop to 0."""
    first = min(anchor.day_col_by_daynum.values())
    last = max(anchor.day_col_by_daynum.values())
    rows = sorted(anchor.icd_rows.values())
    rng = (f"{rowcol_to_a1(rows[0], first)}:"
           f"{rowcol_to_a1(rows[-1], last)}")
    blank = [["" for _ in range(first, last + 1)] for _ in rows]
    return [{"range": rng, "values": blank}]


def run_rollover(sh, ws, *, today: Optional[dt.date] = None,
                 dry_run: bool = True, force: bool = False, logfn=print) -> dict:
    """Close the displayed week and open the next one.

    Steps, in the order they must run:
      0  snapshot the tab
      1  leaderboard: shift the week columns right, new label in col C
      2  delta chart: freeze each per-day 'This week' into 'Last week'
         (org_sales_board.plan_delta_rollover, reused verbatim)
      3  day block: PREVIOUS <- LAST <- RUNNING weekly totals per rep
      4  WE stack: insert the closed week at the top, then re-anchor the
         Current-vs-Prior formulas that Sheets just shifted off it
      5  blank the day cells
      6  advance the day-number anchor to the new Monday
    1-3 read live values that 5 zeroes, so 5 runs last. 4 inserts a row and
    moves everything below it, so it runs after the absolute-row passes."""
    from automations.recruiting_report.fill import _retry

    today = today or dt.date.today()
    grid = _retry(ws.get_all_values)
    ok, why = needs_rollover(grid, today)
    logfn(f"  rollover check: {why}")
    if not ok and not force:
        return {"rolled": False, "reason": why}
    if not ok and force:
        logfn("  ⚠ --force: rolling anyway")

    anchor = find_daily_section(grid, BLOCK_LABEL)
    board_dates = wk.sheet_week(anchor.day_col_by_daynum, today)
    closed_sunday = board_dates[-1]
    new_sunday = closed_sunday + dt.timedelta(days=7)
    lb = find_leaderboard(grid)
    stack = find_we_stack(grid, anchor.totals_row)
    summary = {"rolled": True, "closed": wk.we_label(closed_sunday),
               "new_label": wk.we_label(new_sunday), "steps": {}}

    snapshot(sh, ws, dry_run=dry_run, logfn=logfn)

    def push(tag, updates):
        summary["steps"][tag] = len(updates)
        logfn(f"  {tag}: {len(updates)} write(s)")
        if updates and not dry_run:
            ws.batch_update(updates, value_input_option="USER_ENTERED")

    # 1 — leaderboard columns shift right; col C keeps its live =SUMIF.
    push("leaderboard-shift",
         plan_leaderboard_shift(grid, lb, wk.we_label(new_sunday)))

    # 2 — the delta chart. org's finder + planner apply unchanged here.
    delta_updates: List[dict] = []
    for t in org_ro.find_delta_tables(grid):
        delta_updates += org_ro.plan_delta_rollover(ws, t)
    push("delta-freeze", delta_updates)

    # 3 — per-rep weekly-total columns.
    push("weekly-total-shift", plan_kl_shift(grid, anchor))

    # 4 — WE stack insert + Current-vs-Prior re-anchor.
    day_cols = [c for _d, c in sorted(anchor.day_col_by_daynum.items(),
                                      key=lambda kv: kv[1])]
    totals = [_cell(grid, anchor.totals_row, c) for c in day_cols]
    grand = _cell(grid, anchor.totals_row, anchor.running_total_col)
    new_row = [wk.we_label(closed_sunday, pad=False), ""] + totals + [grand]
    logfn(f"  WE stack: insert {new_row[0]!r} at row {stack['top_row']} "
          f"= {totals} (total {grand})")
    if not dry_run:
        # inherit_from_before=False -> take the formatting of the WE row BELOW,
        # not the Totals row above it.
        ws.insert_row(new_row, index=stack["top_row"],
                      value_input_option="USER_ENTERED",
                      inherit_from_before=False)
        fgrid = _retry(lambda: ws.get_all_values(
            value_render_option="FORMULA"))
        cvp = find_cvp_anchors(fgrid)
        push("cvp-reanchor", plan_cvp_reanchor(fgrid, cvp, stack["top_row"]))
        grid = _retry(ws.get_all_values)          # rows below 174 have moved
        anchor = find_daily_section(grid, BLOCK_LABEL)
    else:
        fgrid = _retry(lambda: ws.get_all_values(
            value_render_option="FORMULA"))
        cvp = find_cvp_anchors(fgrid)
        logfn(f"  [dry-run] cvp anchors at rows {cvp} would be re-pointed "
              f"at row {stack['top_row']}")

    # 5 — blank the day cells.
    push("daily-clear", plan_daily_clear(anchor))

    # 6 — advance the day-number row. Write ALL SEVEN numbers, not just the
    #     Monday anchor.
    #
    #     The tab ships this row as a chain — C98 static, then =C98+1, =D98+1, …
    #     — which is correct only inside a single month. Rolling into a week that
    #     CROSSES one produces 27,28,29,30,31,32,33 instead of 27,28,29,30,31,1,2
    #     (reproduced live on the sandbox 2026-07-27 rolling WE 07.26 -> WE 08.02).
    #     Those numbers are what `week.sheet_week` reads the board's week back
    #     out of, so the very next day's fill would raise "day numbers don't
    #     match any Mon-Sun week" and the report would stop until someone fixed
    #     the row by hand — every month, on the roll that crosses.
    #     Replacing the chain with the seven real day-of-month values is the
    #     minimal fix: same displayed numbers on a normal week, correct ones on a
    #     wrapping week, and nothing else on the tab reads these cells by formula.
    new_monday = new_sunday - dt.timedelta(days=6)
    day_cols_sorted = [c for _d, c in sorted(anchor.day_col_by_daynum.items(),
                                             key=lambda kv: kv[1])]
    new_daynums = [(new_monday + dt.timedelta(days=i)).day for i in range(7)]
    push("day-anchor",
         [{"range": (f"{rowcol_to_a1(anchor.daynum_row, day_cols_sorted[0])}:"
                     f"{rowcol_to_a1(anchor.daynum_row, day_cols_sorted[-1])}"),
           "values": [new_daynums]}])
    logfn(f"  day numbers -> {new_daynums} "
          f"(week of {new_monday.isoformat()})")

    logfn(f"  ✅ rolled {summary['closed']} -> {summary['new_label']}"
          f"{' (dry-run, nothing written)' if dry_run else ''}")
    return summary

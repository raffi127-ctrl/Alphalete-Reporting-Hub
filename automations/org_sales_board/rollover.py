"""Weekly TUESDAY rollover for the Alphalete ORG Sales Board.

Run FIRST thing TUESDAY, BEFORE the new week's daily fill (Megan 2026-06-03).
NOT Monday: Monday is when the VAs enter the prior week's SUNDAY production, so
the just-finished week isn't complete until Monday's entry is done. Running the
rollover Tuesday freezes a COMPLETE week; running it Monday would freeze a week
still missing Sunday. (The week math — new_week_ending — resolves the same
Mon–Sun week for any weekday, so only the run-DAY matters, not the code.)
Three mechanics:

1. LEADERBOARDS (the ALPHALETE ORG weekly-history block + the 10 captainship
   strips): col C = the live current week (a =SUM formula for ORG, a =SUMIF
   formula for captainships); cols D→ = frozen static history (WE dates,
   newest→oldest left→right). Rollover GROWS by one column (Megan 2026-06-01,
   keep full history): each data row's values shift one column RIGHT
   (C-value→D, D→E, …) freezing the completed week into D; col C keeps its
   formula in BOTH cases — the daily-clear (step 4) zeroes the source the
   captainship =SUMIF reads, so it drops to 0 for the new week WITHOUT the
   rollover overwriting the formula with a literal (Eve 2026-06-26). The
   header row shifts the same way and the new col-C header becomes the new
   week-ending date. (Captainship C headers are =C24, so only the ORG C24 is
   re-dated — the rest follow.)

2. DELTA tables (per-captainship, "this wk / last wk / Delta"): freeze each
   "this week" cell's VALUE into its adjacent "last week" cell. No shifting —
   the table only holds 2 weeks. "this week" cells are formulas that
   auto-show the new week once the daily tables refill.

3. (later) the per-captain ORG-vs-prior summary history rows.

WORKSHEET-SCOPED writes only ([[reference_org_board_sandbox_scoping]]). Preview
with dry_run=True first ([[feedback_preview_marcellus]]).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


def a1col(c: int) -> str:          # 1-based col -> letter(s)
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def we_label(week_ending: dt.date) -> str:
    """'WE MM.DD' matching the sheet's header format (zero-padded)."""
    return f"WE {week_ending.month:02d}.{week_ending.day:02d}"


def new_week_ending(today: dt.date) -> dt.date:
    """The Sunday that ENDS the week containing `today` (Mon-anchored)."""
    return today + dt.timedelta(days=6 - today.weekday())


def _cell(grid, r, c):  # 0-based
    return (grid[r][c] if r < len(grid) and c < len(grid[r]) else "").strip()


@dataclass
class LeaderboardBlock:
    title: str
    header_row: int                       # 1-based
    data_rows: List[int] = field(default_factory=list)  # rows w/ a col-C value
    first_col: int = 3                    # col C
    last_col: int = 16                    # last WE col (P)
    c_keeps_formula: bool = True          # ORG=True; captainship=False
    rewrite_c_header: bool = True         # ORG=True; captainship C hdr is =C24


def find_org_block(grid: List[List[str]]) -> LeaderboardBlock:
    """The ALPHALETE ORG weekly-history block. All columns 1-based."""
    n = len(grid)
    hr = next(i for i in range(n)
              if _cell(grid, i, 0).upper().startswith("ALPHALETE ORG"))
    # Scan the FULL header row — the history is ~2 years wide (C..DC), so a
    # capped range would mis-detect the last column and overwrite real weeks.
    last_col = max((c + 1 for c in range(2, len(grid[hr])) if _cell(grid, hr, c)),
                   default=16)                                   # 1-based
    rows = []
    for i in range(hr + 1, n):
        if _cell(grid, i, 2).lower() == "monday":               # daily section
            break
        if _cell(grid, i, 2):
            rows.append(i + 1)
        elif rows and i + 1 - rows[-1] > 1:
            break
    return LeaderboardBlock(title="ALPHALETE ORG", header_row=hr + 1,
                            data_rows=rows, first_col=3, last_col=last_col,
                            c_keeps_formula=True, rewrite_c_header=True)


def plan_leaderboard_rollover(ws, block: LeaderboardBlock, new_label: str):
    """Build the shift-right writes (grow by one col). All cols 1-based.
    Reads VALUES so frozen cells become static. For data rows col C is left
    untouched (keeps its formula, ORG) or zeroed (captainships); D..last+1
    receive old C..last. Header: new col-C label + the old headers shifted."""
    c0, c1 = block.first_col, block.last_col       # C .. last WE col (1-based)
    width = c1 - c0 + 1
    Cl, Dl, ANl = a1col(c0), a1col(c0 + 1), a1col(c1 + 1)
    updates = []

    # --- header row ---
    hdr = (ws.get(f"{Cl}{block.header_row}:{a1col(c1)}{block.header_row}",
                  value_render_option="UNFORMATTED_VALUE") or [[]])[0]
    hdr = (list(hdr) + [""] * width)[:width]       # old C..last
    if block.rewrite_c_header:
        updates.append({"range": f"{Cl}{block.header_row}:{ANl}{block.header_row}",
                        "values": [[new_label] + hdr]})         # C..AN
    else:                                          # captainship C hdr is =C24
        updates.append({"range": f"{Dl}{block.header_row}:{ANl}{block.header_row}",
                        "values": [hdr]})                        # D..AN = old C..last

    # --- data rows: shift old C..last -> D..last+1 ---
    rng = f"{Cl}{block.data_rows[0]}:{a1col(c1)}{block.data_rows[-1]}"
    vals = ws.get(rng, value_render_option="UNFORMATTED_VALUE")
    rowmap = {block.data_rows[0] + i: (list(r) + [""] * width)[:width]
              for i, r in enumerate(vals)}
    preview = []
    for row in block.data_rows:
        cur = rowmap.get(row, [""] * width)        # old C..last
        updates.append({"range": f"{Dl}{row}:{ANl}{row}", "values": [cur]})
        if not block.c_keeps_formula:
            updates.append({"range": f"{Cl}{row}", "values": [[0]]})
        if len(preview) < 5:
            preview.append((row, cur[0], cur[:4]))
    return updates, {"new_label": new_label, "rows": len(block.data_rows),
                     "grow_into": ANl, "sample": preview}


def plan_captainship_leaderboard_rollover(ws, header_row, data_rows, last_col,
                                          org_header_row, org_last_col):
    """Roll a captainship leaderboard. Mirrors the ORG data shift (old C..last
    VALUES -> D..last+1, freezing the just-finished week into D) but:
      • col-C is LEFT INTACT — it holds the live `=SUMIF` this-week total. The
        daily-clear (step 4) blanks the daily table that =SUMIF sums, so it
        reads 0 for the new week ON ITS OWN. Writing a literal 0 here would
        destroy the formula (Eve 2026-06-26 — the just-finished week is already
        frozen into D from col C's VALUE, read below before any write);
      • col-C HEADER is left alone (it's `=C24`, auto-follows the ORG);
      • the static D..last HEADERS are replaced by the (already-rolled) ORG
        header row D..end, so every leaderboard tracks identical week columns.
    Returns (updates, info). Read-only until applied."""
    c0, c1 = 3, last_col
    width = c1 - c0 + 1
    Cl, Dl, ANl = a1col(c0), a1col(c0 + 1), a1col(c1 + 1)
    updates = []
    # Headers D..(last+1) = ORG header row D..(org_last+1) — same week set.
    org_hdr = (ws.get(f"{a1col(4)}{org_header_row}:{a1col(org_last_col + 1)}{org_header_row}",
                      value_render_option="UNFORMATTED_VALUE") or [[]])[0]
    org_hdr = (list(org_hdr) + [""] * width)[:width]
    updates.append({"range": f"{Dl}{header_row}:{ANl}{header_row}",
                    "values": [org_hdr]})
    # Data rows: shift old C..last -> D..last+1. Col C's VALUE (the =SUMIF
    # result for the just-finished week) is READ here via UNFORMATTED_VALUE and
    # frozen into D BEFORE any write, so the week is preserved. Col C itself is
    # NOT written — its =SUMIF stays live and self-zeroes when step 4 clears the
    # daily table it sums (no literal-0 overwrite of the formula).
    rng = f"{Cl}{data_rows[0]}:{a1col(c1)}{data_rows[-1]}"
    vals = ws.get(rng, value_render_option="UNFORMATTED_VALUE")
    rowmap = {data_rows[0] + i: (list(r) + [""] * width)[:width]
              for i, r in enumerate(vals)}
    for row in data_rows:
        cur = rowmap.get(row, [""] * width)
        updates.append({"range": f"{Dl}{row}:{ANl}{row}", "values": [cur]})
    return updates, {"rows": len(data_rows), "grow_into": ANl}


DAILY_SECTION_LABELS = [
    "Retail NL", "ATT Fiber Team", "Retail JE", "ATT NDS Team", "B2B",
    "BOX", "Frontier", "Retail Internet",
]

# Weekday name -> Python weekday() index. A daily section's week starts on the
# weekday named in its first day column: Monday for most, SUNDAY for Frontier —
# which is why Frontier carries its own static date anchor (see step 5/5).
_WD_INDEX = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


def week_label_of(grid) -> str:
    """The week a board tab is currently ON — its ORG-leaderboard col-C header
    ('WE 07.19'). Works on either tab. '' if the block can't be found."""
    try:
        ob = find_org_block(grid)
        return _cell(grid, ob.header_row - 1, ob.first_col - 1).strip()
    except Exception:  # noqa: BLE001
        return ""


def target_week_label(today=None) -> str:
    """The week the board SHOULD be on right now — the label of the REPORTING
    week's Sunday (week.reporting_sunday), i.e. the week the daily fill is about
    to write into.

    NOT new_week_ending(today), which is the calendar week and rolls a day early.
    The board's reporting week does not advance until TUESDAY: on MONDAY,
    reporting_sunday is still the CLOSING Sunday, because Monday's fill exists to
    write SUNDAY's production into the week that just ended (JE/Frontier post a day
    behind). Rolling on Monday would advance the columns out from under that fill —
    day-12 columns would no longer exist and Sunday would be lost from the frozen
    history, every week. Anchoring to the reporting week keeps the board on exactly
    the week the fill targets."""
    import datetime as _dt
    from automations.org_sales_board import week as _wk
    return we_label(_wk.reporting_sunday(today or _dt.date.today()))


def needs_rollover(cS, today=None, vS=None) -> tuple:
    """Should the COPY roll? True when the copy is NOT on the week the fill is
    about to write (target_week_label). Fires on the first run of a Tuesday and is
    a no-op every other run.

    Self-healing by construction: the target stays fixed all week, so if Tuesday's
    run is missed entirely, Wednesday's rolls instead and its fill still backfills
    every completed day. That is the whole point — the rollover used to be a MANUAL
    step, and when a human forgot it (2026-07-14) the copy sat a full week behind
    the VA: the fill had no columns for the new week, a week of data silently never
    landed, and the board email was gated for days.

    `vS` (the VA grid) is optional and used ONLY as a cross-check signal — if the
    VA is on a different week than we computed, something is off and the caller
    should say so rather than silently diverge.

    Returns (needed, target_label, copy_label, va_label)."""
    tgt = target_week_label(today)
    cp = week_label_of(cS)
    va = week_label_of(vS) if vS is not None else ""
    return (bool(cp and tgt and cp != tgt), tgt, cp, va)


BACKUP_TAB = "backup_pre_rollover"


def _snapshot_pre_rollover(ws, grid, dry_run: bool = False, logfn=print) -> None:
    """Freeze the tab's CURRENT state into a fixed backup tab BEFORE the rollover
    mutates anything — a static, values-only safety net so a bad roll is always
    recoverable.

      • ONE fixed tab (BACKUP_TAB), OVERWRITTEN every week — never a new tab per
        run. Created if it doesn't exist.
      • STATIC VALUES, never formulas: `grid` is get_all_values() (FORMATTED —
        formulas already resolved to their shown value), written with
        value_input_option='RAW' so a cell that displayed '-58%' (or even a
        literal '=…') is stored as text, never re-evaluated into a live formula.
      • FIRST + MUST SUCCEED: any failure raises, so run_rollover aborts BEFORE
        its first write. An un-rolled board with no backup beats a rolled board
        with no backup.
      • OUT of the bot's radar: the tab name matches neither SANDBOX_TAB nor
        PROD_TAB, and nothing in the module enumerates worksheets (every access
        is by explicit name), so discover_captainships / the daily fill /
        compare.py / the 3d product-summary step never read or write it.

    dry_run: log what WOULD be snapshotted, write nothing."""
    import datetime as _dt
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = len(grid)
    cols = max((len(r) for r in grid), default=1)
    if dry_run:
        logfn(f"  0/5 snapshot: WOULD freeze {rows}x{cols} of {ws.title!r} into "
              f"{BACKUP_TAB!r} (static values, RAW) @ {stamp} — dry-run, skipped")
        return
    try:
        sh = ws.spreadsheet
        try:
            bws = sh.worksheet(BACKUP_TAB)
        except Exception:                         # tab doesn't exist yet — create
            bws = sh.add_worksheet(title=BACKUP_TAB, rows=max(rows, 1),
                                   cols=max(cols, 1))
            logfn(f"  0/5 snapshot: created backup tab {BACKUP_TAB!r}")
        # Exact-size the tab so a board that SHRANK leaves no stale trailing
        # rows/cols from a previous, wider snapshot.
        bws.resize(rows=max(rows, 1), cols=max(cols, 1))
        rect = [row + [""] * (cols - len(row)) for row in grid]   # rectangular
        # Named args: gspread 6 swapped update()'s positional order to
        # (values, range_name); be explicit so the call is unambiguous + warning-
        # free. RAW so nothing is re-parsed into a live formula.
        bws.update(range_name="A1", values=rect, value_input_option="RAW")
    except Exception as e:  # noqa: BLE001 — abort the roll; never swallow
        raise RuntimeError(
            f"pre-rollover snapshot to {BACKUP_TAB!r} FAILED "
            f"({type(e).__name__}: {e}) — NOT rolling (an un-rolled board beats a "
            f"rolled board with no backup)") from e
    logfn(f"  0/5 snapshot: froze {rows}x{cols} of {ws.title!r} into "
          f"{BACKUP_TAB!r} (static values) @ {stamp}")


def run_rollover(ws, today=None, dry_run: bool = False, logfn=print) -> dict:
    """The whole TUESDAY rollover in order — run BEFORE the new week's daily
    fill, AFTER a fresh pull has finalized the just-finished week:

      1. ORG leaderboard      — shift right, new col-C week header, freeze col C.
      2. 10 captainship leaderboards — same shift (headers copied from the rolled
         ORG so all strips track identical weeks).
      3. 12 delta tables      — freeze each 'this week' value into 'last week'.
      4. daily charts cleared — every Mon-Sun day cell blanked, so the
         formula-driven current cells (leaderboard col C, delta 'this week')
         drop to 0 for the fresh week.

    WORKSHEET-SCOPED. Steps 1-3 must run before 4 (they read the live values
    that step 4 zeroes). Step 2 re-reads the grid after step 1 so it copies the
    ALREADY-rolled ORG headers."""
    import datetime as _dt
    from automations.org_sales_board import captainship as cap
    today = today or _dt.date.today()
    if today.weekday() != 1:   # 1 == Tuesday
        logfn(f"  ℹ rollover running on {today:%A} {today.isoformat()} (not the "
              f"historical Tuesday slot). Expected when it's VA-driven — the copy "
              f"follows whenever the VA rolls. The closing week is frozen from the "
              f"copy's CURRENT daily grid, so it must be filled first "
              f"(auto_rollover does this); a day-behind source missing its Sunday "
              f"would otherwise freeze short.")
    # Target the REPORTING week (the week the fill writes), NOT the calendar week —
    # new_week_ending() rolls a day early and on a MONDAY would advance the board
    # out from under the fill that is about to write Sunday. See target_week_label.
    new_label = target_week_label(today)
    logfn(f"=== ORG board rollover — new week {new_label} "
          f"(dry_run={dry_run}) ===")
    summary = {"new_label": new_label, "captainships": 0, "delta_tables": 0,
               "org_history_tables": 0, "cleared_ranges": 0}

    grid = ws.get_all_values()
    org = find_org_block(grid)
    # Idempotency: if the leaderboard's col-C header is ALREADY this week's WE
    # label, the rollover ran already this week — skip (re-running would double-
    # shift the history). Lets the Tuesday daily run call this safely every time.
    if _cell(grid, org.header_row - 1, org.first_col - 1).strip() == new_label:
        logfn(f"  rollover already done this week (col C = {new_label!r}) — skip")
        summary["skipped"] = True
        return summary
    # SNAPSHOT FIRST — freeze the pre-rollover state into the fixed backup tab
    # before ANY write. Placed AFTER the idempotency skip so a no-op re-run never
    # clobbers a good backup with post-rollover state; still before the first
    # mutation below. Raises on failure (aborting the roll), so `grid` (the
    # pre-rollover values already read for the idempotency check) is the exact
    # snapshotted state.
    _snapshot_pre_rollover(ws, grid, dry_run=dry_run, logfn=logfn)
    summary["backup_tab"] = BACKUP_TAB
    upd, _ = plan_leaderboard_rollover(ws, org, new_label)
    if not dry_run:
        ws.batch_update(upd, value_input_option="USER_ENTERED")
    logfn(f"  1/4 ORG leaderboard frozen (hdr {org.header_row}); "
          f"new col {new_label}")

    grid = ws.get_all_values()                 # ORG headers changed
    org = find_org_block(grid)
    # Roll EVERY leaderboard box, not just the first. Fiber captains carry two
    # stacked boxes (📶 New Internet + 🛜 All Units); find_captainship (one box)
    # left the All Units box un-shifted, desyncing its weekly history from the
    # NI box + the ORG week after week (Eve 2026-06-26). discover_captainships
    # replaces the hardcoded CAPTAIN_NAMES list, and find_captainship_boxes
    # iterates both boxes — the same pair the daily fill writes.
    for title, _tkey in cap.discover_captainships(grid):
        try:
            boxes = cap.find_captainship_boxes(grid, title)
        except Exception as e:
            logfn(f"      ⚠ captainship {title} not found: {e}")
            continue
        for _variant, a in boxes:
            hdr_row = a.leaderboard[0][0] - 2
            lb_rows = [r for r, _ in a.leaderboard]
            last_col = max((c + 1 for c in range(2, len(grid[hdr_row - 1]))
                            if (grid[hdr_row - 1][c] or "").strip()), default=16)
            upd, _ = plan_captainship_leaderboard_rollover(
                ws, hdr_row, lb_rows, last_col, org.header_row, org.last_col)
            if not dry_run:
                ws.batch_update(upd, value_input_option="USER_ENTERED")
            summary["captainships"] += 1
    logfn(f"  2/4 {summary['captainships']} captainship leaderboard box(es) frozen")

    tables = find_delta_tables(grid)
    for t in tables:
        upd = plan_delta_rollover(ws, t)
        if upd and not dry_run:
            ws.batch_update(upd, value_input_option="USER_ENTERED")
    summary["delta_tables"] = len(tables)
    logfn(f"  3/4 {len(tables)} delta tables frozen (this week -> last week)")

    # 3b. 'X ORG - Current vs Prior Weeks' summary tables (CARLOS/COLTEN/BEN):
    # shift the static 4-week history down + seed Last Week from this week.
    # MUST run before the daily clear (their 'Sales - This Week' is a live
    # SUMIF over the daily area). Feeds the 4-Week AVG. (Megan 2026-06-03.)
    org_tables = find_org_history_tables(grid)
    for t in org_tables:
        upd = plan_org_history_rollover(ws, t)
        if upd and not dry_run:
            ws.batch_update(upd, value_input_option="USER_ENTERED")
    summary["org_history_tables"] = len(org_tables)
    logfn(f"  3b/5 {len(org_tables)} ORG history table(s) shifted down "
          f"(this wk → Last Week → Prior → 2 Weeks → 3 Weeks)")

    # 3c. Per-campaign history blocks (Retail NL, ATT Fiber, Retail JE, ATT NDS,
    # B2B, BOX, Frontier, Retail Internet): same down-shift, but seeded from each
    # section's 'Totals' (=SUM current week) row instead of a 'Sales - This Week'
    # SUMIF — the X-ORG finder above missed them (Eve 2026-06-26). MUST also run
    # before the daily clear: the 'Totals' row is a live =SUM over the daily
    # cells step 4 zeroes, so its value has to be frozen first. The Totals row is
    # only READ — its formula is never written (plan_org_history_rollover writes
    # only Last/Prior/2wk/3wk, all static data cells).
    camp_tables = find_campaign_history_tables(grid)
    for t in camp_tables:
        upd = plan_org_history_rollover(ws, t)
        if upd and not dry_run:
            ws.batch_update(upd, value_input_option="USER_ENTERED")
    summary["campaign_history_tables"] = len(camp_tables)
    logfn(f"  3c/5 {len(camp_tables)} per-campaign history block(s) shifted down "
          f"(Totals → Last Week → Prior → 2 Weeks → 3 Weeks)")

    # 3d. Per-captainship Product-Summary WE-stack week-logs: insert the just-
    # closed week at the TOP of each stack (static values) + re-anchor the two
    # summary formulas ('Sales (Last Week)' → new top row, 'Sales (4 Week AVG)'
    # → new top 4 rows). MUST run BEFORE the daily clear — each block's 'Totals'
    # is a live =SUM whose value has to be frozen first. Idempotent by label: a
    # block whose top already reads this week's 'WE m.d' row is skipped, so a
    # re-run never double-shifts (the same self-heal guard the leaderboards use).
    #
    # Re-automated 2026-07-16 (Eve): this was made MANUAL 2026-06-30 to avoid an
    # unattended double-shift, but the hand-maintained block drifts — it is how
    # the KHALIL / ATT-NDS 'Sales (Last Week)' Grand-Total formula picked up a
    # stray +J1346 (found 2026-07-16). The double-shift fear is moot now that
    # run_rollover is idempotent AND apply_product_summary_rollover skips any
    # block already carrying this week's WE row.
    ps = apply_product_summary_rollover(ws, today=today, dry_run=dry_run,
                                        logfn=logfn)
    summary["product_summaries"] = len(ps)
    logfn(f"  3d/5 {len(ps)} captainship product-summary WE-stack(s) processed "
          f"(new WE row at top + summary formulas re-anchored)")
    # The real row inserts above shift every row BELOW the first insert, so the
    # row numbers in `grid` are now stale — re-read before the daily clear and
    # the date-anchor step, both of which locate their rows by this grid.
    grid = ws.get_all_values()

    ranges = plan_daily_clear(ws, grid)
    if not dry_run:
        ws.batch_clear(ranges)
    summary["cleared_ranges"] = len(ranges)
    logfn(f"  4/5 daily charts cleared ({len(ranges)} ranges) — new week blank")

    # 5/5 Advance the daily-section week dates. Most daily sections' day-of-month
    # rows derive from ONE static anchor cell (the first/Retail NL section's
    # Monday); the others reference it (=C81…), so setting that cell rolls them
    # all. Without this the daily fill skips the new week's pulls ("not on the
    # sheet's current week → 0 cells") and the whole current week stays blank
    # (found 2026-06-02).
    #
    # But there is MORE THAN ONE static anchor: a section whose week does not start
    # on Monday can't reference the Monday anchor and carries its own. Frontier runs
    # SUNDAY–Saturday (automated 2026-07-07, after this step was written) and has a
    # second static anchor. The old code set the first static anchor it found and
    # `break`ed, so Frontier never advanced — it sat a full week behind the rest of
    # the board, its daily fill silently wrote nothing, and the VA-compare lit up
    # (found 2026-07-14). So: advance EVERY static anchor, and derive each section's
    # start date from ITS OWN first weekday header rather than assuming Monday.
    from automations.org_sales_board import fill_section as fs
    from automations.org_sales_board import week as _wk
    new_monday = _wk.reporting_sunday(today) - dt.timedelta(days=6)   # reporting wk
    anchors = []
    for label in DAILY_SECTION_LABELS:
        try:
            a = fs.find_daily_section(grid, label)
        except Exception:
            continue
        first_col = min(a.day_col_by_daynum.values())
        cell = f"{a1col(first_col)}{a.daynum_row}"
        try:
            fcur = ws.get(cell, value_render_option="FORMULA")
            cur = (fcur[0][0] if fcur and fcur[0] else "")
        except Exception:
            cur = ""
        if str(cur).startswith("="):     # derives from another section's anchor
            continue
        # This section's week starts on the weekday named in its first day column
        # (header row sits directly above the day-number row) — Monday for most,
        # Sunday for Frontier. Sunday-first means the Sunday BEFORE the new Monday.
        hdr = grid[a.daynum_row - 2] if 1 < a.daynum_row <= len(grid) + 1 else []
        wd = (hdr[first_col - 1] if first_col - 1 < len(hdr) else "").strip().lower()
        idx = _WD_INDEX.get(wd)
        start = (new_monday - dt.timedelta(days=(7 - idx) % 7)
                 if idx is not None else new_monday)
        if not dry_run:
            ws.update(cell, [[start.day]], value_input_option="USER_ENTERED")
        anchors.append((label, cell, start))
    if anchors:
        summary["daily_anchors"] = [(c, s.isoformat()) for _l, c, s in anchors]
        summary["daily_anchor"] = anchors[0][1]        # back-compat: master anchor
        for label, cell, start in anchors:
            logfn(f"  5/5 daily date anchor {cell} → {start.day} "
                  f"({label}, week of {start.isoformat()})")
    else:
        logfn("  ⚠ 5/5 no static daily date anchor found — daily dates may not "
              "have advanced (daily fill could skip the new week)")
    logfn("=== rollover done ===")
    return summary


def plan_daily_clear(ws, grid) -> List[str]:
    """Blank ranges for the daily-chart day cells (Mon-Sun) of every daily
    section + every captainship daily table. Deleting them (Megan: "leave
    blank") makes the formula-driven current-week cells — leaderboard col C
    (=SUMIF of a section's running totals) and each delta table's "this week"
    (=SUMIF of a captainship's daily) — read 0 for the fresh week. Running-total
    formulas (col J) are left intact; clearing the day cells zeroes them. Never
    touches the frozen history columns."""
    from automations.org_sales_board import fill_section as fs
    from automations.org_sales_board import captainship as cap
    ranges: List[str] = []
    for label in DAILY_SECTION_LABELS:
        try:
            a = fs.find_daily_section(grid, label)
        except Exception:
            continue
        rows = list(a.icd_rows.values())
        cols = sorted(a.day_col_by_daynum.values())
        if rows and cols:
            ranges.append(f"{a1col(cols[0])}{min(rows)}:"
                          f"{a1col(cols[-1])}{max(rows)}")
    # Auto-discovered from the board — same source the fill uses — so adding/
    # removing a captainship needs no edit here either. Both boxes of a fiber
    # captain are cleared (find_captainship_boxes), so the 🛜 All Units daily
    # table is blanked too (the NI box was the only one cleared before).
    for title, _tkey in cap.discover_captainships(grid):
        try:
            boxes = cap.find_captainship_boxes(grid, title)
        except Exception:
            continue
        for _variant, a in boxes:
            if a.daily and a.day_cols:
                d_rows = [r for r, _ in a.daily]
                ranges.append(f"{a1col(a.day_cols[0])}{min(d_rows)}:"
                              f"{a1col(a.day_cols[-1])}{max(d_rows)}")
    return ranges


def find_delta_tables(grid: List[List[str]]) -> List[dict]:
    """Locate every per-captainship DELTA table (the 'this wk / last wk / Delta'
    blocks). A header row has 'Total this week' in col C; the per-day columns run
    as strict THIS WEEK / LAST WEEK / DELTA triplets.
    Data rows run until col B blanks out or hits the 'Captainship' total row.

    A 'This week' header only counts as a real this-week column when 'Delta'
    sits two columns to its right — the triplet signature. The label alone is
    NOT enough: the Sunday 'Last week' header is typed as 'This week' on the
    JAIRO / RAF SPECIAL / LUIS tables (both tabs), so a label-only scan picked
    up col Y — the FROZEN Sunday last-week value — as a live this-week column.
    That did two bad things (2026-07-20):
      • the compare gated col Y as a current-week cell. The copy and the VA
        freeze their history at different moments, so it always differs there —
        the 9am VA-compare failed with 8 phantom 'va_ahead's on data that is
        report-only by design.
      • plan_delta_rollover writes each this-col into col+1, so it would have
        written Y into Z — clobbering the live '=Iferror((X-Y)/Y,0)' Delta
        formula with a static number on the next Tuesday rollover.
    The triplet check keys on structure, so a mistyped header can't move it."""
    out = []
    n = len(grid)
    for i in range(n):
        if _cell(grid, i, 2) != "Total this week":
            continue
        this_cols = [c + 1 for c in range(len(grid[i]))
                     if _cell(grid, i, c) == "This week"
                     and _cell(grid, i, c + 2) == "Delta"]   # per-day triplets
        rows = []
        j = i + 1
        while j < n:
            b = _cell(grid, j, 1)
            if not b or b.lower().startswith("captainship") \
                    or _cell(grid, j, 2) == "Total this week":
                break
            rows.append(j + 1)
            j += 1
        out.append({"header_row": i + 1, "data_rows": rows,
                    "this_cols": this_cols})
    return out


def plan_delta_rollover(ws, table: dict):
    """Freeze each per-day 'This week' VALUE into its 'Last week' cell (the
    next column). The Total/Delta columns are formulas and auto-recompute, so
    they're left alone. Read-only until applied."""
    this_cols = table["this_cols"]
    rows = table["data_rows"]
    if not this_cols or not rows:
        return []
    c0, c1 = min(this_cols), max(this_cols)        # F .. X
    rng = f"{a1col(c0)}{rows[0]}:{a1col(c1)}{rows[-1]}"
    block = ws.get(rng, value_render_option="UNFORMATTED_VALUE")
    updates = []
    for idx, row in enumerate(rows):
        vals = block[idx] if idx < len(block) else []
        for tc in this_cols:
            v = vals[tc - c0] if (tc - c0) < len(vals) else ""
            updates.append({"range": f"{a1col(tc + 1)}{row}",
                            "values": [[v if v != "" else 0]]})
    return updates


_ORG_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"}


def find_org_history_tables(grid: List[List[str]]) -> List[dict]:
    """Find each 'X ORG - Current vs Prior Weeks' summary table that carries a
    STATIC 4-week history — Last Week / Prior Week / 2 Weeks Prior / 3 Weeks
    Prior — plus a 'Sales - This Week' row (CARLOS / COLTEN / BEN). RAF ORG is
    formula-driven (its 'Sales (Last Week)' is a live =SUM over the daily
    sections, with no static history rows), so it lacks these labels and is
    skipped. These four rows are the VAs' manual weekly shift-down that feeds
    the 4-Week AVG (=AVERAGE of the four); the Tuesday rollover replicates it.
    Returns dicts with each row's 1-based number + the column span (first
    weekday col .. Grand-Total col)."""
    tables = []
    for i, row in enumerate(grid):
        if not any("ORG - Current vs Prior" in (c or "") for c in row[:6]):
            continue
        hdr = i + 1
        rows, dayrow = {}, None
        for r in range(hdr, min(hdr + 15, len(grid) + 1)):
            lab = (_cell(grid, r - 1, 0) or _cell(grid, r - 1, 1)).strip().lower()
            if lab == "sales - this week":
                rows["this"] = r
            elif lab == "last week":
                rows["lw"] = r
            elif lab == "prior week":
                rows["pw"] = r
            elif lab == "2 weeks prior":
                rows["2wp"] = r
            elif lab == "3 weeks prior":
                rows["3wp"] = r
            if dayrow is None and sum(
                    1 for c in grid[r - 1]
                    if (c or "").strip().lower() in _ORG_WEEKDAYS) >= 4:
                dayrow = r
        if not all(k in rows for k in ("this", "lw", "pw", "2wp", "3wp")):
            continue
        if dayrow is None:
            continue
        daycols = [c + 1 for c, v in enumerate(grid[dayrow - 1])
                   if (v or "").strip().lower() in _ORG_WEEKDAYS]
        tables.append({"header_row": hdr, "c0": min(daycols),
                       "cN": max(daycols) + 1, **rows})   # cN = Grand-Total col
    return tables


def find_campaign_history_tables(grid: List[List[str]]) -> List[dict]:
    """Per-campaign Last/Prior/2wk/3wk history blocks — one under each daily
    section (Retail NL, ATT Fiber, Retail JE, ATT NDS, B2B, BOX, Frontier,
    Retail Internet). Each is four consecutive label rows ('Last Week' / 'Prior
    Week' / '2 Weeks Prior' / '3 Weeks Prior') sitting directly beneath the
    section's 'Totals' (=SUM current-week) row. Unlike the X-ORG blocks (seeded
    from a 'Sales - This Week' SUMIF, handled by find_org_history_tables), these
    seed Last Week from that 'Totals' row — so the returned dict's "this" key
    points at the Totals row and the SAME plan_org_history_rollover shifts them.

    The 'Totals' row is the signal that distinguishes a campaign block from an
    X-ORG block: a campaign block's first non-blank row above 'Last Week' is
    'Totals'; an X-ORG block's is a 'Sales (...)' row, so it's skipped here.
    Returns dicts shaped like find_org_history_tables (this/lw/pw/2wp/3wp +
    c0/cN). [No hardcoded rows — found by their col-A/B labels.]"""
    seq = ("last week", "prior week", "2 weeks prior", "3 weeks prior")
    out: List[dict] = []
    n = len(grid)
    for i in range(n):
        if (_cell(grid, i, 0) or _cell(grid, i, 1)).lower() != "last week":
            continue
        if i + 3 >= n or not all(
                (_cell(grid, i + k, 0) or _cell(grid, i + k, 1)).lower() == seq[k]
                for k in range(4)):
            continue
        # First NON-BLANK row above 'Last Week' must be the section 'Totals'
        # (=SUM). If it's a 'Sales (...)' row instead, this is an X-ORG block —
        # leave it to find_org_history_tables.
        tot = None
        for r in range(i - 1, max(i - 4, -1), -1):
            if not _cell(grid, r, 0) and not _cell(grid, r, 1):
                continue                       # blank spacer — keep scanning up
            if _cell(grid, r, 0).lower() in ("totals", "total"):
                tot = r
            break                              # first non-blank row decides
        if tot is None:
            continue
        # Value-column span = every column carrying a value across the Totals +
        # the 4 history rows (robust to a 0 that displays blank in one row). This
        # FULL span (incl. the frozen 'LAST WEEK'/'PREVIOUS WEEK' total columns)
        # is what plan_org_history_rollover shifts, so keep c0/cN wide.
        scan = [tot, i, i + 1, i + 2, i + 3]
        maxc = max(len(grid[r]) for r in scan)
        daycols = [c + 1 for c in range(2, maxc)
                   if any(_cell(grid, r, c) for r in scan)]
        if not daycols:
            continue
        # LIVE this-week span (Monday .. RUNNING-WEEK-TOTAL) for the go-live GATE:
        # the frozen 'LAST WEEK'S TOTALS' / 'PREVIOUS WEEK'S TOTALS' columns of the
        # Totals row are prior-week history — they roll on the two tabs at
        # different moments and would false-flag if gated (mirrors how
        # find_org_history_tables spans only Monday..Grand-Total). Found from the
        # weekday header row above 'Totals'; running-total col = Sunday + 1.
        dv0 = dvN = None
        # scan up to the campaign's own weekday header (the FIRST weekday row above
        # 'Totals' — the rep rows between carry no weekday labels); cap generously
        # so a big roster (header sits well above Totals) is still reached.
        for hr in range(tot - 1, max(tot - 45, -1), -1):
            wk = [c + 1 for c in range(len(grid[hr]))
                  if _cell(grid, hr, c).strip().lower() in _ORG_WEEKDAYS]
            if len(wk) >= 4:
                dv0, dvN = min(wk), max(wk) + 1        # +1 = RUNNING WEEK TOTAL
                break
        out.append({"this": tot + 1, "lw": i + 1, "pw": i + 2,
                    "2wp": i + 3, "3wp": i + 4,
                    "c0": min(daycols), "cN": max(daycols),
                    "day_c0": dv0 if dv0 is not None else min(daycols),
                    "day_cN": dvN if dvN is not None else max(daycols)})
    return out


def plan_org_history_rollover(ws, table: dict):
    """Shift the static 4-week history DOWN one row, seeding Last Week from the
    just-finished week's 'Sales - This Week' (read as VALUES before the daily
    area is cleared): Last Week ← this week, Prior Week ← Last Week, 2 Weeks
    Prior ← Prior Week, 3 Weeks Prior ← 2 Weeks Prior. Every source is read
    BEFORE any write, so the cascade can't corrupt. All written as static
    values (Grand-Total column included — it's static, not a formula). Read-only
    until applied."""
    c0, cN = table["c0"], table["cN"]

    def span(r):
        return f"{a1col(c0)}{r}:{a1col(cN)}{r}"

    src = [table["this"], table["lw"], table["pw"], table["2wp"]]
    dst = [table["lw"], table["pw"], table["2wp"], table["3wp"]]
    got = ws.batch_get([span(r) for r in src],
                       value_render_option="UNFORMATTED_VALUE")
    updates = []
    for d, block in zip(dst, got):
        vals = list(block[0]) if block else []
        if vals:
            updates.append({"range": span(d), "values": [vals]})
    return updates


# --------------------------------------------------------------------------
# Per-captainship Product-Summary WE-stack week-log (insert-at-top, grows down)
# --------------------------------------------------------------------------
# Unlike the daily-section history blocks (fixed 4 rows 'Last Week'…'3 Weeks
# Prior', value-shift, drops the 5th — see find_campaign_history_tables), each
# captainship's Product Summary keeps a FULL dated week-log: a 'Totals' row
# (live =SUM of the captain's daily chart) sitting directly above a stack of
# 'WE m.d' rows, newest first, growing DOWN. The Tuesday rollover INSERTS the
# just-finished week as a new row at the TOP (static values) and re-anchors the
# two summary formulas ('Sales (Last Week)' = top row, 'Sales (4 Week AVG)' =
# top 4 rows) so they keep tracking the top after the shift — a raw insert makes
# Google auto-adjust them the WRONG way (they'd follow the OLD top down and drop
# the new week), so the re-anchor is mandatory. Eve 2026-06-30.

_WEEKDAYS_LOWER = {"monday", "tuesday", "wednesday", "thursday", "friday",
                   "saturday", "sunday"}
_WE_ROW_RE = re.compile(r"^WE\s+\d", re.IGNORECASE)


def we_label_short(week_ending: dt.date) -> str:
    """'WE M.D' (NON-zero-padded) matching the captainship week-log rows
    ('WE 6.21'), distinct from we_label()'s zero-padded leaderboard form
    ('WE 06.21')."""
    return f"WE {week_ending.month}.{week_ending.day}"


def _captain_span(grid: List[List[str]], title: str):
    """(start_row, end_row) 1-based of a captain's block, bounded by the NEXT
    different captain's '… CAPTAIN(SHIP) TEAM' title (col B). Used to scope a
    preview to one captainship."""
    pat = re.compile(r"\bcaptain(?:ship)?\s+team\b")
    tl = title.strip().lower()
    n = len(grid)
    start = next((i for i in range(n)
                  if tl in _cell(grid, i, 1).lower()
                  and pat.search(_cell(grid, i, 1).lower())), None)
    if start is None:
        return None
    end = n
    for i in range(start + 1, n):
        b = _cell(grid, i, 1).lower()
        m = pat.search(b)
        if m and b[:m.start()].strip() and tl not in b[:m.start()]:
            end = i
            break
    return (start + 1, end)


def find_captainship_product_summaries(grid: List[List[str]]) -> List[dict]:
    """Every captainship Product-Summary WE-stack block, anchored by label:
      • a 'Totals' row (col A) DIRECTLY above a 'WE …' history row (col A) — the
        signal that separates a captainship week-log from the daily-section
        history blocks (those carry literal 'Last Week' text under Totals);
      • the weekly day columns (Monday..Sunday) + the Grand-Total column to
        their right, read from the daily chart's weekday header above Totals;
      • the two summary rows 'Sales (Last Week)' / 'Sales ( 4 Week AVG)' (col B)
        above Totals, whose per-day cells reference the stack top.
    Returns dicts {totals_row, top_row, day_cols, gt_col, last_week_row,
    avg_row} (all 1-based). [No hardcoded rows.]"""
    out: List[dict] = []
    n = len(grid)
    for i in range(n):
        if _cell(grid, i, 0).lower() not in ("totals", "total"):
            continue
        if i + 1 >= n or not _WE_ROW_RE.match(_cell(grid, i + 1, 0)):
            continue
        # weekday header = nearest weekday-name row ABOVE Totals. Scan up to the
        # previous block boundary (its leaderboard 'TOTALS' row) with NO fixed
        # cap — big teams (15+ reps) push the daily header well above Totals, so
        # a tight window silently dropped RAF/CARLOS/COLTEN (Eve 2026-06-30).
        dayrow = None
        for r in range(i - 1, -1, -1):
            if _cell(grid, r, 0).lower() in ("totals", "total"):
                break                            # previous block's totals — stop
            if sum(1 for c in grid[r]
                   if (c or "").strip().lower() in _WEEKDAYS_LOWER) >= 4:
                dayrow = r
                break
        if dayrow is None:
            continue
        day_cols = [c + 1 for c in range(len(grid[dayrow]))
                    if (grid[dayrow][c] or "").strip().lower() in _WEEKDAYS_LOWER]
        gt_col = max(day_cols) + 1               # Grand-Total col (after Sunday)
        # summary rows above Totals (col B), found by label. The summary block
        # sits above the leaderboard, so it can be ~40 rows up for big teams —
        # scan generously, but STOP at a 'WE …' row (that means we've crossed up
        # into the PREVIOUS box's week-log, so THIS box has no summary rows and
        # we must not borrow the other box's). [No fixed offset.]
        lw_row = avg_row = None
        for r in range(i - 1, max(i - 120, -1), -1):
            if _WE_ROW_RE.match(_cell(grid, r, 0)):
                break
            b = _cell(grid, r, 1).lower().replace(" ", "")
            if b == "sales(lastweek)":
                lw_row = r + 1
            elif b == "sales(4weekavg)":
                avg_row = r + 1
            if lw_row and avg_row:
                break
        out.append({"totals_row": i + 1, "top_row": i + 2,
                    "day_cols": day_cols, "gt_col": gt_col,
                    "last_week_row": lw_row, "avg_row": avg_row})
    return out


def _captain_for_row(grid: List[List[str]], row1: int) -> str:
    """Captain name owning a given 1-based row — the nearest '… CAPTAIN(SHIP)
    TEAM' title (col B) above it. For readable per-block logging."""
    pat = re.compile(r"\bcaptain(?:ship)?\s+team\b")
    for r in range(row1 - 1, -1, -1):
        b = _cell(grid, r, 1)
        m = pat.search(b.lower())
        if m and b[:m.start()].strip():
            return b[:m.start()].strip()
    return "?"


def _roll_one_product_summary(ws, b: dict, label: str) -> dict:
    """Apply ONE WE-stack insert + re-anchor using b's CURRENT (freshly-read)
    row numbers. Caller must pass row numbers read AFTER any prior insert."""
    top, tot = b["top_row"], b["totals_row"]
    c0, gtc = min(b["day_cols"]), b["gt_col"]
    # freeze the Totals values (read just before the insert, off the live =SUM)
    tot_vals = (ws.get(f"{a1col(c0)}{tot}:{a1col(gtc)}{tot}",
                       value_render_option="UNFORMATTED_VALUE") or [[]])[0]
    # 1) structural insert of ONE blank row at the stack top
    ws.spreadsheet.batch_update({"requests": [{"insertDimension": {
        "range": {"sheetId": ws.id, "dimension": "ROWS",
                  "startIndex": top - 1, "endIndex": top},
        "inheritFromBefore": False}}]})           # inherit history-row formatting
    # 2) new WE row: label in col A, frozen day+grand-total values in C..gt
    updates = [
        {"range": f"A{top}", "values": [[label]]},
        {"range": f"{a1col(c0)}{top}:{a1col(gtc)}{top}", "values": [list(tot_vals)]},
    ]
    # 3) re-anchor the two summary formulas to the (new) top window. The insert
    #    pushed the old top from `top` to `top+1`; the freshly inserted row now
    #    occupies `top`, so the original references (=X$top, AVERAGE(X$top:
    #    X$top+3)) are exactly right — Google auto-rewrote them off the top, so
    #    we set them back. (J/Grand-Total of these rows is a self-sum owned by
    #    elapsed_totals.py — left untouched.)
    for col in b["day_cols"]:
        X = a1col(col)
        if b["last_week_row"]:
            updates.append({"range": f"{X}{b['last_week_row']}",
                            "values": [[f"={X}${top}"]]})
        if b["avg_row"]:
            updates.append({"range": f"{X}{b['avg_row']}",
                            "values": [[f"=AVERAGE({X}${top}:{X}${top + 3})"]]})
    ws.batch_update(updates, value_input_option="USER_ENTERED")
    return {**b, "label": label, "frozen": list(tot_vals)}


def apply_product_summary_rollover(ws, today=None, dry_run: bool = False,
                                   only_title: str | None = None,
                                   logfn=print) -> List[dict]:
    """Insert the just-closed week at the TOP of each captainship Product-Summary
    WE-stack (newest-first, full history kept) and re-anchor the two summary
    formulas to the fixed top window. MUST run BEFORE the daily clear (the Totals
    row is a live =SUM whose value has to be frozen first).

    A real row insert SHIFTS every row below it, so processing block N would
    invalidate stale row numbers for blocks N+1… . We therefore RE-READ the grid
    and RE-FIND every block BY LABEL after each insert, and pick the next block
    whose top WE row is not yet this week's label — never carrying fixed row
    numbers across an insert. Progress (and idempotency, within and across runs)
    is tracked by the label itself: a rolled block's top now reads `label`, so
    it's skipped next pass; the loop ends when every in-scope block carries this
    week's WE row. `only_title` scopes to ONE captainship (preview)."""
    import datetime as _dt
    today = today or _dt.date.today()
    just_closed = new_week_ending(today) - dt.timedelta(days=7)
    label = we_label_short(just_closed)
    logfn(f"  product-summary week-log — freeze {label!r} (just-closed Sunday "
          f"{just_closed.isoformat()}; today {today:%a} {today.isoformat()}; "
          f"dry_run={dry_run})")

    def _scope(grid):
        span = _captain_span(grid, only_title) if only_title else None
        if only_title and span is None:
            return None, None
        blocks = find_captainship_product_summaries(grid)
        if span:
            blocks = [b for b in blocks if span[0] <= b["totals_row"] <= span[1]]
        return blocks, span

    # DRY-RUN: one read, list every block + what WOULD be frozen (no insert, so
    # the by-label loop can't make progress — iterate once instead).
    if dry_run:
        grid = ws.get_all_values()
        blocks, span = _scope(grid)
        if blocks is None:
            logfn(f"  ⚠ captain title {only_title!r} not found — nothing to do")
            return []
        results = []
        for b in blocks:
            cap = _captain_for_row(grid, b["totals_row"])
            cur = _cell(grid, b["top_row"] - 1, 0)
            c0, gtc = min(b["day_cols"]), b["gt_col"]
            if cur == label:
                logfn(f"    [{cap}] rows {b['totals_row']}/{b['top_row']}: "
                      f"top already {label!r} — would skip")
                results.append({**b, "captain": cap, "label": label, "skipped": True})
                continue
            tv = (ws.get(f"{a1col(c0)}{b['totals_row']}:{a1col(gtc)}{b['totals_row']}",
                         value_render_option="UNFORMATTED_VALUE") or [[]])[0]
            logfn(f"    [{cap}] rows {b['totals_row']}/{b['top_row']}: would insert "
                  f"{label!r} = {list(tv)} (was top {cur!r}); summary rows "
                  f"LW={b['last_week_row']} AVG={b['avg_row']}")
            results.append({**b, "captain": cap, "label": label, "frozen": list(tv),
                            "prev_top_label": cur, "skipped": False})
        return results

    # LIVE: re-read + re-find by label after every insert.
    results: List[dict] = []
    guard = 0
    while True:
        guard += 1
        if guard > 200:            # backstop; never expected to trip
            raise RuntimeError("product-summary rollover did not converge")
        grid = ws.get_all_values()
        blocks, span = _scope(grid)
        if blocks is None:
            logfn(f"  ⚠ captain title {only_title!r} not found — nothing to do")
            break
        target = next((b for b in blocks
                       if _cell(grid, b["top_row"] - 1, 0) != label), None)
        if target is None:
            break                  # every in-scope block carries this week's WE
        cap = _captain_for_row(grid, target["totals_row"])
        prev = _cell(grid, target["top_row"] - 1, 0)
        info = _roll_one_product_summary(ws, target, label)
        info["captain"] = cap
        info["prev_top_label"] = prev
        results.append(info)
        logfn(f"    [{cap}] rows {target['totals_row']}/{target['top_row']}: "
              f"inserted {label!r} = {info['frozen']} (was top {prev!r}); "
              f"re-anchored LW→row {target['top_row']}, "
              f"AVG→{target['top_row']}:{target['top_row'] + 3}")
    logfn(f"  product-summary week-log: {len(results)} block(s) rolled to {label!r}")
    return results

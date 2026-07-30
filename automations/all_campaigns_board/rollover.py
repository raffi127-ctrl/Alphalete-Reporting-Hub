"""Weekly TUESDAY rollover for the 'All Campaigns Org Sales Board' tab.

The SAME system the ORG Sales Board rollover applies to the Copy tab
(org_sales_board.rollover), scoped to THIS tab's structures (which are a subset —
no captainships, no product-summary stacks). Runs on the first run of the new
reporting week (the reporting week rolls TUESDAY, so this fires Tuesday) and is a
self-healing no-op otherwise: it keys off the leaderboard's col-C week header, so
a missed Tuesday just rolls Wednesday instead.

Structures rolled (all found by LABEL, never row index — [[feedback_no_hardcoded_columns]]):

  1. WEEKLY LEADERBOARD (Table 1, header 'AT&T FIBER TEAM' + 'WE ..' columns):
     col C = the live current week (=SUMIF over the daily running totals); cols
     D→ = frozen weekly history, newest→oldest. GROWS by one column (like the
     ORG leaderboard, which keeps full history): each row's C..last shift RIGHT
     into D..last+1, freezing the just-closed week into D. Col C keeps its
     =SUMIF — the daily clear (step 5) zeroes what it sums, so it self-drops to 0
     for the new week without overwriting the formula. Col-C header re-dated.
     The box's TOTALS row shifts WITH the rep rows (it is the row scan's
     terminator, so it used to be left behind — its live col-C =SUM kept the open
     week right while its frozen history slid a column behind every Tuesday).

  2. DAILY 'All Units' per-rep 2-week freeze: each rep's RUNNING WEEK TOTAL (col
     J, a =SUM value) → col K (LAST WEEK'S TOTALS); old K → col L (PREVIOUS). Read
     as values before the clear. Those same two columns on the WE stack below
     (the 'Totals' row + every 'WE m.d' row) are re-derived after step 3 from the
     rule K = col-J of the row ONE week older, L = of TWO weeks older — the rep
     shift never touched them, so they went stale/blank.

  3. WE-history rows (the 'WE m.d' org-daily-breakdown rows under the daily
     Totals): INSERT the just-closed week as a new row at the TOP of the stack
     and GROW DOWN — nothing is dropped, the full history is kept (same as the
     Copy tab). Reuses the ORG rollover's product-summary engine, which also
     re-anchors 'Sales (Last Week)' (=C$<top>) and the '4 Week AVG' to the fixed
     top window after the insert.

  4. DELTA box ('Total this week'/'Last week'/'Delta' triplets): freeze each 'This
     week' value into its 'Last week' cell (reuses the ORG rollover's engine), then
     reset the 'Total for week → Last week' column (col D) to MONDAY ONLY — it's an
     enumerated sum grown a day at a time to match the elapsed days on 'Total this
     week', so the closed week's days must come out of it (Megan 2026-07-28).

  5. DAILY CLEAR + DATE ANCHOR: blank the day cells C-I so the formula-driven
     current cells drop to 0, and advance the static day-of-month anchor to the
     new Monday so the daily fill maps the new week's dates.

Steps 1-4 read live current-week values, so they MUST run before step 5 zeroes
them. WORKSHEET-SCOPED writes. Snapshot backup FIRST (own backup tab, never the
ORG board's). Preview with dry_run=True first ([[feedback_preview_marcellus]]).
[[project_org_sales_board]]
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from automations.org_sales_board.rollover import (
    a1col, we_label, target_week_label,
    find_delta_tables, plan_delta_rollover, plan_delta_lastweek_reset,
)
from automations.org_sales_board import fill_section as fs
from automations.org_sales_board import week as _wk

LEADERBOARD_LABEL = "AT&T FIBER TEAM"   # Table 1 col-A header (WE-date columns)
DAILY_LABEL = "All Units"                # Table 2 daily section
BACKUP_TAB = "backup_pre_rollover_allcampaigns"


def _cell(grid, r, c):  # 0-based
    return (grid[r][c] if r < len(grid) and c < len(grid[r]) else "").strip()


# --------------------------------------------------------------- leaderboard

def find_leaderboard_block(grid: List[List[str]]) -> dict:
    """The weekly leaderboard: col-A header == LEADERBOARD_LABEL whose col-C is a
    'WE ..' week header (distinguishes it from the daily 'All Units' section and
    the delta box, which share the tab). Returns header row, data rows (col-B
    non-empty until 'TOTALS'), and the last WE column (grows, so scan the whole
    header row)."""
    n = len(grid)
    hr = None
    for i in range(n):
        if (_cell(grid, i, 0).lower() == LEADERBOARD_LABEL.lower()
                and _cell(grid, i, 2).upper().startswith("WE ")):
            hr = i + 1
            break
    if hr is None:
        raise ValueError(f"Leaderboard block '{LEADERBOARD_LABEL}' (col-A header "
                         f"with a 'WE ..' col-C) not found.")
    last_col = max((c + 1 for c in range(2, len(grid[hr - 1]))
                    if _cell(grid, hr - 1, c)), default=3)
    rows: List[int] = []
    totals_row = None
    for i in range(hr, n):
        a = _cell(grid, i, 0).lower()
        b = _cell(grid, i, 1)
        if a.startswith("total"):
            totals_row = i + 1        # the terminator — reported, NOT a data row
            break
        if b:
            rows.append(i + 1)
    return {"header_row": hr, "data_rows": rows, "totals_row": totals_row,
            "first_col": 3, "last_col": last_col}


def plan_leaderboard_rollover(ws, block: dict, new_label: str):
    """GROW-RIGHT shift — a NEW week column IS added (Megan 2026-07-24: the
    leaderboard keeps full weekly history, like the ORG leaderboard). The
    just-closed week's col-C VALUE freezes into D, D→E, …, last→last+1 (grows by
    one col); col C keeps its =SUMIF (self-zeroes on the daily clear) and its
    header re-dates to the new week.

    Destination D..last+1 = source C..last; nothing is dropped.

    The box's own TOTALS row shifts WITH the rep rows. It is the terminator of
    find_leaderboard_block's row scan, not a member of it, and leaving it out is
    exactly the defect Eve caught on the ORG board 2026-07-28: its col C is a
    live '=SUM' so the OPEN week always looked right, while its static D.. history
    stood still and slid one column further behind every Tuesday — the column
    labelled 'WE 07.26' ending up showing a fortnight-old total. Col C is never
    written here, so the =SUM survives the shift.
    [[project_org-board-leaderboard-totals-row]]"""
    c0, c1 = block["first_col"], block["last_col"]        # C .. last
    width = c1 - c0 + 1
    hr = block["header_row"]
    Cl, Dl, ANl = a1col(c0), a1col(c0 + 1), a1col(c1 + 1)
    updates = []
    hdr = (ws.get(f"{Cl}{hr}:{a1col(c1)}{hr}",
                  value_render_option="UNFORMATTED_VALUE") or [[]])[0]
    hdr = (list(hdr) + [""] * width)[:width]              # old C..last
    updates.append({"range": f"{Cl}{hr}:{ANl}{hr}", "values": [[new_label] + hdr]})
    shift_rows = list(block["data_rows"])
    if block.get("totals_row"):
        shift_rows.append(block["totals_row"])
    r0, r1 = shift_rows[0], shift_rows[-1]
    vals = ws.get(f"{Cl}{r0}:{a1col(c1)}{r1}",
                  value_render_option="UNFORMATTED_VALUE")
    rowmap = {r0 + i: (list(r) + [""] * width)[:width]
              for i, r in enumerate(vals)}
    for row in shift_rows:
        cur = rowmap.get(row, [""] * width)               # old C..last (C = value)
        updates.append({"range": f"{Dl}{row}:{ANl}{row}", "values": [cur]})
        # col C left untouched — keeps its =SUMIF/=SUM, self-zeroes on the clear
    return updates


# --------------------------------------------------------------- daily 2-week + WE history

def plan_daily_kl_freeze(ws, anchor) -> list:
    """Per rep: RUNNING WEEK TOTAL (col J value) -> LAST WEEK'S (col K); old K ->
    PREVIOUS WEEK'S (col L). Read as values (J is a =SUM) before the clear. The
    running-total col + the two history cols are located from the daily header."""
    hdr_row = anchor.header_row
    def col_by_hdr(name):
        for c, v in enumerate(ws_hdr):
            if str(v).strip().lower() == name:
                return c + 1
        return None
    ws_hdr = (ws.get(f"A{hdr_row}:AZ{hdr_row}",
                     value_render_option="UNFORMATTED_VALUE") or [[]])[0]
    run_c = anchor.running_total_col
    k_c = col_by_hdr("last week's totals")
    l_c = col_by_hdr("previous week's totals")
    if not (k_c and l_c):
        return []
    rows = sorted(anchor.icd_rows.values())
    r0, r1 = rows[0], rows[-1]
    block = ws.batch_get(
        [f"{a1col(run_c)}{r0}:{a1col(run_c)}{r1}",
         f"{a1col(k_c)}{r0}:{a1col(k_c)}{r1}"],
        value_render_option="UNFORMATTED_VALUE")
    j_vals = [row[0] if row else "" for row in (block[0] or [])]
    k_vals = [row[0] if row else "" for row in (block[1] or [])]
    updates = []
    for i, row in enumerate(range(r0, r1 + 1)):
        j = j_vals[i] if i < len(j_vals) else ""
        k = k_vals[i] if i < len(k_vals) else ""
        updates.append({"range": f"{a1col(l_c)}{row}", "values": [[k if k != "" else 0]]})
        updates.append({"range": f"{a1col(k_c)}{row}", "values": [[j if j != "" else 0]]})
    return updates


# --------------------------------------------------------------- clear + anchor

def plan_daily_clear(anchor) -> str:
    rows = sorted(anchor.icd_rows.values())
    cols = sorted(anchor.day_col_by_daynum.values())
    return f"{a1col(cols[0])}{rows[0]}:{a1col(cols[-1])}{rows[-1]}"


# --------------------------------------------------------------- backup

def _snapshot(ws, grid, dry_run: bool, logfn) -> None:
    rows = len(grid)
    cols = max((len(r) for r in grid), default=1)
    if dry_run:
        logfn(f"  0/6 snapshot: WOULD freeze {rows}x{cols} of {ws.title!r} into "
              f"{BACKUP_TAB!r} — dry-run, skipped")
        return
    try:
        sh = ws.spreadsheet
        try:
            bws = sh.worksheet(BACKUP_TAB)
        except Exception:
            bws = sh.add_worksheet(title=BACKUP_TAB, rows=max(rows, 1), cols=max(cols, 1))
            logfn(f"  0/6 snapshot: created backup tab {BACKUP_TAB!r}")
        bws.resize(rows=max(rows, 1), cols=max(cols, 1))
        rect = [row + [""] * (cols - len(row)) for row in grid]
        bws.update(range_name="A1", values=rect, value_input_option="RAW")
    except Exception as e:  # noqa: BLE001 — abort the roll; never swallow
        raise RuntimeError(f"pre-rollover snapshot to {BACKUP_TAB!r} FAILED "
                           f"({type(e).__name__}: {e}) — NOT rolling") from e
    logfn(f"  0/6 snapshot: froze {rows}x{cols} into {BACKUP_TAB!r}")


# --------------------------------------------------------------- orchestration

def week_label_of(grid) -> str:
    try:
        b = find_leaderboard_block(grid)
        return _cell(grid, b["header_row"] - 1, b["first_col"] - 1)
    except Exception:
        return ""


def needs_rollover(grid, today=None) -> tuple:
    """True when the board is NOT on the week the fill is about to write
    (target_week_label) — fires on the first run of the new reporting week
    (Tuesday) and is a no-op otherwise. Returns (needed, target, current)."""
    tgt = target_week_label(today)
    cur = week_label_of(grid)
    return (bool(cur and tgt and cur != tgt), tgt, cur)


def run_rollover(ws, today=None, dry_run: bool = False, logfn=print) -> dict:
    today = today or dt.date.today()
    new_label = target_week_label(today)               # 'WE MM.DD' zero-padded
    grid = ws.get_all_values()
    lb = find_leaderboard_block(grid)
    cur = _cell(grid, lb["header_row"] - 1, lb["first_col"] - 1)
    summary = {"new_label": new_label, "prev_label": cur}
    if cur == new_label:
        logfn(f"  rollover already done this week (leaderboard col C = "
              f"{new_label!r}) — skip")
        summary["skipped"] = True
        return summary
    logfn(f"=== All Campaigns rollover — {cur!r} → {new_label!r} "
          f"(dry_run={dry_run}) ===")

    _snapshot(ws, grid, dry_run, logfn)
    summary["backup_tab"] = BACKUP_TAB

    # 1) leaderboard grow-right + re-date col C
    upd = plan_leaderboard_rollover(ws, lb, new_label)
    if upd and not dry_run:
        ws.batch_update(upd, value_input_option="USER_ENTERED")
    tot_note = (f" + TOTALS row {lb['totals_row']}" if lb.get("totals_row")
                else " — ⚠ no TOTALS row found, its history will NOT shift")
    logfn(f"  1/6 leaderboard frozen ({len(lb['data_rows'])} rep rows{tot_note})"
          f" → new col C {new_label}; {len(upd)} write(s)")

    anchor = fs.find_daily_section(grid, DAILY_LABEL)
    # 2) daily per-rep J → K → L (fixed window: L is dropped, no new columns)
    upd = plan_daily_kl_freeze(ws, anchor)
    if upd and not dry_run:
        ws.batch_update(upd, value_input_option="USER_ENTERED")
    logfn(f"  2/6 daily per-rep running-total frozen (J→K→L); {len(upd)} write(s)")

    # 3) delta box: this week → last week. Done BEFORE the WE-history row insert
    # (step 4), which shifts every row below it — freezing the delta first keeps
    # its live values intact; the insert only moves the (already-frozen) rows.
    tables = find_delta_tables(grid)
    dcount = 0
    lw_updates = []
    for t in tables:
        upd = plan_delta_rollover(ws, t)
        if upd and not dry_run:
            ws.batch_update(upd, value_input_option="USER_ENTERED")
        if upd:
            dcount += 1
        # 'Total for week → Last week' (col D) back to MONDAY ONLY. It's an
        # enumerated sum (=G+J+M+…) grown one day at a time so it spans the same
        # elapsed days as 'Total this week'; the new week has a single completed
        # day, so every day carried over from the closed week comes out.
        lw_updates += plan_delta_lastweek_reset(grid, t)
    if lw_updates and not dry_run:
        ws.batch_update(lw_updates, value_input_option="USER_ENTERED")
    logfn(f"  3/6 {dcount} delta table(s) frozen (this week → last week); "
          f"'Last week' week-total reset to Monday only "
          f"({len(lw_updates)} cell(s))")

    # 4) WE-history: INSERT the just-closed week at the TOP of the stack and GROW
    # DOWN — nothing dropped, same as the Copy tab (Megan 2026-07-24). Reuses the
    # ORG rollover's product-summary engine (Totals row → new 'WE m.d' top row +
    # re-anchor 'Sales (Last Week)' / '4 Week AVG' to the fixed top window).
    from automations.org_sales_board.rollover import apply_product_summary_rollover
    ps = apply_product_summary_rollover(ws, today=today, dry_run=dry_run, logfn=logfn)
    logfn(f"  4/6 WE-history grown down ({len(ps)} stack(s) — new week at top, "
          f"none dropped)")

    # 4b) PRIOR-WEEK COLUMNS — "LAST WEEK'S TOTALS" (K) / "PREVIOUS WEEK'S
    # TOTALS" (L) on the WE stack, re-derived from the one rule that governs
    # them on EVERY row of the stack, the 'Totals' row included:
    #     K = the col-J total of the row ONE week older, L = of TWO weeks older.
    # Step 2 above shifts the per-REP J→K→L, but nothing seeded the stack: the
    # 'Totals' row's K/L sat frozen at whatever a human last typed and the WE row
    # step 4 inserts came in with K/L blank. Re-deriving the whole stack is
    # idempotent, so this also self-heals the weeks already drifted and any
    # future missed Tuesday. MUST run AFTER the insert (it reads the just-frozen
    # week) — hence the fresh grid read inside apply_prior_week_totals — and it
    # never reads the live 'Totals' col-J, so the daily clear below is
    # unaffected. [[project_org-board-prior-week-columns]]
    from automations.org_sales_board.rollover import (
        apply_prior_week_totals, check_prior_week_totals,
        check_leaderboard_totals_front)
    if dry_run:
        pre = check_prior_week_totals(grid)
        logfn(f"  4b/6 [dry-run] prior-week columns: {len(pre)} cell(s) "
              f"currently break the rule; the real roll re-derives the stack "
              f"AFTER the week insert")
    else:
        pw = apply_prior_week_totals(ws, dry_run=False, logfn=logfn)
        after = ws.get_all_values()
        post = check_prior_week_totals(after)
        logfn(f"  4b/6 prior-week columns re-derived ({len(pw)} cell(s)); "
              f"{len(post)} residual violation(s)"
              + (f" — {post[:3]}" if post else ""))
        summary["prior_week_cells"] = len(pw)
        summary["prior_week_residual"] = len(post)
        # …and the tripwire for the OTHER half of the same defect: the box's
        # TOTALS row must have moved right with its rep rows.
        lb2 = find_leaderboard_block(after)
        if lb2.get("totals_row"):
            ok, msg = check_leaderboard_totals_front(
                after, lb2["data_rows"], lb2["totals_row"],
                lb2["first_col"] + 1)
            logfn(f"  4b/6 {'✔' if ok else '❌'} {msg}")
            summary["leaderboard_totals_ok"] = ok

    # 5) clear daily day cells (the daily table sits ABOVE the WE insert, so its
    # anchor row numbers are unchanged).
    clr = plan_daily_clear(anchor)
    if not dry_run:
        ws.batch_clear([clr])
    logfn(f"  5/6 daily day cells cleared ({clr}) — new week blank")

    # 6) advance the static day-of-month anchor to the new Monday
    new_monday = _wk.reporting_sunday(today) - dt.timedelta(days=6)
    first_col = min(anchor.day_col_by_daynum.values())
    cell = f"{a1col(first_col)}{anchor.daynum_row}"
    if not dry_run:
        ws.update(cell, [[new_monday.day]], value_input_option="USER_ENTERED")
    logfn(f"  6/6 daily date anchor {cell} → {new_monday.day} "
          f"(week of {new_monday.isoformat()})")
    logfn("=== rollover done ===")
    summary.update({"leaderboard_rows": len(lb["data_rows"]),
                    "we_history_stacks": len(ps),
                    "delta_tables": dcount, "cleared": clr,
                    "anchor_cell": cell, "anchor_day": new_monday.day})
    return summary

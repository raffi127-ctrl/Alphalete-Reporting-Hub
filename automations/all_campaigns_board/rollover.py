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

  2. DAILY 'All Units' per-rep 2-week freeze: each rep's RUNNING WEEK TOTAL (col
     J, a =SUM value) → col K (LAST WEEK'S TOTALS); old K → col L (PREVIOUS). Read
     as values before the clear.

  3. WE-history rows (the 'WE m.d' org-daily-breakdown rows under the daily
     Totals): seed the top row from the just-closed week's Totals row, shift the
     rest down within the fixed window (oldest drops). Feeds 'Sales (Last Week)'
     (=C$<top>) which stays valid because this is a VALUE shift, not a row insert.

  4. DELTA box ('Total this week'/'Last week'/'Delta' triplets): freeze each 'This
     week' value into its 'Last week' cell (reuses the ORG rollover's engine).

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
    find_delta_tables, plan_delta_rollover,
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
    for i in range(hr, n):
        a = _cell(grid, i, 0).lower()
        b = _cell(grid, i, 1)
        if a == "totals":
            break
        if b:
            rows.append(i + 1)
    return {"header_row": hr, "data_rows": rows, "first_col": 3,
            "last_col": last_col}


def plan_leaderboard_rollover(ws, block: dict, new_label: str):
    """FIXED-WINDOW shift — NO new column is added to the right (Megan
    2026-07-24). The just-closed week's col-C VALUE moves into D, D→E, …, and the
    OLDEST week (col `last`) falls off. Same principle as the daily J→K→L freeze.
    Col C keeps its =SUMIF (self-zeroes on the daily clear); its header re-dates.

    Destination D..last (cols first+1..last) = source C..last-1 (cols
    first..last-1); the old `last` value is overwritten (lost)."""
    c0, c1 = block["first_col"], block["last_col"]        # C .. G (oldest)
    if c1 <= c0:
        return []
    hr = block["header_row"]
    Cl, Dl, Gl = a1col(c0), a1col(c0 + 1), a1col(c1)
    src_last = a1col(c1 - 1)                               # F (one left of oldest)
    wsrc = c1 - c0                                         # # source cols C..F
    updates = []
    # header: C = new label; D..last = old C..(last-1)
    hdr = (ws.get(f"{Cl}{hr}:{src_last}{hr}",
                  value_render_option="UNFORMATTED_VALUE") or [[]])[0]
    hdr = (list(hdr) + [""] * wsrc)[:wsrc]
    updates.append({"range": f"{Cl}{hr}:{Gl}{hr}", "values": [[new_label] + hdr]})
    # data rows: D..last = old C..(last-1); col C left untouched (keeps =SUMIF)
    rng = f"{Cl}{block['data_rows'][0]}:{src_last}{block['data_rows'][-1]}"
    vals = ws.get(rng, value_render_option="UNFORMATTED_VALUE")
    rowmap = {block["data_rows"][0] + i: (list(r) + [""] * wsrc)[:wsrc]
              for i, r in enumerate(vals)}
    for row in block["data_rows"]:
        cur = rowmap.get(row, [""] * wsrc)                # old C..(last-1) VALUES
        updates.append({"range": f"{Dl}{row}:{Gl}{row}", "values": [cur]})
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


def find_we_history_rows(grid, daily_totals_row: int) -> List[int]:
    """The 'WE m.d' org-daily-breakdown rows directly below the daily Totals row.
    Contiguous run of col-A labels starting 'WE '."""
    out = []
    for r in range(daily_totals_row + 1, len(grid) + 1):
        if _cell(grid, r - 1, 0).upper().startswith("WE "):
            out.append(r)
        elif out:
            break
    return out


def plan_we_history_rollover(ws, anchor, we_rows: List[int], new_label_short: str):
    """Value-shift the WE-history window down one row, seeding the top from the
    just-closed week's daily Totals row (cols C..last-history). Oldest drops. A
    VALUE shift (not a row insert) so the 'Sales (Last Week)' =C$<top> anchor
    stays valid. new_label_short = the closed week's 'WE m.d' col-A label."""
    if not we_rows:
        return []
    # span: from the first day col through the widest history col across the rows
    day_c0 = min(anchor.day_col_by_daynum.values())
    tot = anchor.totals_row
    scan_rows = [tot] + we_rows
    maxc = 1
    for r in scan_rows:
        got = ws.get(f"A{r}:AZ{r}", value_render_option="UNFORMATTED_VALUE")
        row = got[0] if got else []
        for c in range(len(row)):
            if str(row[c]).strip():
                maxc = max(maxc, c + 1)
    c0, cN = day_c0, maxc
    def span(r):
        return f"{a1col(c0)}{r}:{a1col(cN)}{r}"
    src = [tot] + we_rows[:-1]        # Totals -> top ; top -> 2nd ; ...
    dst = we_rows
    got = ws.batch_get([span(r) for r in src],
                       value_render_option="UNFORMATTED_VALUE")
    updates = []
    for d, block in zip(dst, got):
        vals = list(block[0]) if block and block[0] else []
        if vals:
            updates.append({"range": span(d), "values": [vals]})
    # re-label the new top row's col A to the just-closed week
    updates.append({"range": f"A{we_rows[0]}", "values": [[new_label_short]]})
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
    logfn(f"  1/6 leaderboard frozen ({len(lb['data_rows'])} rows) → new col C "
          f"{new_label}; {len(upd)} write(s)")

    anchor = fs.find_daily_section(grid, DAILY_LABEL)
    # 2) daily per-rep J → K → L
    upd = plan_daily_kl_freeze(ws, anchor)
    if upd and not dry_run:
        ws.batch_update(upd, value_input_option="USER_ENTERED")
    logfn(f"  2/6 daily per-rep running-total frozen (J→K→L); {len(upd)} write(s)")

    # 3) WE-history rows shift down (seed top from Totals)
    from automations.org_sales_board.rollover import we_label_short, new_week_ending
    just_closed = new_week_ending(today) - dt.timedelta(days=7)
    we_rows = find_we_history_rows(grid, anchor.totals_row)
    upd = plan_we_history_rollover(ws, anchor, we_rows,
                                   we_label_short(just_closed))
    if upd and not dry_run:
        ws.batch_update(upd, value_input_option="USER_ENTERED")
    logfn(f"  3/6 WE-history window shifted ({len(we_rows)} row(s), top = "
          f"{we_label_short(just_closed)}); {len(upd)} write(s)")

    # 4) delta box: this week → last week
    tables = find_delta_tables(grid)
    dcount = 0
    for t in tables:
        upd = plan_delta_rollover(ws, t)
        if upd and not dry_run:
            ws.batch_update(upd, value_input_option="USER_ENTERED")
        if upd:
            dcount += 1
    logfn(f"  4/6 {dcount} delta table(s) frozen (this week → last week)")

    # 5) clear daily day cells
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
                    "we_history_rows": len(we_rows),
                    "delta_tables": dcount, "cleared": clr,
                    "anchor_cell": cell, "anchor_day": new_monday.day})
    return summary

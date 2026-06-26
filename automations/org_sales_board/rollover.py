"""Weekly TUESDAY rollover for the Alphalete ORG Sales Board.

Run FIRST thing TUESDAY, BEFORE the new week's daily fill (Megan 2026-06-03).
NOT Monday: Monday is when the VAs enter the prior week's SUNDAY production, so
the just-finished week isn't complete until Monday's entry is done. Running the
rollover Tuesday freezes a COMPLETE week; running it Monday would freeze a week
still missing Sunday. (The week math — new_week_ending — resolves the same
Mon–Sun week for any weekday, so only the run-DAY matters, not the code.)
Three mechanics:

1. LEADERBOARDS (the ALPHALETE ORG weekly-history block + the 10 captainship
   strips): col C = the live current week (a =SUM/=SUMIF formula for ORG, a
   filled value for captainships); cols D→ = frozen static history (WE dates,
   newest→oldest left→right). Rollover GROWS by one column (Megan 2026-06-01,
   keep full history): each data row's values shift one column RIGHT
   (C-value→D, D→E, …) freezing the completed week into D; col C keeps its
   formula (ORG) or is zeroed (captainships, refilled by the daily run). The
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
      • col-C VALUE is zeroed (the daily run refills the new week);
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
    # Data rows: shift old C..last -> D..last+1, zero C.
    rng = f"{Cl}{data_rows[0]}:{a1col(c1)}{data_rows[-1]}"
    vals = ws.get(rng, value_render_option="UNFORMATTED_VALUE")
    rowmap = {data_rows[0] + i: (list(r) + [""] * width)[:width]
              for i, r in enumerate(vals)}
    for row in data_rows:
        cur = rowmap.get(row, [""] * width)
        updates.append({"range": f"{Dl}{row}:{ANl}{row}", "values": [cur]})
        updates.append({"range": f"{Cl}{row}", "values": [[0]]})
    return updates, {"rows": len(data_rows), "grow_into": ANl}


DAILY_SECTION_LABELS = [
    "Retail NL", "ATT Fiber Team", "Retail JE", "ATT NDS Team", "B2B",
    "BOX", "Frontier", "Retail Internet",
]

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
        logfn(f"  ⚠ rollover is meant to run TUESDAY (after Monday's Sunday "
              f"entry); today is {today:%A} {today.isoformat()} — double-check "
              f"the just-finished week is complete before relying on this.")
    new_label = we_label(new_week_ending(today))
    logfn(f"=== ORG board Tuesday rollover — new week {new_label} "
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

    ranges = plan_daily_clear(ws, grid)
    if not dry_run:
        ws.batch_clear(ranges)
    summary["cleared_ranges"] = len(ranges)
    logfn(f"  4/5 daily charts cleared ({len(ranges)} ranges) — new week blank")

    # 5/5 Advance the daily-section week dates. Each daily section's day-of-month
    # row derives from ONE static anchor cell (the first/Retail NL section's
    # Monday); every other section references it (=C81…), so setting that single
    # cell rolls all the daily sections to the new week. Without this the daily
    # fill skips the new week's pulls ("not on the sheet's current week → 0
    # cells") and the whole current week stays blank (found 2026-06-02).
    from automations.org_sales_board import fill_section as fs
    new_monday = new_week_ending(today) - dt.timedelta(days=6)
    anchor_cell = None
    for label in DAILY_SECTION_LABELS:
        try:
            a = fs.find_daily_section(grid, label)
        except Exception:
            continue
        cell = f"{a1col(min(a.day_col_by_daynum.values()))}{a.daynum_row}"
        try:
            fcur = ws.get(cell, value_render_option="FORMULA")
            cur = (fcur[0][0] if fcur and fcur[0] else "")
        except Exception:
            cur = ""
        if not str(cur).startswith("="):          # the static master anchor
            if not dry_run:
                ws.update(cell, [[new_monday.day]],
                          value_input_option="USER_ENTERED")
            anchor_cell = cell
            break
    if anchor_cell:
        summary["daily_anchor"] = anchor_cell
        logfn(f"  5/5 daily date anchor {anchor_cell} → {new_monday.day} "
              f"(week of {new_monday.isoformat()})")
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
    blocks). A header row has 'Total this week' in col C; the per-day 'This week'
    columns are paired with the 'Last week' column to their immediate right.
    Data rows run until col B blanks out or hits the 'Captainship' total row."""
    out = []
    n = len(grid)
    for i in range(n):
        if _cell(grid, i, 2) != "Total this week":
            continue
        this_cols = [c + 1 for c in range(len(grid[i]))
                     if _cell(grid, i, c) == "This week"]   # per-day only
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

"""Weekly Monday rollover for the Alphalete ORG Sales Board.

Run FIRST thing Monday, BEFORE the new week's daily fill, so the just-finished
week is frozen before the daily areas reset. Three mechanics:

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

CAPTAIN_NAMES = ["RAF", "WAYNE", "STARR", "ARON", "CARLOS", "EVELIZ",
                 "LUIS", "KHALIL", "COLTEN", "JAIRO"]


def run_rollover(ws, today=None, dry_run: bool = False, logfn=print) -> dict:
    """The whole Monday rollover in order — run BEFORE the new week's daily
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
    new_label = we_label(new_week_ending(today))
    logfn(f"=== ORG board Monday rollover — new week {new_label} "
          f"(dry_run={dry_run}) ===")
    summary = {"new_label": new_label, "captainships": 0, "delta_tables": 0,
               "cleared_ranges": 0}

    grid = ws.get_all_values()
    org = find_org_block(grid)
    upd, _ = plan_leaderboard_rollover(ws, org, new_label)
    if not dry_run:
        ws.batch_update(upd, value_input_option="USER_ENTERED")
    logfn(f"  1/4 ORG leaderboard frozen (hdr {org.header_row}); "
          f"new col {new_label}")

    grid = ws.get_all_values()                 # ORG headers changed
    org = find_org_block(grid)
    for name in CAPTAIN_NAMES:
        try:
            a = cap.find_captainship(grid, name)
        except Exception as e:
            logfn(f"      ⚠ captainship {name} not found: {e}")
            continue
        hdr_row = a.leaderboard[0][0] - 2
        lb_rows = [r for r, _ in a.leaderboard]
        last_col = max((c + 1 for c in range(2, len(grid[hdr_row - 1]))
                        if (grid[hdr_row - 1][c] or "").strip()), default=16)
        upd, _ = plan_captainship_leaderboard_rollover(
            ws, hdr_row, lb_rows, last_col, org.header_row, org.last_col)
        if not dry_run:
            ws.batch_update(upd, value_input_option="USER_ENTERED")
        summary["captainships"] += 1
    logfn(f"  2/4 {summary['captainships']} captainship leaderboards frozen")

    tables = find_delta_tables(grid)
    for t in tables:
        upd = plan_delta_rollover(ws, t)
        if upd and not dry_run:
            ws.batch_update(upd, value_input_option="USER_ENTERED")
    summary["delta_tables"] = len(tables)
    logfn(f"  3/4 {len(tables)} delta tables frozen (this week -> last week)")

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
    for name in ("RAF", "WAYNE", "STARR", "ARON", "CARLOS", "EVELIZ",
                 "LUIS", "KHALIL", "COLTEN", "JAIRO"):
        try:
            a = cap.find_captainship(grid, name)
        except Exception:
            continue
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

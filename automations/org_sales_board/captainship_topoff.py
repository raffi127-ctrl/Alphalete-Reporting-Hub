"""Captainship top-off: re-pull the three program views right before the
captainship drafts are built, and RAISE any completed-day cell that Tableau now
has higher than the 05:20 board fill wrote.

WHY (Eve 2026-10-01). Austin Eldredge (Pat's captainship) wrote in: "my numbers
are very off for yesterday". His Wednesday on the mail was 7 New Internet / 9
units; Tableau Product Sales Summary had 16 / 22 by 10:43. Monday and Tuesday
were exact. The board fill ran 05:20-05:34 CT and at that hour Tableau did not
have all of Wednesday yet — Pat's whole team read 141 that day (Mon 157, Tue
182), and Starr, Tony, Sahil and Jess were short too. The next morning's fill
rewrites every day of the week, so the board heals itself a day later — but the
captainship mail screenshots the board at ~06:45 and goes out with the short
number.

So this runs on Lucy 3, `after: captainship_knocks`, not before 06:30, and
`captainship_drafts` runs `after` it: same machine, so the ordering is
enforced, and `after` is soft — a failed top-off never holds the drafts.

ONLY RAISES. A cell is written only when the new value is HIGHER than what is
on the board. That is the whole job (late sales), and it makes a bad pull
harmless: a program view that failed, came back filtered, or matched nobody
reads as 0 and writes nothing. A genuine drop (a cancel) waits for tomorrow's
05:20 fill, which rewrites the week anyway.

Writes only captainship day cells; the running totals, leaderboard "this week"
and delta boxes are live formulas over them. Then it re-sorts the CAPTAINSHIP
blocks only (never the campaign sections above — Lucy 1's BOX top-off writes
those at 06:52) and the delta boxes. No manifest, no Activity verdict on the
board: this is not the board's run.

Every raised cell is logged ("Pat's Captain Team · Austin Eldredge · Wed NI
7 -> 16"), which is also how we learn whether 06:30 is late enough.

    python -m automations.org_sales_board.captainship_topoff --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Tuple

from automations.org_sales_board import captainship as cap

_DAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _num(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except ValueError:
        return 0


def _cell(grid, r, c) -> str:  # 1-based
    return (grid[r - 1][c - 1] if r - 1 < len(grid) and c - 1 < len(grid[r - 1])
            else "")


def plan_raises(grid, prog: Dict[str, dict], today: dt.date,
                aliases) -> Tuple[List[dict], List[str]]:
    """Pure: -> (sheet updates, human log lines) for every completed-day cell of
    every captainship box where the pull is HIGHER than the board."""
    from automations.org_sales_board import week as _wk
    monday = _wk.reporting_monday(today)
    updates, lines = [], []
    for title, tkey in cap.discover_captainships(grid):
        def per_for(name, metric=None, tkey=tkey):
            # Same lookup as run_captainships: own program first, then any other.
            cands = cap._candidates_for_name(name, aliases)
            for tk in [tkey] + [k for k in prog if k != tkey]:
                pdata = prog.get(tk, {})
                k = next((x for x in pdata if x in cands), None)
                if k:
                    return pdata[k].get(metric or cap.TYPES[tk]["metric"], {})
            return {}
        try:
            boxes = cap.find_captainship_boxes(grid, title)
        except Exception:  # noqa: BLE001 — a block we can't read is skipped
            continue
        for variant, anchor in boxes:
            metric = ("NewInternet" if tkey == "fiber" and variant == "new_internet"
                      else None)
            tag = "NI" if metric else "units"
            for row, name in anchor.daily:
                per = per_for(name, metric) or {}
                for i, col in enumerate(anchor.day_cols):
                    d = monday + dt.timedelta(days=i)
                    if d >= today:
                        continue
                    new = _num(per.get(d, 0))
                    old_raw = _cell(grid, row, col)
                    if new > _num(old_raw):
                        updates.append({"range": f"{cap._a1col(col)}{row}",
                                        "values": [[new]]})
                        lines.append(f"{title} · {name} · {_DAY_ABBR[i]} {tag} "
                                     f"{old_raw or 'blank'} -> {new}")
    return updates, lines


def first_captainship_row(grid) -> int:
    """1-based row of the first captainship band; everything above is the
    campaign sections, which this module never re-sorts."""
    for r in range(len(grid)):
        if cap.block_title(grid, r):
            return r + 1
    return len(grid) + 1


def _start_row(a1_range: str) -> int:
    m = re.search(r"(\d+)", a1_range)
    return int(m.group(1)) if m else 0


def resort_captainships(ws, dry_run=False, logfn=print) -> None:
    from automations.org_sales_board import sort as _sort, delta_sort as _dsort
    grid = ws.get_all_values()
    fgrid = ws.get(f"A1:{_sort._a1(108)}{len(grid)}",
                   value_render_option="FORMULA")
    cut = first_captainship_row(grid)
    plan = [u for u in (_sort.plan_daily_sorts(grid)
                        + _sort.plan_leaderboard_sorts(grid, fgrid))
            if _start_row(u["range"]) >= cut]
    logfn(f"  sort: {len(plan)} captainship range(s) from row {cut}")
    if plan and not dry_run:
        ws.batch_update(plan, value_input_option="USER_ENTERED")
    _dsort.apply_delta_sort(ws, dry_run=dry_run, logfn=logfn)


def run(dry_run=False, today=None, logfn=print) -> int:
    from automations.focus_office_att.aliases import load_aliases
    from automations.org_sales_board.run import SHEET_ID
    from automations.org_sales_board.tabs import BOARD_TAB
    from automations.recruiting_report.fill import open_by_key
    from automations.shared.tableau_patchright import tableau_session

    today = today or dt.date.today()
    ws = open_by_key(SHEET_ID).worksheet(BOARD_TAB)
    with tableau_session(verbose=False) as page:
        prog, failed = cap.pull_programs(
            page, today, out_prefix="org_sales_board_topoff_", logfn=logfn)
    if failed:
        logfn(f"  ⚠ program pull(s) failed: {failed} — those can only stay as "
              f"they are (this step never lowers a cell)")
    grid = ws.get_all_values()          # read AFTER the pull: freshest board
    updates, lines = plan_raises(grid, prog, today, load_aliases())
    for ln in lines:
        logfn(f"  ↑ {ln}")
    logfn(f"=== top-off: {len(updates)} cell(s) raised"
          f"{' (dry-run, nothing written)' if dry_run else ''} ===")
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        resort_captainships(ws, logfn=logfn)
    # Every program failing = nothing was checked. Say so with the exit code;
    # the drafts still run (they are `after` this, which is soft).
    return 1 if failed and len(failed) >= len(cap.PROGRAMS) else 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="captainship_topoff")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pull and list what would be raised; write nothing.")
    args = ap.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

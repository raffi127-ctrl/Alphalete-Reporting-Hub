#!/usr/bin/env python3
"""Country Sales Board — daily fill + Tuesday rollover.

Fills the 'Country Sales Board' tab of the ATT Program - Focus Report workbook
from the D2D1-PAGERV4 Tableau view ('D2D Page 1 - This Week'). One crosstab in,
seven day columns out; the rest of the tab is formulas that recompute themselves
(see fill.py).

Runs DAILY, right after the ORG Sales Board fills its Copy tab — same slot and
same shape as all_campaigns_board, which is the report this one is modelled on.
Each run does two things, in this order:

  1. ROLLOVER (Tuesdays, self-healing) — if the board isn't on the week this
     fill is about to write, close the displayed week and open the next one
     (rollover.py). Keyed off the leaderboard's week header, so a missed Tuesday
     just rolls Wednesday, and every other day of the week is a no-op. Gated
     behind --enable-rollover.
  2. FILL — pull the board's week from Tableau and write the day cells.

  python -m automations.country_sales_board.run                 # sandbox, live write
  python -m automations.country_sales_board.run --dry-run       # plan only
  python -m automations.country_sales_board.run --enable-rollover
  python -m automations.country_sales_board.run --last-week     # force the (LW2) sheet
  python -m automations.country_sales_board.run --from-csv P    # offline, no browser
  python -m automations.country_sales_board.run --real          # PROD tab (guarded)

SANDBOX BY DEFAULT. `--real` targets the live tab the VAs read and is refused
unless paired with `--i-mean-it`, mirroring org_sales_board's guard.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_sales_board.fill_section import apply_plan, find_daily_section
from automations.country_sales_board import fill as cf, pull as cp
from automations.country_sales_board import rollover as cr, week as wk

SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"
PROD_TAB = "Country Sales Board"
SANDBOX_TAB = "Country Sales Board (sandbox)"
OUT_DIR = Path("output")
CENTRAL = ZoneInfo("America/Chicago")   # [[project_central-time-for-texas-reports]]


def _verify(ws, today, dry_run: bool, skip: bool) -> int:
    """Post-write check: does the board actually carry numbers for the day this
    report is about? Returns the process exit code.

    This is the report's ONLY correctness gate. The orchestrator has no `verify`
    manifest for this one, so without it a run that completed having written
    nothing exits 0, is recorded DONE, and nobody is alerted. Re-reads the sheet
    rather than trusting the plan — that proves the write LANDED, not just that
    it was computed."""
    if dry_run:
        print("  (dry-run — skipping the yesterday check, nothing was written)")
        return 0
    if skip:
        print("  ⚠ --no-verify: skipping the yesterday check")
        return 0
    from automations.recruiting_report.fill import _retry as _r
    grid = _r(ws.get_all_values)
    ok, msg = cf.verify_yesterday(grid, today)
    if ok:
        print(f"  verify: {msg}")
        return 0
    print(f"  ❌ VERIFY FAILED — {msg}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Country Sales Board daily fill")
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan and print the writes; touch nothing.")
    ap.add_argument("--real", action="store_true",
                    help=f"Target {PROD_TAB!r} instead of the sandbox tab.")
    ap.add_argument("--i-mean-it", action="store_true",
                    help="Required alongside --real (writing the live tab).")
    ap.add_argument("--last-week", action="store_true",
                    help="Force the (LW2) worksheet instead of letting the "
                         "pull pick the one that matches the board's week.")
    ap.add_argument("--from-csv", metavar="PATH",
                    help="Parse an already-downloaded crosstab instead of "
                         "opening Tableau (offline engine check).")
    ap.add_argument("--enable-rollover", action="store_true",
                    help="Allow the Tuesday rollover to run before the fill.")
    ap.add_argument("--force-rollover", action="store_true",
                    help="Roll even when the week check says not to (repair).")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the post-write check that yesterday carries "
                         "numbers on the board.")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="Override today's date (testing/backfill).")
    args = ap.parse_args()

    if args.real and not args.i_mean_it:
        print(f"refusing to write {PROD_TAB!r} without --i-mean-it. "
              f"Build against the sandbox first.")
        return 2
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.datetime.now(CENTRAL).date())
    tab = PROD_TAB if args.real else SANDBOX_TAB
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"=== Country Sales Board — {tab!r} — {mode} — today={today} ===")

    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(tab)
    grid = _retry(ws.get_all_values)

    # ---- rollover (Tuesdays; self-healing no-op otherwise) ----
    # Runs BEFORE the pull so the fill targets the week the board ends up on:
    # on a Tuesday the board closes WE n and opens WE n+1, and the pull is then
    # aligned to n+1. Doing it after would fill the old week and then wipe it.
    rollover_summary = None
    ok, why = cr.needs_rollover(grid, today)
    if ok and not args.enable_rollover:
        print(f"  ⚠ rollover NEEDED ({why}) but --enable-rollover not set — "
              f"filling only")
    elif ok or args.force_rollover:
        rollover_summary = cr.run_rollover(sh, ws, today=today,
                                           dry_run=args.dry_run,
                                           force=args.force_rollover)
        if not args.dry_run:
            grid = _retry(ws.get_all_values)     # rows/columns have moved
    else:
        print(f"  rollover check: {why}")

    # The week the board is showing AFTER any roll — what the pull must cover.
    board_dates = wk.sheet_week(
        find_daily_section(grid, cf.BLOCK_LABEL).day_col_by_daynum, today)

    # ---- pull ----
    if args.from_csv:
        from automations.org_sales_board import section_pull as sp
        print(f"  parsing {args.from_csv} (offline)…")
        pull = sp.parse_crosstab_byday(cp.SPEC, Path(args.from_csv), today)
        print(f"  parsed {len(pull)} ICD owner(s)")
    else:
        from automations.shared.tableau_patchright import tableau_session
        try:
            with tableau_session() as page:
                if args.last_week:
                    pull = cp.pull_icd_days(page, OUT_DIR, last_week=True,
                                            today=today)
                else:
                    pull, _sheet = cp.pull_icd_days_aligned(
                        page, OUT_DIR, board_dates, today=today)
        except cp.NoDataYet as e:
            # Not a failure: Tableau hides an empty worksheet, so this is the
            # normal state before the week's first sales land.
            # Not necessarily fine: 'no worksheet' is the normal state only
            # before a week's first sales land. If YESTERDAY is already blank on
            # the board, this is a silent outage, so let the check decide.
            print(f"  ⏸ {e}")
            print("=== nothing to fill — checking the board anyway ===")
            return _verify(ws, today, args.dry_run, args.no_verify)

    # ---- plan ----

    # A rep appended at the BOTTOM of the day block is filled but falls outside
    # the tab's fixed =SUMIF/=SUM ranges, so they'd count toward nothing. Say so
    # before writing rather than let the board quietly under-report.
    fgrid = _retry(lambda: ws.get_all_values(value_render_option="FORMULA"))
    for line in cf.audit_aggregate_coverage(fgrid, grid):
        print(line)

    plan = cf.plan_day_fill(grid, pull, today=today)
    if not plan.updates:
        for line in plan.log:      # apply_plan prints the log; short-circuit here
            print(line)
        print("=== no writes planned — checking the board anyway ===")
        return _verify(ws, today, args.dry_run, args.no_verify)

    # ---- apply ----
    apply_plan(ws, plan, dry_run=args.dry_run)

    # Delta box: grow the 'Total for week -> Last week' formula to the days
    # completed so far (Tue = Monday, Wed = Mon+Tue, …) so it compares against
    # the same stretch of last week that 'Total this week' covers of this one.
    # The Tuesday rollover resets it to Monday; this walks it forward daily.
    from automations.org_sales_board.rollover import apply_delta_lastweek
    apply_delta_lastweek(ws, today=today, dry_run=args.dry_run)

    # Top box ('Current vs Prior Weeks'): the Grand Total of 'Sales (Last Week)'
    # and 'Sales ( 4 Week AVG)' must cover the SAME elapsed days as 'Sales -
    # This Week' — one more day each day, and back to Monday-only the moment the
    # week rolls. NOTHING here rebuilt them, so J12/J13 kept whatever the
    # rollover left: the full 7-day enumeration of the closed week, re-pointed at
    # the new top of the WE stack. Every percentage in that box then compared one
    # elapsed day against a finished week (Eve 2026-08-04: -84% on a Tuesday
    # morning). org's planner is reused verbatim; its delta half is off because
    # apply_delta_lastweek above already owns that box.
    from automations.org_sales_board.elapsed_totals import apply_elapsed_totals
    apply_elapsed_totals(ws, today=today, dry_run=args.dry_run,
                         include_delta=False)

    if rollover_summary and rollover_summary.get("rolled"):
        print(f"  rolled {rollover_summary['closed']} -> "
              f"{rollover_summary['new_label']}")
    print(f"=== {len(plan.updates)} cell write(s) "
          f"{'planned' if args.dry_run else 'applied'} — done ===")
    # Unmatched board ICDs are WARNED, never a non-zero exit. Verified
    # 2026-07-27 against the probe week: the 5 that don't match (Edgar Muniz II,
    # Niko Figueroa, Mason Davis, Mary Maya, Jacob Morgan) are simply absent
    # from the view's 111 owners and sit at 0 in the VAs' own frozen columns for
    # both WE 07.19 and WE 07.26 — inactive reps whose board rows nobody
    # removed. Exiting INCOMPLETE on them would fail this report every single
    # morning for a permanent, correct 0 (the trap org_sales_board's daily
    # compare fell into). The warning is the signal; a rep who WAS producing and
    # suddenly appears here is the case that wants an ICD Aliases row.
    if plan.unmatched:
        print(f"  ⚠ {len(plan.unmatched)} board ICD(s) had no match in the "
              f"pull and were filled 0 — expected for inactive reps, but a "
              f"PRODUCING rep here means a name drift (add an ICD Aliases "
              f"row): {plan.unmatched}")
    return _verify(ws, today, args.dry_run, args.no_verify)


if __name__ == "__main__":
    sys.exit(main())

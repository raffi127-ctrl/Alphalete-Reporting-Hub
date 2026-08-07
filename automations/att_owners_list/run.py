#!/usr/bin/env python3
"""ATT Owners List — the Friday roster fill.

Every Friday, for the week that closed on Sunday:

  1. PULL   'Sales By ICD (ATT) (V2) (LW2) (2)' off ATT Tracker 2.1 - D2D /
            D2D 1-PAGERV2 (Internet Only) — the 'D2D PAGE 2 LAST WEEK' page.
  2. FILL   that week's column on the 'ATT Owners List' tab: a name where they
            sold, a red blank where they didn't, a new row (yellow) for anyone
            who has never been on the list.
  3. TELL   #revision-emails who joined and who didn't sell. Nobody is removed:
            a red cell says "not this week", and the weeks beside it say whether
            it was a quiet week or the end of the road.
  4. SEED   any brand-new owner into all THREE Country Sales Board boxes, so
            their sales have somewhere to land the very next morning.

  python -m automations.att_owners_list.run                    # sandbox, live write
  python -m automations.att_owners_list.run --dry-run          # plan only
  python -m automations.att_owners_list.run --post             # send the Slack note
  python -m automations.att_owners_list.run --real --i-mean-it # the REAL tab
  python -m automations.att_owners_list.run --from-csv P       # offline, no browser
  python -m automations.att_owners_list.run --rebuild          # realign history
  python -m automations.att_owners_list.run --week 2026-08-02  # a specific week

SANDBOX BY DEFAULT, like every other board fill here: `--real` targets the tab
people read and is refused without `--i-mean-it`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from automations.recruiting_report.fill import open_by_key, _retry
from automations.att_owners_list import board as B
from automations.att_owners_list import pull as P
from automations.att_owners_list import sheet as S
from automations.att_owners_list import slack_post as SP

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"
PROD_TAB = "ATT owners list"          # the tab's own casing — matched loosely
SANDBOX_TAB = "ATT owners list (sandbox)"
BOARD_TAB = "Country Sales Board"
BOARD_SANDBOX_TAB = "Country Sales Board (sandbox)"
OUT_DIR = Path("output")
CENTRAL = ZoneInfo("America/Chicago")   # [[project_central-time-for-texas-reports]]


def last_sunday(today: dt.date) -> dt.date:
    """The Sunday that closed the week this report is about — the most recent
    one STRICTLY BEFORE today. On a Friday that is five days back; on a Sunday
    it is the week before, never the day itself, because the day isn't over
    and Tableau's 'last week' worksheet doesn't include it either."""
    return today - dt.timedelta(days=((today.weekday() + 1) % 7) or 7)


def _find_ws(sh, title: str):
    want = title.strip().lower()
    ws = next((w for w in sh.worksheets() if w.title.strip().lower() == want),
              None)
    if ws is None:
        raise ValueError(f"Tab {title!r} not found in the workbook.")
    return ws


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="plan and print everything; write nothing")
    ap.add_argument("--real", action="store_true",
                    help=f"target {PROD_TAB!r} instead of the sandbox tab")
    ap.add_argument("--i-mean-it", action="store_true",
                    help="required alongside --real")
    ap.add_argument("--post", action="store_true",
                    help="actually send the Slack note (default: print it)")
    ap.add_argument("--no-board", action="store_true",
                    help="skip seeding new owners into the Country Sales Board")
    ap.add_argument("--from-csv", metavar="PATH",
                    help="parse an already-downloaded crosstab instead of "
                         "opening Tableau (offline engine check)")
    ap.add_argument("--week", metavar="YYYY-MM-DD",
                    help="the week-ending Sunday to fill (default: the last "
                         "one). The pull must actually cover it.")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="override today's date (testing/backfill)")
    ap.add_argument("--rebuild", action="store_true",
                    help="realign the tab's history so every row is ONE "
                         "person, then fill as usual")
    ap.add_argument("--overwrite", action="store_true",
                    help="rewrite the week's column even if it already holds "
                         "something different")
    args = ap.parse_args(argv)

    if args.real and not args.i_mean_it:
        print(f"refusing to write {PROD_TAB!r} without --i-mean-it. "
              f"Build against the sandbox first.")
        return 2
    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.datetime.now(CENTRAL).date())
    want = (dt.date.fromisoformat(args.week) if args.week else last_sunday(today))
    tab = PROD_TAB if args.real else SANDBOX_TAB
    board_tab = BOARD_TAB if args.real else BOARD_SANDBOX_TAB
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"=== ATT Owners List — {tab!r} — {mode} — today={today} "
          f"— week ending {want.isoformat()} ===")

    # ---- pull ----------------------------------------------------------
    if args.from_csv:
        print(f"  parsing {args.from_csv} (offline)…")
        pull = P.parse(Path(args.from_csv), near=today)
        print(f"  parsed {len(pull.owners)} owner(s), "
              f"{pull.days[0].isoformat()}..{pull.days[-1].isoformat()}")
    else:
        from automations.shared.tableau_patchright import tableau_session
        try:
            with tableau_session() as page:
                pull = P.pull_last_week(page, OUT_DIR, near=today)
        except P.NoDataYet as e:
            print(f"  ⏸ {e}")
            print("=== nothing to fill ===")
            return 0

    # The view is pinned to a RELATIVE week, so never assume it is the week we
    # asked for — read the dates back and refuse a mismatch rather than write
    # one week's roster into another week's column.
    if pull.week_ending != want:
        print(f"  ❌ the view returned the week ending "
              f"{pull.week_ending.isoformat()} "
              f"({pull.days[0].isoformat()}..{pull.days[-1].isoformat()}), not "
              f"{want.isoformat()}. Nothing written — pass "
              f"--week {pull.week_ending.isoformat()} if that IS the week you "
              f"want filled.")
        return 1

    # ---- sheet ---------------------------------------------------------
    sh = open_by_key(SHEET_ID)
    ws = _find_ws(sh, tab)
    grid = _retry(ws.get_all_values)
    layout = S.find_layout(grid)
    print(f"  tab: header row {layout.header_row}, names "
          f"{layout.first_name_row}..{layout.last_name_row}, "
          f"{len(layout.week_cols)} week column(s) "
          f"({layout.weeks[0].isoformat()}..{layout.weeks[-1].isoformat()})")
    for line in S.health(grid, layout):
        print(line)

    if args.rebuild:
        block, stats = S.plan_rebuild(grid, layout)
        problems = S.verify_rebuild(grid, layout, block)
        if problems:
            print("  ❌ rebuild REFUSED — it would change the data, not just "
                  "the layout:")
            for p in problems:
                print(f"      {p}")
            return 1
        print(f"  rebuild: {stats['rows_before']} row(s) → {stats['people']} "
              f"person row(s) across {stats['weeks']} week(s); every column's "
              f"name set verified identical")
        if args.dry_run:
            print("  (dry-run — not applying the rebuild)")
        else:
            _backup(grid, layout, tab)
            S.apply_rebuild(ws, layout, block)
            grid = _retry(ws.get_all_values)
            layout = S.find_layout(grid)

    col, made = S.ensure_week_col(ws, grid, want, dry_run=args.dry_run)
    if made and not args.dry_run:
        grid = _retry(ws.get_all_values)
        layout = S.find_layout(grid)

    existing = [S._cell(grid, r - 1, col - 1)
                for r in range(layout.first_name_row, layout.last_name_row + 1)]
    had = sum(1 for v in existing if v)

    from automations.focus_office_att.aliases import load_aliases
    aliases = load_aliases()
    plan = S.plan_week(grid, layout, pull, aliases=aliases)
    for line in plan.log:
        print(line)
    if plan.new:
        print(f"  NEW: {', '.join(sorted(plan.new))}")
    if plan.back:
        print(f"  BACK: {', '.join(sorted(plan.back))}")
    if plan.dropped:
        print(f"  STOPPED SELLING: {', '.join(sorted(plan.dropped))}")

    if had and not args.overwrite:
        want_names = {u["values"][0][0] for u in plan.values if u["values"][0][0]}
        if want_names != {v for v in existing if v}:
            print(f"  ❌ column {S._col(col)} already holds {had} name(s) that "
                  f"differ from this pull — someone filled it by hand. "
                  f"Re-run with --overwrite to replace it.")
            return 1
        print(f"  column {S._col(col)} already matches this pull "
              f"({had} names) — rewriting is a no-op")

    if args.dry_run:
        print(f"  (dry-run) would write {len(plan.values)} cell(s), insert "
              f"{len(plan.inserts)} row(s)")
    else:
        S.apply_inserts(ws, plan, layout)
        if plan.inserts:                    # rows moved — re-plan on the truth
            grid = _retry(ws.get_all_values)
            layout = S.find_layout(grid)
            plan2 = S.plan_week(grid, layout, pull, aliases=aliases)
            plan2.new, plan2.back, plan2.kept = plan.new, plan.back, plan.kept
            plan2.dropped, plan2.still_out = plan.dropped, plan.still_out
            plan = plan2
        S.apply_week(ws, plan)
        grid = _retry(ws.get_all_values)
        layout = S.find_layout(grid)
        updates, fmts = S.plan_summary(grid, layout)
        S.apply_summary(ws, updates, fmts)
        S.freeze_header(ws, layout)

    # ---- the Country Sales Board ---------------------------------------
    board_result = None
    if plan.new and not args.no_board:
        print(f"  Country Sales Board ({board_tab!r}):")
        bws = _find_ws(sh, board_tab)
        board_result = B.sync(bws, plan.new, aliases=aliases,
                              dry_run=args.dry_run)
    elif plan.new:
        print("  --no-board: not touching the Country Sales Board")

    # ---- Slack ----------------------------------------------------------
    text = SP.build(plan, pull, board=board_result, tab=tab)
    SP.post(text, dry_run=not args.post)

    print(f"=== done — {plan.in_program} owner(s) in the program for "
          f"WE {want.isoformat()} ===")
    return 0


def _backup(grid, layout, tab: str) -> None:
    """CSV of the name block before a rebuild touches it. Cheap, and the only
    thing that makes the rebuild reversible without Sheets' version history."""
    import csv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"att_owners_backup_{dt.date.today().isoformat()}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for r in range(1, layout.last_name_row + 1):
            w.writerow(grid[r - 1] if r - 1 < len(grid) else [])
    print(f"  backup → {path}")


if __name__ == "__main__":
    sys.exit(main())

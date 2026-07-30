"""August Owner Showdown — daily competition fill.

Two $5,000 competitions on the KTS tab (Raf, 2026-07-29):
  * PERSONAL PRODUCTION — new-internet sales in each owner's own codes, daily.
  * REP COUNT           — active rep count, polled on Sundays only.
Both sorted high→low after every fill.

  python -m automations.owner_showdown.run --dry-run
  python -m automations.owner_showdown.run --sandbox --dry-run
  python -m automations.owner_showdown.run --sandbox            # write sandbox tab
  python -m automations.owner_showdown.run --week 2026-08-02    # pin personal week
  python -m automations.owner_showdown.run --personal-only
  python -m automations.owner_showdown.run --make-sandbox       # dup KTS -> sandbox

Sandbox-first + --dry-run until Raf says "use the real tab / roll out".
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback

from automations.owner_showdown import roster, sheet_fill, tableau_pull

SANDBOX_TAB = "KTS SANDBOX"


def _current_we_sunday(today: dt.date) -> dt.date:
    """Week-ending Sunday (Mon..Sun week) for `today`."""
    # Monday=0 .. Sunday=6; days until Sunday.
    return today + dt.timedelta(days=(6 - today.weekday()))


def make_sandbox():
    ws, sh = sheet_fill.open_tab(sheet_fill.TAB)
    for w in sh.worksheets():
        if w.title == SANDBOX_TAB:
            print(f"sandbox tab {SANDBOX_TAB!r} already exists (gid={w.id})")
            return
    dup = sh.duplicate_sheet(source_sheet_id=ws.id, new_sheet_name=SANDBOX_TAB)
    print(f"created sandbox tab {SANDBOX_TAB!r} (gid={dup.id}) from {ws.title!r}")


def _print_plan(title, sec, rows_plan, unmatched, a1):
    print(f"\n=== {title} — writes to {a1} ===", flush=True)
    print(f"{'#':>2}  {'OWNER':22}  TOTAL  cells", flush=True)
    for i, r in enumerate(rows_plan, 1):
        ncells = len([v for v in r['cells'].values()])
        print(f"{i:>2}  {r['name']:22}  {str(r['total']):>5}  "
              f"({ncells} day cells)", flush=True)
    if unmatched:
        print(f"  ⚠ NOT MATCHED in source ({len(unmatched)}): "
              f"{', '.join(unmatched)}", flush=True)


def _run(args) -> int:
    if args.make_sandbox:
        make_sandbox()
        return 0

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    we = dt.date.fromisoformat(args.week) if args.week else _current_we_sunday(today)
    tab = SANDBOX_TAB if args.sandbox else sheet_fill.TAB
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"Owner Showdown → tab {tab!r} · run date {today} · personal week "
          f"ending {we} · {mode}", flush=True)

    ws, sh = sheet_fill.open_tab(tab)
    vals = ws.get_all_values()

    do_personal = not args.repcount_only
    do_rep = not args.personal_only

    # --- pull from Tableau (one ownerville session) ---
    sales = {}
    counts = {}
    if not args.skip_download:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=True) as page:
            if do_personal:
                sales = tableau_pull.pull_personal_sales(we, page=page)
            if do_rep:
                counts = tableau_pull.pull_rep_counts(we_sunday=we, page=page)
    else:
        print("  --skip-download: no Tableau pull (existing cells only)", flush=True)

    # --- PERSONAL PRODUCTION ---
    if do_personal:
        sec = sheet_fill.discover(vals, sheet_fill.SEC_PERSONAL)
        merged = sheet_fill.read_existing_personal(sec, vals)
        for owner_norm, daymap in sales.items():
            if owner_norm in roster.SALES_SET:
                merged.setdefault(owner_norm, {}).update(daymap)
        # 0-fill: every competitor gets 0 on ELAPSED days of the pulled week
        # that they didn't sell (Raf: "if they have 0, enter 0"). Future days
        # stay blank until they arrive; earlier weeks keep their sheet values.
        week_dates = [we - dt.timedelta(days=i) for i in range(7)]
        covered = [d for d in week_dates if d in sec.date_cols and d <= today]
        for owner_norm in roster.SALES_SET:
            dm = merged.setdefault(owner_norm, {})
            for d in covered:
                dm.setdefault(d, 0)
        rows_plan, unmatched = sheet_fill.plan_personal(sec, merged)
        a1, _ = sheet_fill.write_section(ws, sec, rows_plan, args.dry_run)
        _print_plan("PERSONAL PRODUCTION", sec, rows_plan, unmatched, a1)

    # --- REP COUNT (Sundays only) ---
    if do_rep:
        sec = sheet_fill.discover(vals, sheet_fill.SEC_REP)
        snapshots = sheet_fill.read_existing_repcount(sec, vals)
        is_sunday = today.weekday() == 6 or (args.date and we == today)
        cur_sunday = today if today in sec.date_cols else we
        if counts and cur_sunday in sec.date_cols:
            snap = {o: c for o, c in counts.items() if o in roster.REPCOUNT_SET}
            snapshots[cur_sunday] = snap
            print(f"  rep-count snapshot stored for {cur_sunday} "
                  f"({len(snap)} competitors matched)", flush=True)
        elif counts:
            print(f"  ⚠ run date/week {cur_sunday} is not a Sunday column — "
                  f"rep count NOT written (polls are Sundays only)", flush=True)
        rows_plan, unmatched = sheet_fill.plan_repcount(sec, snapshots)
        a1, _ = sheet_fill.write_section(ws, sec, rows_plan, args.dry_run)
        _print_plan("REP COUNT (growth)", sec, rows_plan, unmatched, a1)

    print(f"\n{'(dry-run — nothing written)' if args.dry_run else 'written ✓'}",
          flush=True)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="August Owner Showdown fill")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sandbox", action="store_true", help="use KTS SANDBOX tab")
    p.add_argument("--make-sandbox", action="store_true",
                   help="duplicate KTS -> KTS SANDBOX and exit")
    p.add_argument("--week", help="WE Sunday (YYYY-MM-DD) for the personal pull")
    p.add_argument("--date", help="override run date (YYYY-MM-DD)")
    p.add_argument("--personal-only", action="store_true")
    p.add_argument("--repcount-only", action="store_true")
    p.add_argument("--skip-download", action="store_true")
    args = p.parse_args(argv)
    try:
        return _run(args)
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

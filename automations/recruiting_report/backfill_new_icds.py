"""Backfill the RECRUITING half (rows 2-23) of ICD tabs that AppStream has
only just started seeing.

Why this exists (and why `run.py` can't do it): `run.py` step 2.5 promotes
every `sales_only` tab flagged `promote_when_visible` the moment AppStream sees
its office, and backfills it in that same run — but

  * `--only` takes ONE tab, and the promotion is a one-shot: the run that
    promotes rewrites the mapping, so a second `--only` run finds nothing
    pending, sees a populated tab (its OPT block is already filled) and writes
    only the current week. Four new ICDs => three of them end up with one
    column.
  * its backfill window is `--backfill-weeks` (default 10) of the TEMPLATE's
    columns, not the tab's. A tab whose history starts earlier than the
    template keeps those weeks blank, silently.

So this walks the columns of EACH TAB, over one AppStream session, and writes
tab by tab so a dropped session keeps whatever already landed. Writes through
`fill.fill_office_section`, which skips None — a week AppStream has nothing for
leaves the existing cells alone, and nothing is ever cleared.

Usage:
  # everything AppStream can newly see, whole history, no writes
  python -m automations.recruiting_report.backfill_new_icds --captainship Carlos --dry-run

  # for real
  python -m automations.recruiting_report.backfill_new_icds --captainship Carlos

  # a tab that is already `confirmed` (nothing left to promote)
  python -m automations.recruiting_report.backfill_new_icds --captainship Carlos \
      --tabs "Jackie Leroy,Jeff Starr" --since 2026-04-05
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from typing import Dict, List, Optional


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Backfill the recruiting rows of newly-visible ICD tabs.")
    ap.add_argument("--captainship", default=os.environ.get("CAPTAINSHIP", "Raf"),
                    help="Which focus report: Raf (default) or Carlos.")
    ap.add_argument("--tabs",
                    help="Comma-separated sheet tabs to backfill. Default: the "
                         "tabs promoted out of sales_only by THIS run.")
    ap.add_argument("--week", help="Last Sheet WE Sunday to fill, YYYY-MM-DD "
                                   "(default: the most recent Sunday).")
    ap.add_argument("--since", help="First Sheet WE Sunday to fill, YYYY-MM-DD "
                                    "(default: the tab's first weekly column).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and print, write nothing.")
    return ap.parse_args(argv)


def _most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def _backfill_tab(page, sh, office: dict, week: dt.date,
                  since: Optional[dt.date], dry_run: bool) -> bool:
    """Fetch + write one tab's recruiting history. True when something landed."""
    from . import fetch_office, fill

    tab = office["sheet_tab"]
    office_id, owner = office["office_id"], office["as_owner"]
    ws = fill._retry(sh.worksheet, tab)
    values = fill._retry(ws.get_all_values)
    # Weeks come from THIS TAB's date headers, never from the template and
    # never from a column index — templates change, headers survive.
    sunday_to_col = fill.find_sunday_columns(values, header_row_idx=0)
    metric_rows = fill.find_office_metric_rows(ws, anchor_row=1, max_rows=30)
    if not metric_rows:
        print(f"\n{tab}: no recruiting metric rows on the tab — skipping")
        return False

    weeks = sorted(s for s in sunday_to_col
                   if s <= week and (since is None or s >= since))
    if not weeks:
        print(f"\n{tab}: no weekly columns in range — skipping")
        return False
    print(f"\n=== {tab} (office {office_id} / {owner}) — {len(metric_rows)} "
          f"metric rows, {len(weeks)} week(s) {weeks[0]} -> {weeks[-1]}")

    week_data: Dict[dt.date, dict] = {}
    for w in weeks:
        # Recruiting lags AppStream by one week: the Sheet WE column `w` is
        # filled from AppStream's PRIOR week, the settled one. Same convention
        # as run.py.
        as_week = w - dt.timedelta(days=7)
        try:
            metrics = fetch_office.fetch_one(page, office_id, owner, as_week)
        except Exception as exc:  # noqa: BLE001 — one bad week shouldn't sink the tab
            print(f"  WE {w} <- AS {as_week}: FAILED ({type(exc).__name__}: {exc})")
            continue
        if metrics == {}:
            print(f"  WE {w} <- AS {as_week}: office not accessible — stopping this tab")
            break
        if not metrics:
            print(f"  WE {w} <- AS {as_week}: no data")
            continue
        week_data[w] = metrics
        print(f"  WE {w} <- AS {as_week}: pull={metrics.get('pull')} "
              f"applies={metrics.get('total_applies')} "
              f"1st_booked={metrics.get('first_booked')} "
              f"job_offered={metrics.get('job_offered')}")

    if not week_data:
        print(f"  {tab}: nothing fetched — nothing written")
        return False
    for line in fill.fill_office_section(ws, metric_rows, sunday_to_col,
                                         week_data, dry_run, label=tab):
        print(line)
    return True


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    # fill.py reads CAPTAINSHIP at import time to pick the sheet / template /
    # mapping, so it has to be set BEFORE the import below.
    os.environ["CAPTAINSHIP"] = args.captainship

    from . import fill
    from .list_all_offices import refresh_offices_from_page
    from automations.shared.tableau_patchright import appstream_direct_session

    week = dt.date.fromisoformat(args.week) if args.week else _most_recent_sunday()
    since = dt.date.fromisoformat(args.since) if args.since else None
    wanted = [t.strip() for t in args.tabs.split(",")] if args.tabs else None

    mapping = fill.load_mapping()
    sh = fill.open_sheet()
    print(f"captainship={args.captainship} | sheet: {sh.title} | "
          f"target week (WE) {week} | dry_run={args.dry_run}")

    rc = 0
    with appstream_direct_session(verbose=True) as page:
        # Refresh the office list LIVE first — all-offices.json is a cache and
        # would never show access granted today.
        try:
            print(refresh_offices_from_page(page))
        except Exception as exc:  # noqa: BLE001
            print(f"office-list refresh FAILED: {type(exc).__name__}: {exc}")
            return 1

        promoted = fill.promote_visible_sales_only(mapping, dry_run=args.dry_run)
        for p in promoted:
            print(f"[promoted] {p['sheet_tab']} -> office {p['office_id']} "
                  f"({p['as_owner']}); sales_only -> confirmed")

        by_tab = {c["sheet_tab"]: c for c in mapping["confirmed"]}
        if wanted is None:
            targets = [p["sheet_tab"] for p in promoted]
            if not targets:
                print("nothing was promoted this run — pass --tabs to backfill "
                      "a tab that is already confirmed")
                return 0
        else:
            targets = wanted
            unknown = [t for t in targets if t not in by_tab]
            if unknown:
                print(f"[STOP] not confirmed in the mapping (AppStream still "
                      f"can't see them?): {', '.join(unknown)}")
                targets = [t for t in targets if t in by_tab]
                rc = 1

        for tab in targets:
            if not _backfill_tab(page, sh, by_tab[tab], week, since, args.dry_run):
                rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

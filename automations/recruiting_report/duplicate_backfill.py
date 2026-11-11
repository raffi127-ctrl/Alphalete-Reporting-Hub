"""Rewrite ONLY the Duplicate rows of Focus Report tabs, N weeks back.

Raf's Loom (2026-11-10, "How to Calculate Duplicate Percentage Accurately"):
  * row "Removed From Process Emails" -> renamed "Duplicate/Already Interviewed"
    and filled with the duplicate count from AppStream's View Details box
  * Total Applies  = Emails Received (weekly total)
  * Duplicate %    = duplicates / Emails Received

Touches three rows and the one label — every other row is left alone (a
re-fetch of old weeks would otherwise quietly move numbers people already saw).

Usage:
  # preview tab, 8 weeks, no writes
  python -m automations.recruiting_report.duplicate_backfill --tabs "Marcellus Butler" --dry-run
  # every confirmed tab of the captainship
  python -m automations.recruiting_report.duplicate_backfill --all --weeks 8
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from typing import List, Optional

ROWS = ("removed_from_process_emails", "total_applies", "duplicate_pct")


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--captainship", default=os.environ.get("CAPTAINSHIP", "Raf"))
    ap.add_argument("--tabs", help="Comma-separated tabs (default: the preview tabs).")
    ap.add_argument("--all", action="store_true", help="Every confirmed tab.")
    ap.add_argument("--weeks", type=int, default=8, help="How many weeks back (default 8).")
    ap.add_argument("--week", help="Last WE Sunday, YYYY-MM-DD (default: most recent Sunday).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true", help="Print the View Details boxes read.")
    return ap.parse_args(argv)


def _most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    os.environ["CAPTAINSHIP"] = args.captainship
    from . import fetch_office, fill
    from automations.shared.tableau_patchright import appstream_direct_session

    week = dt.date.fromisoformat(args.week) if args.week else _most_recent_sunday()
    mapping = fill.load_mapping()
    by_tab = {c["sheet_tab"]: c for c in mapping["confirmed"]}
    if args.all:
        targets = list(by_tab)
    elif args.tabs:
        targets = [t.strip() for t in args.tabs.split(",") if t.strip()]
    else:
        targets = sorted(t for t in fill.DUPLICATE_V2_TABS if t != "*")
    unknown = [t for t in targets if t not in by_tab]
    for t in unknown:
        print(f"[SKIP] {t}: not a confirmed tab in the mapping")
    targets = [t for t in targets if t in by_tab]
    # The tabs named here get the new definition for this run.
    fill.DUPLICATE_V2_TABS.update(targets)

    sh = fill.open_sheet()
    print(f"captainship={args.captainship} | {sh.title} | {len(targets)} tab(s) | "
          f"{args.weeks} week(s) to WE {week} | dry_run={args.dry_run}")
    rc = 0
    with appstream_direct_session(verbose=True) as page:
        for tab in targets:
            office = by_tab[tab]
            try:
                ws = fill._retry(sh.worksheet, tab)
                values = fill._retry(ws.get_all_values)
            except Exception as exc:  # noqa: BLE001
                print(f"\n{tab}: can't open tab ({exc}) — skipped")
                rc = 1
                continue
            sunday_to_col = fill.find_sunday_columns(values, header_row_idx=0)
            weeks = sorted(s for s in sunday_to_col if s <= week)[-args.weeks:]
            if office.get("siblings"):
                print(f"  note: {tab} has sibling offices {office['siblings']} — "
                      f"only the top section is done here")
            rows = fill.find_office_metric_rows(ws, anchor_row=1, max_rows=30)
            rows = {k: v for k, v in rows.items() if k in ROWS}
            if not rows:
                print(f"\n{tab}: no Duplicate rows on the tab — skipped")
                continue
            print(f"\n=== {tab} (office {office['office_id']}) {weeks[0]} -> {weeks[-1]}")
            data = {}
            for w in weeks:
                as_week = w - dt.timedelta(days=7)   # same one-week lag as run.py
                try:
                    m = fetch_office.fetch_one(page, office["office_id"], office["as_owner"], as_week)
                except Exception as exc:  # noqa: BLE001
                    print(f"  WE {w}: FAILED ({type(exc).__name__}: {exc})")
                    continue
                if m == {}:
                    print(f"  WE {w}: office not accessible — stopping this tab")
                    break
                print(f"  WE {w} <- AS {as_week}: emails={m.get('emails_received')} "
                      f"dup={m.get('duplicates')} -> {m.get('duplicate_pct_v2')}% "
                      f"(old: removed={m.get('removed_from_process_emails')} "
                      f"applies={m.get('total_applies')} dup%={m.get('duplicate_pct')})")
                if args.debug:
                    dbg = fetch_office.LAST_DUPLICATE_DEBUG
                    print(f"    box={dbg.get('processBox')} ids={dbg.get('boxIds')}")
                    for r in dbg.get("reasons") or []:
                        print(f"    reason {r}")
                data[w] = {k: v for k, v in m.items()
                           if k in ROWS or k in ("duplicates", "total_applies_v2", "duplicate_pct_v2")}
            if data:
                for line in fill.fill_office_section(ws, rows, sunday_to_col, data,
                                                     args.dry_run, label=tab):
                    print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

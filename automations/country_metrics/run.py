"""Country Metrics — weekly fill.

Pulls the Metrics + PRODUCT SALES crosstabs from Tableau, aggregates per
captainship + COUNTRY, and writes the target week's column on the
'Country Metrics' tab (sandbox Sheet). Run Thursdays for the just-ended week.

  python -m automations.country_metrics.run                 # most-recent Sunday
  python -m automations.country_metrics.run --week 2026-05-24
  python -m automations.country_metrics.run --dry-run
  python -m automations.country_metrics.run --skip-download # reuse cached CSVs
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.country_metrics import pull, fill, slack_post


def _most_recent_sunday(today: dt.date | None = None) -> dt.date:
    """The weekending (WE Sunday) of the most-recently-finished week.

    This drives the weekly cadence WITHOUT any 'which column did I fill last'
    bookkeeping: the fill locates the column by this date's header in row 1, so
    - each Thursday targets a NEW week (e.g. 5/24 -> col V, next Thu 5/31 -> col
      W) — the column advances on its own, never repeats; and
    - running twice in the SAME week resolves to the SAME Sunday -> the SAME
      column, so it OVERWRITES that week's cells (idempotent) rather than
      appending a duplicate column.
    """
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="country_metrics")
    ap.add_argument("--week", help="Weekending Sunday YYYY-MM-DD (matches the "
                    "date header + the Tableau week filter). Default: most "
                    "recent Sunday.")
    ap.add_argument("--dry-run", action="store_true", help="Don't write to the Sheet.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the cached crosstab CSVs in output/.")
    ap.add_argument("--no-slack", action="store_true",
                    help="Skip the Slack 'report ready' post in #level10-alphalete.")
    ap.add_argument("--slack-only", action="store_true",
                    help="Skip the Tableau pull + Sheet write; only post the "
                         "Slack 'report ready' note. Use when the week's column "
                         "is already filled and you just want the message.")
    args = ap.parse_args(argv)

    today = dt.date.today()
    week = dt.date.fromisoformat(args.week) if args.week else _most_recent_sunday(today)
    print(f"=== Country Metrics — weekending {week.isoformat()} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}"
          f"{', SLACK-ONLY' if args.slack_only else ''}) ===")

    if not args.slack_only:
        print("Step 1: pull + aggregate from Tableau…")
        res = pull.gather(week, skip_download=args.skip_download, logfn=print)
        print(f"  roster: {res['roster_size']} owners mapped to teams")
        print(f"  AIR orders folded into the Owners-Over-100 totals: {res.get('air_total', 0)}")
        if res["missing_cols"]:
            print(f"  WARNING: Metrics columns not found: {res['missing_cols']}")
        if res["unmatched"]:
            print(f"  NOTE: {len(res['unmatched'])} owner(s) in PRODUCT SALES not in any "
                  f"team roster (counted in COUNTRY via ORG, not in a captainship): "
                  f"{', '.join(res['unmatched'])}")

        # Quick per-section summary so gaps are obvious before/after the write.
        for section, d in res["data"].items():
            keys = ",".join(sorted(k for k in d if d[k] not in (None, "")))
            print(f"  {section:<8} -> {keys or '(no data)'}")

        print("Step 2: write the week column on 'Country Metrics'…")
        ws = fill.open_ws()
        fill.write(ws, res["data"], week, args.dry_run, logfn=print)
    else:
        print("Slack-only: skipping Tableau pull + Sheet write.")

    # --- Slack note (best-effort; never fails the run) ---
    if args.no_slack:
        print("  (Slack post skipped — --no-slack.)")
    else:
        sres = slack_post.post_update(week, today, dry_run=args.dry_run)
        if args.dry_run:
            pass  # post_update already printed the dry-run lines
        elif sres.get("ok"):
            tag_note = (f", tagged {sres['tagged']}" if sres.get("thread_created")
                        else "")
            print(f"  ✓ Slack: posted to '{sres.get('thread_title')}' thread "
                  f"({sres.get('ts')}{', created thread' if sres.get('thread_created') else ''}{tag_note})")
        else:
            print(f"  ⚠ Slack post FAILED (sheet fill is done — run still OK): "
                  f"{sres.get('error')}")

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

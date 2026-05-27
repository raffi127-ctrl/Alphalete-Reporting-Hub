"""Ongoing Cancel Report — daily run.

Flow:
  1. Pull Internet Cancel Rates (Daily) Crosstab via patchright (RafExpanded view).
  2. Parse + render a single PNG (60 reps × last 7 days, color-coded).
  3. Find today's 'Metrics M/DD' parent thread in #alphalete-sales.
  4. Reply in that thread with the image + comment 'Ongoing Cancel'.

Pre-requisite (manual until all metrics are automated): someone posts the
'Metrics M/DD' header thread in #alphalete-sales BEFORE this report runs.

Run with --dry-run to do steps 1+2 (image saved to disk) without posting.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.ongoing_cancel import pull, render, slack_post


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ongoing_cancel")
    p.add_argument("--dry-run", action="store_true",
                   help="Render the image but don't post to Slack.")
    p.add_argument("--date", default=None,
                   help="Override today's date (YYYY-MM-DD).")
    args = p.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    scratch = Path("/tmp")
    csv_path = scratch / "ongoing_cancel.csv"
    img_path = scratch / "ongoing_cancel.png"

    print(f"=== Ongoing Cancel — {today.isoformat()} ===")
    print("Step 1: Tableau Crosstab pull (RafExpanded custom view)...")
    pull.fetch_crosstab(csv_path, verbose=False)
    print(f"  ✓ {csv_path}")

    print("Step 2: Parse + render image...")
    parsed = pull.parse(csv_path, days=7)
    render.render(parsed, img_path)
    print(f"  ✓ {img_path}   ({len(parsed['rows'])} reps × {len(parsed['days'])} days)")

    print(f"Step 3: Slack post to #alphalete-sales / today's Metrics thread...")
    try:
        result = slack_post.post_reply_with_image(img_path, today=today,
                                                  dry_run=args.dry_run)
    except slack_post.SlackPostError as e:
        print(f"  ✗ {e}")
        return 1
    print(f"  ✓ {result}")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

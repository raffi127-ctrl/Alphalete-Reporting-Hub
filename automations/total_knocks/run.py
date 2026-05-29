"""Run — the Total Knocks daily pipeline (Hub entry point).

  1. Scrape Ownerville 'Disposition by Rep' for the day prior.
  2. Replace the rep list on the Total Knocks tab (daily snapshot).
  3. Render the full table as a PNG.
  4. Post the PNG as a reply in today's 'Metrics for:' thread in
     #alphalete-sales, with a 🚪 reaction on the parent.

Default target date = yesterday. The Hub action runs this with no args.

Flags:
  --test-tab   write to the '… - TEST' sandbox tab instead of prod
  --no-slack   do everything EXCEPT post to Slack (write + render only)
  --dry-run    scrape + render a preview only; NO Sheet write, NO Slack post
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

# Make emoji / checkmarks safe on the Windows console (cp1252 default).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.total_knocks import fill as _fill
from automations.total_knocks import render as _render
from automations.total_knocks.pull import SHEET_COLUMNS, pull_disposition_day

# 🚪 reaction on the parent Metrics post (short name, no colons).
REACT_EMOJI = "door"
# Comment leads with the workflow emoji + Title Case title, matching every
# other metrics post (🚫 Canceled Orders, 🌐 New Internet Churn).
SLACK_COMMENT = "🚪 Total Knocks"


def _yesterday() -> dt.date:
    return dt.date.today() - dt.timedelta(days=1)


def _preview_rows(rows: list[dict]) -> tuple[list[str], list[list[str]]]:
    """Build (header, string-rows) from in-memory records — used for the
    --dry-run image when nothing was written to the Sheet."""
    ordered = _fill._sorted_rows(rows)
    out = []
    for rec in ordered:
        out.append([str(_fill._cell_value(c, rec.get(c, ""))) for c in SHEET_COLUMNS])
    return list(SHEET_COLUMNS), out


def run(target: dt.date | None = None, *, test_tab: bool = False,
        no_slack: bool = False, dry_run: bool = False) -> int:
    target = target or _yesterday()
    tab = _fill.TAB_TEST if test_tab else _fill.TAB_PROD
    print(f"[total_knocks] Starting — data date {target.isoformat()} "
          f"-> tab {tab!r}", flush=True)
    print("[total_knocks] Opening Ownerville… please don't touch or close "
          "the browser window while it works.", flush=True)

    # 1. Pull.
    target, rows = pull_disposition_day(target)
    print(f"[total_knocks] Scraped {len(rows)} rep(s) from Disposition by Rep.",
          flush=True)
    if not rows:
        print("[total_knocks] ⚠ No rows for that day — nothing to post.",
              flush=True)
        return 1

    # 2. Fill (skipped on dry-run).
    if dry_run:
        print("[total_knocks] DRY-RUN — skipping Sheet write.", flush=True)
    else:
        stats = _fill.fill_total_knocks(rows, tab=tab)
        print(f"[total_knocks] Wrote {stats['reps']} rep(s) to "
              f"{stats['write_range']}.", flush=True)

    # 3. Render.
    if dry_run:
        header, srows = _preview_rows(rows)
        img = _render.render_table(header, srows, target)
    else:
        img = _render.render_from_sheet(target, tab=tab)
    print(f"[total_knocks] Rendered image -> {img}", flush=True)

    # 4. Slack.
    if dry_run or no_slack:
        why = "dry-run" if dry_run else "--no-slack"
        print(f"[total_knocks] Skipping Slack post ({why}).", flush=True)
        print("[total_knocks] ✅ Finished.", flush=True)
        return 0

    from automations.shared.slack_metrics_post import post_reply_with_image
    comment = f"{SLACK_COMMENT} — {target.strftime('%b')} {target.day}"
    resp = post_reply_with_image(
        Path(img), comment=comment, react_emoji=REACT_EMOJI,
    )
    if resp.get("ok"):
        print(f"[total_knocks] ✅ Posted to today's Metrics thread "
              f"(file {resp.get('file')}).", flush=True)
    else:
        print(f"[total_knocks] ⚠ Slack response: {resp}", flush=True)
    print("[total_knocks] ✅ Finished.", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Total Knocks daily pipeline.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--test-tab", action="store_true",
                    help="write to the '… - TEST' sandbox tab instead of prod")
    ap.add_argument("--no-slack", action="store_true",
                    help="write + render but do NOT post to Slack")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview only: no Sheet write, no Slack post")
    args = ap.parse_args()
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    return run(target, test_tab=args.test_tab, no_slack=args.no_slack,
               dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

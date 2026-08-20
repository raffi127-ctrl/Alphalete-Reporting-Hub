"""Re-post today's BOX Order Log workbook into the thread that ALREADY posted.

For the day a formatting change lands after the morning thread has gone out.
The thread is right, the workbook in it is the old layout, and waiting until
tomorrow means a day of people reading the version we just fixed.

Same shape as `backfill_tier` — find today's parent by its dated header, reply
to it as Lucy, never start a second thread — with one deliberate difference:
this DOES re-upload a file the thread already carries, because that's the whole
point. Dedupe is therefore on the caption's marker phrase (_MARK), not on the
filename, which is identical to the copy posted this morning.

Runs on LUCY 2: the reply has to come from Lucy, and a laptop run would post as
whoever's token is on the laptop. DRY-RUN by default; --post does it.

    lucy rerun box_order_log_repost                     # dry, both channels
    lucy rerun box_order_log_repost --post              # do it
    lucy rerun box_order_log_repost --channel C0… --post   # one channel only

Python 3.9 on Lucy 2 — deferred annotations, no runtime `X | Y`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from .backfill_tier import find_parent, header_title
from .run import OUTPUT_DIR, TARGETS

# The caption. Its first line is what people see in the thread; _MARK is the
# part this script recognises as its own, so running twice can't double-post.
_MARK = "updated pending tab"
CAPTION = (
    "\U0001F4E6 Re-posted with the {} — use this one, not the workbook "
    "above.\n"
    "Pending orders is now two sections, each grouped by sales rep: the ones "
    "that aren't yellow first, then the yellow ones. Ready For Booking now "
    "shows yellow."
).format(_MARK)


def workbook_for(day: dt.date) -> Path:
    """The daily workbook run.py writes for `day`."""
    return OUTPUT_DIR / "BOX Order Log {}.xlsx".format(day.strftime("%m-%d-%Y"))


def already_reposted(client, channel: str, ts: str) -> bool:
    """Has this script already replied in this thread?"""
    try:
        rs = client.conversations_replies(channel=channel, ts=ts, limit=200)
    except Exception:                                     # noqa: BLE001
        return False
    for m in rs.get("messages", [])[1:]:
        if _MARK in (m.get("text") or "").lower():
            return True
    return False


def _targets(one: str) -> List[Tuple[str, str]]:
    if one:
        return [(one, one)]
    return list(TARGETS)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Re-post today's BOX Order Log workbook into today's "
                    "already-posted thread")
    ap.add_argument("--post", action="store_true",
                    help="actually upload (default: dry run)")
    ap.add_argument("--channel", default="",
                    help="one channel id (default: every channel in "
                         "run.TARGETS)")
    ap.add_argument("--file", metavar="XLSX",
                    help="workbook to post (default: today's in output/)")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="the thread's date (default: today)")
    args = ap.parse_args(argv)

    day = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    book = Path(args.file) if args.file else workbook_for(day)
    if not book.exists():
        print("✗ no workbook at {} — build it first with `lucy rerun "
              "box_order_log` (that runs --sheet --xlsx, no post).".format(book),
              file=sys.stderr)
        return 1

    # Guard against posting the pre-change layout: the workbook has to be
    # newer than the code that changed it, or there's nothing to re-post.
    stamp = dt.datetime.fromtimestamp(book.stat().st_mtime)
    print("Workbook: {}\n  built {}".format(book, stamp.strftime("%Y-%m-%d %H:%M")))
    if stamp.date() != day:
        print("  ⚠ that file was built on {}, not {} — re-run "
              "`lucy rerun box_order_log` first if you want the day's own "
              "numbers.".format(stamp.date(), day))

    from automations.shared import slack_metrics_post as smp

    rc = 0
    for name, channel in _targets(args.channel):
        os.environ["METRICS_CHANNEL_ID"] = channel
        client = smp._client()
        parent = find_parent(client, channel, day)
        if not parent:
            print("✗ {}: no '{}' thread — skipped.".format(
                name, header_title(day)), file=sys.stderr)
            rc = 1
            continue
        ts = parent.get("thread_ts") or parent.get("ts")
        if already_reposted(client, channel, ts):
            print("✓ {}: already re-posted in this thread — "
                  "nothing to do.".format(name))
            continue
        if not args.post:
            print("  DRY RUN — would reply in {} (ts={}) with {}\n"
                  "    caption: {}".format(
                      name, ts, book.name, CAPTION.replace("\n", "\n             ")))
            continue
        client.files_upload_v2(
            channel=channel, thread_ts=ts, file=str(book),
            filename=book.name, title=book.stem, initial_comment=CAPTION,
        )
        print("  ✓ {}: posted into today's thread".format(name))

    if not args.post:
        print("\n  re-run with --post")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

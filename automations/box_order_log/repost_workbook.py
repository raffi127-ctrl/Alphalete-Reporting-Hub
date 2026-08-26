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

# The caption is always LEAD + one line saying what changed. Building it that
# way (rather than letting --note replace the whole thing) keeps _MARK in every
# caption we send, and _MARK is how a second run recognises its own reply and
# declines to double-post.
_MARK = "re-posted"
_LEAD = "\U0001F4E6 Re-posted — use this one, not the workbook above."
_LEAD_PENDING = ("\U0001F5C2\uFE0F Pending orders, re-posted — use this one, "
                 "not the image above.")
DEFAULT_NOTE = (
    "Pending orders is now two sections, each grouped by sales rep: the ones "
    "that aren't yellow first, then the yellow ones. Ready For Booking now "
    "shows yellow.")


def caption_for(note: str = "", pending: bool = False) -> str:
    """LEAD + one line on what changed. The lead names the right artifact —
    telling people not to use "the workbook above" under an IMAGE sends them
    looking for the wrong attachment."""
    lead = _LEAD_PENDING if pending else _LEAD
    return lead + "\n" + (note.strip() or DEFAULT_NOTE)


def workbook_for(day: dt.date) -> Path:
    """The daily workbook run.py writes for `day`."""
    return OUTPUT_DIR / "BOX Order Log {}.xlsx".format(day.strftime("%m-%d-%Y"))


def pending_image_for(day: dt.date) -> Path:
    """The daily Pending Orders image run.py writes for `day` (run.out_pending)."""
    return OUTPUT_DIR / "BOX Pending Orders {}.png".format(
        day.strftime("%m-%d-%Y"))


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
    ap.add_argument("--pending", action="store_true",
                    help="re-post the Pending Orders IMAGE instead of the "
                         "workbook (backfill_pending can't: it dedupes on the "
                         "caption and the thread already has one)")
    ap.add_argument("--note", metavar="TEXT", default="",
                    help="one line saying what changed (default: the "
                         "pending-tab layout note)")
    args = ap.parse_args(argv)

    day = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    if args.file:
        book = Path(args.file)
    else:
        book = pending_image_for(day) if args.pending else workbook_for(day)
    if not book.exists():
        print("✗ nothing at {} — build it first with `lucy rerun "
              "box_order_log` (that runs --sheet --xlsx, no post).".format(book),
              file=sys.stderr)
        return 1

    # Guard against posting the pre-change layout: the workbook has to be
    # newer than the code that changed it, or there's nothing to re-post.
    stamp = dt.datetime.fromtimestamp(book.stat().st_mtime)
    print("{}: {}\n  built {}".format("Image" if args.pending else "Workbook",
                                      book, stamp.strftime("%Y-%m-%d %H:%M")))
    if stamp.date() != day:
        print("  ⚠ that file was built on {}, not {} — re-run "
              "`lucy rerun box_order_log` first if you want the day's own "
              "numbers.".format(stamp.date(), day))

    caption = caption_for(args.note, pending=args.pending)

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
                      name, ts, book.name,
                      caption.replace("\n", "\n             ")))
            continue
        client.files_upload_v2(
            channel=channel, thread_ts=ts, file=str(book),
            filename=book.name, title=book.stem, initial_comment=caption,
        )
        print("  ✓ {}: posted into today's thread".format(name))

    if not args.post:
        print("\n  re-run with --post")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

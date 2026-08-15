"""Add the Box Tier Bonus Rep Level board to a BOX Order Log thread ALREADY posted.

One-off backfill for the day the board was wired in (2026-08-15): that morning's
thread went out at 8:32 without the board, and Megan asked for it added to the
live thread — *and* for the parent header to list it, so the header keeps
matching what's actually in the thread.

It finds today's parent by its dated header, uploads the board as a reply, and
edits the header to add the line. Both steps are idempotent: a board already in
the thread is left alone, and a header that already lists it isn't re-edited, so
running this twice changes nothing.

Runs on LUCY 2 — only Lucy's own token can edit Lucy's message, and a laptop run
would post as Megan. DRY-RUN by default; --post does the work.

    lucy rerun box_order_log_tier_backfill                      # dry
    lucy rerun box_order_log_tier_backfill --post               # do it

Python 3.9 on Lucy 2 — deferred annotations, no runtime `X | Y`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Optional

from . import tier_bonus
from .run import CHANNEL, OUTPUT_DIR


def header_title(day: dt.date) -> str:
    """The parent's first line, minus the bold markers — what we search for."""
    return "BOX Order Log — {}".format(day.strftime("%B %d, %Y"))


def find_parent(client, channel: str, day: dt.date) -> Optional[dict]:
    """Today's parent message in `channel`, or None."""
    oldest = dt.datetime.combine(day, dt.time.min).timestamp()
    resp = client.conversations_history(channel=channel, oldest=str(oldest),
                                        limit=200)
    needle = header_title(day)
    for msg in resp.get("messages", []):
        if needle in (msg.get("text") or ""):
            return msg
    return None


def already_in_thread(client, channel: str, ts: str) -> bool:
    """Is the board already a reply here? Matches on the board NAME, which is in
    both the caption and the filename, rather than the emoji-led caption — Slack
    may store an emoji as a shortcode or as the character."""
    try:
        rs = client.conversations_replies(channel=channel, ts=ts, limit=200)
    except Exception:                                     # noqa: BLE001
        return False
    for m in rs.get("messages", [])[1:]:
        if tier_bonus.BOARD_NAME.lower() in (m.get("text") or "").lower():
            return True
        for f in m.get("files", []) or []:
            name = "{} {}".format(f.get("name", ""), f.get("title", ""))
            if tier_bonus.BOARD_NAME.lower() in name.lower():
                return True
    return False


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Add the Box Tier Bonus Rep Level board to today's already-"
                    "posted BOX Order Log thread")
    ap.add_argument("--post", action="store_true",
                    help="actually upload + edit (default: dry run)")
    ap.add_argument("--channel", default=CHANNEL[1],
                    help="channel id holding the thread (default {} {})".format(
                        CHANNEL[0], CHANNEL[1]))
    ap.add_argument("--owner", default=tier_bonus.DEFAULT_OWNER,
                    help="Owner Name to slice the board to")
    ap.add_argument("--image", metavar="PNG",
                    help="use this PNG instead of capturing a fresh one")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="the thread's date (default: today)")
    args = ap.parse_args(argv)

    day = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())

    from automations.shared import slack_metrics_post as smp
    os.environ["METRICS_CHANNEL_ID"] = args.channel
    client = smp._client()

    parent = find_parent(client, args.channel, day)
    if not parent:
        print("✗ no '{}' thread found in {} — nothing to backfill. (Wrong "
              "channel, wrong day, or the thread was never posted.)".format(
                  header_title(day), args.channel), file=sys.stderr)
        return 1
    ts = parent.get("thread_ts") or parent.get("ts")
    text = parent.get("text") or ""
    print("Found today's thread: ts={}".format(ts))

    have_board = already_in_thread(client, args.channel, ts)
    needs_line = tier_bonus.BOARD_NAME not in text
    print("  board already in thread : {}".format("yes" if have_board else "no"))
    print("  header lists the board  : {}".format("no" if needs_line else "yes"))
    if have_board and not needs_line:
        print("\n✅ Nothing to do — the thread already has the board and says so.")
        return 0

    # Capture only if we're actually going to use it.
    img = Path(args.image) if args.image else None
    if not have_board and img is None:
        img, warning = tier_bonus.capture(OUTPUT_DIR, args.owner, day=day)
        if warning:
            print("  ⚠ {}".format(warning))

    new_text = text.rstrip() + "\n" + tier_bonus.TIER_LINE if needs_line else text
    if not args.post:
        print("\n  DRY RUN — nothing sent. Would:")
        if not have_board:
            print("    • reply with {}".format(img))
            print("      caption: {}".format(tier_bonus.TIER_LINE))
        if needs_line:
            print("    • edit the header to:\n      "
                  + new_text.replace("\n", "\n      "))
        print("\n  re-run with --post")
        return 0

    if not have_board:
        client.files_upload_v2(
            channel=args.channel, thread_ts=ts, file=str(img),
            filename=img.name, title=img.stem,
            initial_comment=tier_bonus.TIER_LINE,
        )
        print("  ✓ board posted into the thread")
    if needs_line:
        # Only Lucy can edit Lucy's message — this is why it runs on Lucy 2.
        client.chat_update(channel=args.channel, ts=parent.get("ts"),
                           text=new_text)
        print("  ✓ header updated to list the board")
    print("\n✅ Today's thread now carries the {}.".format(tier_bonus.BOARD_NAME))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Add the Box Tier Bonus Rep Level board to a BOX Order Log thread ALREADY posted.

One-off backfill for the day the board was wired in (2026-08-15): that morning's
thread went out at 8:32 without the board, and Megan asked for it added to the
live thread — *and* for the parent header to list it, so the header keeps
matching what's actually in the thread.

It finds today's parent by its dated header, uploads the board as a reply, and
edits the header to add the line — in EVERY channel the thread posts to
(run.TARGETS), not just the first. Both steps are idempotent: a board already in
the thread is left alone, and a header that already lists it isn't re-edited, so
running this twice changes nothing.

Still the handle to reach for whenever the board misses a live thread, not only
the day it was wired in — tier_bonus.capture_quietly is built so a flake there
costs the thread the picture and nothing else, which leaves exactly this gap.
2026-09-01: a mid-run `git pull` left the process holding an OLD
tableau_patchright next to a NEW capture.py, the import failed, and the thread
posted without the board.

Runs on LUCY 2 — only Lucy's own token can edit Lucy's message, and a laptop run
would post as Megan. DRY-RUN by default; --post does the work.

    lucy rerun box_order_log_tier_backfill                      # dry, both rooms
    lucy rerun box_order_log_tier_backfill --post               # do it
    lucy rerun box_order_log_tier_backfill --channel C0… --post  # one room

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
from .run import (OUTPUT_DIR, PAYOUT_LINE, PENDING_LINE, TARGETS,
                  WORKBOOK_LINE)

# The attachment lines, in thread order. Rebuilding the header from these is
# what lets this script fix WORDING too, not just add a missing line — Megan
# trimmed every line's trailing description on 2026-08-15 and the already-posted
# header needed to match. A line is recognised by its leading emoji, so an
# edited caption still replaces its old version instead of stacking beside it.
# PENDING_LINE joined on 2026-09-01: Carlos's Pending Orders image became
# the thread's third attachment on 2026-08-25 and this list never learned
# about it, so a header rewrite read it as somebody's extra note and moved
# it BELOW the tier line — a header listing the four attachments in an
# order the thread does not have. The order here IS the thread's order.
ATTACHMENT_LINES = [WORKBOOK_LINE, PAYOUT_LINE, PENDING_LINE,
                    tier_bonus.TIER_LINE]


def line_key(line: str) -> str:
    """A wording-and-emoji-proof identity for a header line.

    Matching the emoji prefix was the obvious way to recognise our own lines and
    it FAILED on the live thread 2026-08-15: the rewrite appended three new lines
    above the three old ones instead of replacing them, doubling the header. So
    identity ignores the emoji entirely (raw character OR `:shortcode:`, since
    Slack can hand either one back) and ignores everything after the em-dash —
    which is exactly the descriptive tail that gets reworded. What's left is the
    name of the thing, which is what actually identifies the line.
    """
    import re
    s = (line or "").strip()
    s = re.sub(r"^(?::[a-z0-9_+\-]+:|[^\w\s])+\s*", "", s)   # leading emoji
    s = re.split(r"[—–]|\s-\s", s)[0]                        # drop the tail
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def canonical_header(existing: str, day: dt.date, with_tier: bool = True) -> str:
    """The header this thread SHOULD have: its title, the attachment lines as
    currently worded, then anything else that was in it (a --note, say).

    Extra lines are preserved because they're someone's words; only the
    attachment lines are ours to rewrite.
    """
    lines = (existing or "").split("\n")
    title = lines[0] if lines and lines[0].strip() else "*{}*".format(
        header_title(day))
    ours = {line_key(ln) for ln in ATTACHMENT_LINES}
    extras = [ln for ln in lines[1:]
              if ln.strip() and line_key(ln) not in ours]
    keep = ATTACHMENT_LINES if with_tier else ATTACHMENT_LINES[:-1]
    return "\n".join([title] + list(keep) + extras)


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


def _board_for(day, args, state: dict):
    """The PNG to reply with — captured once and reused for every channel.

    The thread is per-channel but the board is not: capturing it twice would pay
    for a second Tableau session, and could hand the two rooms two different
    pictures if a rep's number moved between the pulls.
    """
    if state.get("img") is None:
        if args.image:
            state["img"] = Path(args.image)
        else:
            img, warning = tier_bonus.capture(OUTPUT_DIR, args.owner, day=day)
            if warning:
                print("  ⚠ {}".format(warning))
            state["img"] = img
    return state["img"]


def _one_channel(client, name: str, channel: str, day, args,
                 state: dict) -> bool:
    """Backfill one room. True when that room ended up correct."""
    print("\n{} ({})".format(name, channel))
    parent = find_parent(client, channel, day)
    if not parent:
        print("  ✗ no '{}' thread here — nothing to backfill. (Wrong channel, "
              "wrong day, or the thread was never posted.)".format(
                  header_title(day)), file=sys.stderr)
        return False
    ts = parent.get("thread_ts") or parent.get("ts")
    text = parent.get("text") or ""
    print("  thread ts               : {}".format(ts))

    have_board = already_in_thread(client, channel, ts)
    new_text = canonical_header(text, day)
    needs_header = new_text.strip() != text.strip()
    print("  board already in thread : {}".format("yes" if have_board else "no"))
    print("  header already correct  : {}".format("no" if needs_header else "yes"))
    if have_board and not needs_header:
        print("  ✅ nothing to do — this thread already has the board and "
              "says so.")
        return True

    # Capture only if we are actually going to use it.
    img = None if have_board else _board_for(day, args, state)

    if not args.post:
        print("  DRY RUN — nothing sent. Would:")
        if not have_board:
            print("    • reply with {}".format(img))
            print("      caption: {}".format(tier_bonus.TIER_LINE))
        if needs_header:
            print("    • rewrite the header to:\n      "
                  + new_text.replace("\n", "\n      "))
        return True

    if not have_board:
        client.files_upload_v2(
            channel=channel, thread_ts=ts, file=str(img),
            filename=img.name, title=img.stem,
            initial_comment=tier_bonus.TIER_LINE,
        )
        print("  ✓ board posted into the thread")
    if needs_header:
        # Only Lucy can edit Lucy's message — this is why it runs on Lucy 2.
        client.chat_update(channel=channel, ts=parent.get("ts"), text=new_text)
        print("  ✓ header rewritten to the current lines")
    return True


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Add the Box Tier Bonus Rep Level board to today's already-"
                    "posted BOX Order Log thread")
    ap.add_argument("--post", action="store_true",
                    help="actually upload + edit (default: dry run)")
    # EVERY room by default (2026-09-01). The thread has gone to two channels
    # since 2026-08-15 (run.TARGETS) but this defaulted to the first one, so a
    # backfill left #a-players-b2b short unless someone remembered to run it a
    # second time with --channel — and a board missing from one room reads as
    # completely fine in the room that got it. Same default as repost_workbook.
    ap.add_argument("--channel", default="",
                    help="one channel id (default: every channel in "
                         "run.TARGETS — {})".format(
                             ", ".join(n for n, _ in TARGETS)))
    ap.add_argument("--owner", default=tier_bonus.DEFAULT_OWNER,
                    help="Owner Name to slice the board to")
    ap.add_argument("--image", metavar="PNG",
                    help="use this PNG instead of capturing a fresh one")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="the thread's date (default: today)")
    args = ap.parse_args(argv)

    day = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    targets = ([(args.channel, args.channel)] if args.channel
               else list(TARGETS))

    from automations.shared import slack_metrics_post as smp
    os.environ["METRICS_CHANNEL_ID"] = targets[0][1]
    client = smp._client()

    state, done, missed = {"img": None}, [], []
    for name, channel in targets:
        # Per-channel try/except, the same rule run.py posts under: a room that
        # fails is recorded and the other one still gets its board.
        try:
            ok = _one_channel(client, name, channel, day, args, state)
        except Exception as exc:                          # noqa: BLE001
            ok = False
            print("  ✗ {}: {}".format(type(exc).__name__,
                                      str(exc).splitlines()[0][:160]),
                  file=sys.stderr)
        (done if ok else missed).append(name)

    if not args.post:
        print("\n  re-run with --post")
        return 0 if not missed else 1
    if missed:
        print("\n⚠ not backfilled: {}".format(", ".join(missed)),
              file=sys.stderr)
    if not done:
        return 1
    print("\n✅ {} now carries the {}.".format(
        " + ".join(done), tier_bonus.BOARD_NAME))
    return 0 if not missed else 1


if __name__ == "__main__":
    raise SystemExit(main())

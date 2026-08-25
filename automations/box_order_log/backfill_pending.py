"""Put the Pending Orders image into a BOX thread that already went out.

The day a section is ADDED, the morning thread posted before the code existed:
it carries the workbook, the payout board and the tier board, and its header
doesn't mention a pending image. This drops the missing reply in and edits the
header to match. From the next morning the normal run posts it in order and
this is dead weight — it stays because "we shipped a new section, backfill
today's thread" is not a one-time event.

RUN IT WHERE LUCY'S TOKEN IS (Lucy 2). Two reasons, both hard: a reply posted
from a laptop goes out under whoever's token that laptop holds, and Slack only
lets the AUTHOR edit a message, so the header can only be fixed by the identity
that wrote it.

No second Tableau hit — it rebuilds from the CSV the morning pass already
pulled, and refuses rather than guessing if that file isn't there.

DRY-RUN BY DEFAULT: builds the image and prints what it would do. Add --post.

    python -m automations.box_order_log.backfill_pending            # dry run
    python -m automations.box_order_log.backfill_pending --post
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import clean, payout, pending, pending_png, png
from .run import OUTPUT_DIR, PENDING_LINE, TARGETS

# The accepted-by-supplier board is REPLACED, not just added: the morning
# thread already carries one under the plain PAYOUT_LINE, and two boards that
# look alike is how somebody reads the stale one. Slack can't edit an uploaded
# file, so the caption has to do the work of saying which is current — the same
# reasoning as review_gate's "never a second link".
BOARD_LINE = ("\U0001F4B5 Accepted by supplier — updated: adds the Submitted "
              "to Supplier column. Use this one, not the earlier board above.")


def todays_csv(today: dt.date) -> Tuple[Optional[Path], bool]:
    """(path, needs_owner_filter) for the crosstab this morning's pass wrote.

    Carlos's own run writes box_order_log_<date>.csv already scoped to his
    view; the per-office pass writes one shared box_order_log_all_<date>.csv
    covering every office, which has to be filtered down.
    """
    own = OUTPUT_DIR / "box_order_log_{}.csv".format(today.isoformat())
    if own.exists():
        return own, False
    shared = OUTPUT_DIR / "box_order_log_all_{}.csv".format(today.isoformat())
    if shared.exists():
        return shared, True
    return None, False


def header_text(today: dt.date) -> str:
    """The parent line the morning run posts — how we find the thread."""
    return "*BOX Order Log — {}*".format(today.strftime("%B %d, %Y"))


def find_thread(client, channel: str, today: dt.date) -> Optional[dict]:
    """Today's BOX parent message in `channel`, or None if it never posted."""
    start = dt.datetime(today.year, today.month, today.day)
    oldest = str(int((start - dt.datetime(1970, 1, 1)).total_seconds()) - 86400)
    wanted = header_text(today)
    cursor = None
    for _page in range(5):
        kw = {"channel": channel, "oldest": oldest, "limit": 200}
        if cursor:
            kw["cursor"] = cursor
        resp = client.conversations_history(**kw)
        for m in resp["messages"]:
            if (m.get("text") or "").startswith(wanted):
                return m
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return None


def marker(line: str) -> str:
    """The emoji-free words of a caption — what an 'is it already there?' test
    can actually compare.

    Slack stores a posted \U0001F5C2\uFE0F as `:card_index_dividers:`, so the
    literal caption NEVER matches the text read back and every check silently
    returns False. That made a re-run double-post the image and append a second
    header line — the exact duplicate this module exists to avoid. Compare the
    words instead; they survive the round trip.
    """
    return re.sub(r"^[^A-Za-z0-9]+", "",
                  re.sub(r":[a-z0-9_+-]+:", "", line or "")).strip()


def already_there(client, channel: str, ts: str, line: str) -> bool:
    """True if a reply carrying `line` is already hanging off this thread.

    Makes a second run a no-op instead of a duplicate — a queued job can be
    re-run by anyone, and a double-posted board is exactly the confusion the
    one-thread-a-day marker exists to prevent.
    """
    want = marker(line)
    resp = client.conversations_replies(channel=channel, ts=ts, limit=200)
    for m in resp["messages"][1:]:
        if want and want in marker(m.get("text") or "") and m.get("files"):
            return True
    return False


def run(today: Optional[dt.date] = None, *, post: bool = False,
        owner_office: str = "", from_file: str = "", board: bool = False,
        pending_image: bool = True,
        targets: Optional[List[Tuple[str, str]]] = None) -> int:
    today = today or dt.date.today()
    targets = targets if targets is not None else TARGETS

    if from_file:
        src, needs_filter = Path(from_file), bool(owner_office)
    else:
        src, needs_filter = todays_csv(today)
    if not src or not src.exists():
        print("✗ no crosstab for {} in {} — this has to run on the machine "
              "that pulled this morning (Lucy 2).".format(today, OUTPUT_DIR),
              file=sys.stderr)
        return 2
    if needs_filter and not owner_office:
        print("✗ {} covers every office — pass --owner-office so we don't "
              "post one office's deals to another's thread.".format(src.name),
              file=sys.stderr)
        return 2

    sales, _stats = clean.load(src, owner_office=owner_office)
    if not sales:
        print("✗ no sales in {} — refusing to post an empty board."
              .format(src.name), file=sys.stderr)
        return 1

    # (caption, file) in the order they should land in the thread.
    uploads: List[Tuple[str, Path]] = []
    if pending_image:
        work = pending.build(sales, today=today)
        out = OUTPUT_DIR / "BOX Pending Orders {}.png".format(
            today.strftime("%m-%d-%Y"))
        pending_png.render(work, out)
        print("  built {}  ({} open: {})".format(
            out.name, work["count"],
            ", ".join(s["title"] for s in work["sections"])))
        uploads.append((PENDING_LINE, out))
    if board:
        tables = payout.build_week_tables(sales, today)
        board_out = OUTPUT_DIR / "BOX Payout {}.png".format(
            today.strftime("%m-%d-%Y"))
        png.render(tables, board_out, subtitle=png.SUBTITLE)
        subm = sum(r["submitted"] for r in tables["this"]["rows"])
        print("  built {}  (submitted this week: {})".format(
            board_out.name, subm))
        uploads.append((BOARD_LINE, board_out))
    if not uploads:
        print("✗ nothing to post — pass --board and/or leave the pending image on",
              file=sys.stderr)
        return 2

    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    who = client.auth_test()
    print("  posting as {} ({})".format(who.get("user"), who.get("user_id")))

    rc = 0
    for name, cid in targets:
        parent = find_thread(client, cid, today)
        if not parent:
            print("  ✗ {}: no BOX thread for {} — nothing to backfill".format(
                name, today))
            rc = rc or 1
            continue
        ts = parent["ts"]
        for line, path in uploads:
            if already_there(client, cid, ts, line):
                print("  = {}: {} already in the thread — skipped".format(
                    name, path.name))
                continue
            if not post:
                print("  [dry-run] {}: would reply to {} with {}".format(
                    name, ts, path.name))
                continue
            client.files_upload_v2(channel=cid, thread_ts=ts, file=str(path),
                                   filename=path.name, title=path.stem,
                                   initial_comment=line)
            print("  ✓ {}: posted {}".format(name, path.name))

        # Header last, so it never lists an attachment that isn't there yet.
        # Only the pending image earns a NEW header line — the updated board
        # replaces one the header already names, so adding a second 💵 line
        # would make the contents list disagree with itself.
        if (not post or not pending_image
                or marker(PENDING_LINE) in marker(parent["text"])):
            continue
        try:
            client.chat_update(channel=cid, ts=ts,
                               text=parent["text"] + "\n" + PENDING_LINE)
            print("    header updated")
        except Exception as exc:                          # noqa: BLE001
            # Only the author can edit. Say so plainly rather than failing the
            # whole backfill — the images are the part people read.
            print("    ⚠ header NOT updated ({}) — run this from the machine "
                  "whose token posted the thread".format(exc), file=sys.stderr)
            rc = rc or 1
    return rc


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="backfill the Pending Orders image into today's BOX thread")
    ap.add_argument("--post", action="store_true",
                    help="actually post (default: build + describe only)")
    ap.add_argument("--date", default="",
                    help="YYYY-MM-DD, defaults to today")
    ap.add_argument("--owner-office", default="",
                    help="required only when the day's pull is the shared "
                         "all-offices crosstab")
    ap.add_argument("--from-file", default="",
                    help="use this crosstab instead of the day's pull")
    ap.add_argument("--board", action="store_true",
                    help="also post the accepted-by-supplier board, rebuilt "
                         "with the Submitted to Supplier column")
    ap.add_argument("--no-pending", action="store_true",
                    help="skip the pending image (use with --board when the "
                         "pending one already went out)")
    ap.add_argument("--channel", default="",
                    help="post to ONE channel id instead of both of Carlos's")
    ap.add_argument("--channel-name", default="",
                    help="display name for --channel")
    args = ap.parse_args(argv)

    day = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    targets = ([(args.channel_name or args.channel, args.channel)]
               if args.channel else None)
    return run(day, post=args.post, owner_office=args.owner_office,
               from_file=args.from_file, board=args.board,
               pending_image=not args.no_pending, targets=targets)


if __name__ == "__main__":
    raise SystemExit(main())

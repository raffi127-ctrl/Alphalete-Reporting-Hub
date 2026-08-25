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
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import clean, pending, pending_png
from .run import OUTPUT_DIR, PENDING_LINE, TARGETS


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


def already_there(client, channel: str, ts: str) -> bool:
    """True if a pending image is already hanging off this thread.

    Makes a second run a no-op instead of a duplicate — a queued job can be
    re-run by anyone, and a double-posted board is exactly the confusion the
    one-thread-a-day marker exists to prevent.
    """
    resp = client.conversations_replies(channel=channel, ts=ts, limit=200)
    for m in resp["messages"][1:]:
        if PENDING_LINE in (m.get("text") or "") and m.get("files"):
            return True
    return False


def run(today: Optional[dt.date] = None, *, post: bool = False,
        owner_office: str = "", from_file: str = "",
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

    work = pending.build(sales, today=today)
    out = OUTPUT_DIR / "BOX Pending Orders {}.png".format(
        today.strftime("%m-%d-%Y"))
    pending_png.render(work, out)
    print("  built {}  ({} open: {})".format(
        out.name, work["count"],
        ", ".join(s["title"] for s in work["sections"])))

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
        if already_there(client, cid, ts):
            print("  = {}: pending image already in the thread — skipped"
                  .format(name))
            continue
        if not post:
            print("  [dry-run] {}: would reply to {} and {}".format(
                name, ts,
                "append the header line" if PENDING_LINE not in parent["text"]
                else "leave the header alone (already lists it)"))
            continue
        client.files_upload_v2(channel=cid, thread_ts=ts, file=str(out),
                               filename=out.name, title=out.stem,
                               initial_comment=PENDING_LINE)
        print("  ✓ {}: posted".format(name))
        # Header last, so it never lists an attachment that isn't there yet.
        # It goes on the END: today the image lands after the tier board, and
        # the header should read in the order the thread actually reads.
        if PENDING_LINE in parent["text"]:
            print("    header already lists it")
            continue
        try:
            client.chat_update(channel=cid, ts=ts,
                               text=parent["text"] + "\n" + PENDING_LINE)
            print("    header updated")
        except Exception as exc:                          # noqa: BLE001
            # Only the author can edit. Say so plainly rather than failing the
            # whole backfill — the image is the part people read.
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
    ap.add_argument("--channel", default="",
                    help="post to ONE channel id instead of both of Carlos's")
    ap.add_argument("--channel-name", default="",
                    help="display name for --channel")
    args = ap.parse_args(argv)

    day = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    targets = ([(args.channel_name or args.channel, args.channel)]
               if args.channel else None)
    return run(day, post=args.post, owner_office=args.owner_office,
               from_file=args.from_file, targets=targets)


if __name__ == "__main__":
    raise SystemExit(main())

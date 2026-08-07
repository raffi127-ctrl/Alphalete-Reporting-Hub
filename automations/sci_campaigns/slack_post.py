"""SCI Campaigns — the weekly 'done' note.

Posted to the **#l10-alphalete** channel (Raf asked to move it here off the old
group DM, 2026-08-04). The channel gets **one top-level message per MONTH**; every
week's note is a **reply** in that month's thread, and Rafael & Maud are @-tagged
ONLY on the first message of a new thread (Eve, 2026-08-07):

    SCI Campaigns - August 2026            <- top-level, one per MONTH
      └ WE 8/1 Complete
        @Rafael @Maud                      <- pings them once, at creation
      └ WE 8/8 Complete                    <- later weeks: no mention
      └ WE 8/15 Complete

The mentions stay inside the thread so the channel itself never fills with
@-mentions (Megan, 2026-08-04). The month comes from the week-ending date, so
WE 8/1 lands in the August thread.

Text only, by design — Megan asked for a notice, not the numbers.

Posts as Lucy via the xoxp USER token (`_client`) — the same token every other
channel post uses. The bot token is DM-only and is NOT on the mini, so it must
NOT be used here ([[reference-lucy-slack-tokens]]). #l10-alphalete is private, so
Lucy Reporting (alphaletereporting@gmail.com) must be a member — she already is,
as int_wow_penetration / fiber_activations post there.

  python -m automations.sci_campaigns.slack_post --week 2026-07-18          # dry-run
  python -m automations.sci_campaigns.slack_post --week 2026-07-18 --post
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from automations.shared import slack_metrics_post as smp

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CHANNEL_ID = "C075PCEL92M"          # #l10-alphalete (private)
# Slack user IDs (not names) so the mention never depends on users:read scope.
RAF = "U045Z8N0ZQC"                 # Rafael Hidalgo (raffi127@gmail.com)
MAUD = "U045USN7NCD"                # Maud Miller (maudmiller4@gmail.com)
TITLE = "SCI Campaigns"
# '%B' is locale-dependent; spell the months out so the title reads the same on
# the mini, on Windows and on a server with a non-English locale.
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
# How far back to scan the channel for this month's parent. #l10-alphalete
# carries other reports too, so this is messages, not weeks.
_HISTORY_LIMIT = 200
# {channel_id: {"YYYY-MM": thread_ts}} — a fast path that also survives the
# month's parent scrolling past _HISTORY_LIMIT in a busy channel.
_CACHE = Path.home() / ".config" / "recruiting-report" / "sci-campaigns-thread.json"


def _we_short(week_ending: dt.date) -> str:
    """'7/18' — M/D, no leading zeros, no year. Built from the date parts (not
    strftime %-m, which is Mac-only) so it runs on Windows too."""
    return f"{week_ending.month}/{week_ending.day}"


def month_key(week_ending: dt.date) -> str:
    """'2026-08' — the thread a week's note belongs to."""
    return f"{week_ending.year:04d}-{week_ending.month:02d}"


def month_title(week_ending: dt.date) -> str:
    """'SCI Campaigns - August 2026' — the monthly parent message."""
    return (f"{TITLE} - {_MONTHS[week_ending.month - 1]} "
            f"{week_ending.year}")


def _cache_read(channel: str, month: str) -> str | None:
    try:
        entry = json.loads(_CACHE.read_text(encoding="utf-8")).get(channel)
    except Exception:
        return None
    return entry.get(month) if isinstance(entry, dict) else None


def _cache_write(channel: str, month: str, ts: str) -> None:
    try:
        data = {}
        if _CACHE.exists():
            data = json.loads(_CACHE.read_text(encoding="utf-8"))
        entry = data.get(channel)
        data[channel] = entry if isinstance(entry, dict) else {}
        data[channel][month] = ts
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception as e:                       # a cache miss is survivable
        print(f"  (couldn't cache the thread ts: {type(e).__name__})")


def find_month_ts(client, week_ending: dt.date) -> str | None:
    """ts of THIS MONTH's parent in #l10-alphalete, or None if it isn't posted
    yet. Cache first, then the channel history — the history read is what makes
    it self-healing if the cache is lost or the module moves machines."""
    month, title = month_key(week_ending), month_title(week_ending)
    ts = _cache_read(CHANNEL_ID, month)
    if ts:
        return ts
    try:
        resp = client.conversations_history(channel=CHANNEL_ID,
                                            limit=_HISTORY_LIMIT)
    except Exception as e:
        print(f"  (can't read the channel history — {str(e)[:80]}; a new "
              f"monthly thread will be started)")
        return None
    for msg in resp.get("messages", []):
        if msg.get("thread_ts") and msg.get("thread_ts") != msg.get("ts"):
            continue                                  # a reply, not a parent
        if (msg.get("text") or "").strip() == title:
            _cache_write(CHANNEL_ID, month, msg.get("ts"))
            return msg.get("ts")
    return None


def notify(week_ending: dt.date, *, dry_run: bool = True) -> dict:
    """Reply 'WE <M/D> Complete' under this month's thread, opening that thread
    (and tagging Rafael & Maud on the first note in it) when it's a new month."""
    parent = month_title(week_ending)
    text = f"WE {_we_short(week_ending)} Complete"
    tags = f"<@{RAF}> <@{MAUD}>"
    # Channel post ⇒ the xoxp USER token (Lucy on the mini), never the bot token.
    client = None if dry_run else smp._client()
    ts = None if dry_run else find_month_ts(client, week_ending)
    creating = ts is None
    if dry_run:
        return {"dry_run": True, "channel": CHANNEL_ID, "thread": parent,
                "text": text, "tags_if_new_month": tags}
    if creating:
        ts = client.chat_postMessage(channel=CHANNEL_ID, text=parent).get("ts")
        _cache_write(CHANNEL_ID, month_key(week_ending), ts)
        # Only the message that opens a thread carries the mentions.
        text = f"{text}\n{tags}"
    resp = client.chat_postMessage(channel=CHANNEL_ID, thread_ts=ts, text=text)
    return {"ok": resp.get("ok"), "channel": CHANNEL_ID, "thread": parent,
            "month": month_key(week_ending), "thread_ts": ts,
            "ts": resp.get("ts"), "created_thread": creating, "text": text}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week", required=True, metavar="YYYY-MM-DD",
                    help="the week ending the note announces")
    ap.add_argument("--post", action="store_true",
                    help="actually send (default: dry-run, no send)")
    args = ap.parse_args(argv)
    out = notify(dt.date.fromisoformat(args.week), dry_run=not args.post)
    print(f"  {'DRY-RUN' if not args.post else 'SENT'}: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

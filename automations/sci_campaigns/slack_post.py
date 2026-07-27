"""SCI Campaigns — the 'done' DM.

One shared Slack GROUP DM (from Lucy) to Rafael, Maud and Megan, with a single
persistent parent message titled 'SCI Campaigns'. Every week's note is a REPLY
in that thread, so the three of them get one thread that accumulates rather than
a new DM each Friday:

    SCI Campaigns          <- parent, posted once, reused forever
      └ WE 7.18.2026 complete

Text only, by design — Megan asked for a notice, not the numbers.

  python -m automations.sci_campaigns.slack_post --week 2026-07-18          # dry-run
  python -m automations.sci_campaigns.slack_post --week 2026-07-18 --post
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from automations.sci_campaigns.email_source import we_label
from automations.shared import slack_metrics_post as smp

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

THREAD_TITLE = "SCI Campaigns"
# Slack user IDs (not names) so delivery never depends on the bot holding the
# users:read scope — same list style as all_campaigns_board.slack_post.
RECIPIENTS = [
    "U045Z8N0ZQC",   # Rafael Hidalgo (raffi127@gmail.com)
    "U045USN7NCD",   # Maud Miller (maudmiller4@gmail.com)
    "U04G5HJBGFN",   # Megan Hidalgo (ltdhidalgos@gmail.com)
]
# How far back to scan the DM for the existing parent. 200 messages is many
# years at one post a week, and the lookup is one API call.
_HISTORY_LIMIT = 200
# {channel_id: thread_ts} — the only way to find the thread again on a token
# without mpim:history. Lives beside the other report credentials/state.
_CACHE = Path.home() / ".config" / "recruiting-report" / "sci-campaigns-thread.json"


def _pick_client():
    """Prefer the 'Lucy' bot token so the DM comes FROM Lucy, matching every
    other Slack report. Fall back to the per-user token off the runner."""
    try:
        return smp._bot_client(), True
    except Exception as e:
        print(f"  (no Lucy bot token here — {type(e).__name__}; using the user "
              f"token, the DM sends from that account)")
        return smp._client(), False


def _cache_read(channel: str) -> str | None:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8")).get(channel)
    except Exception:
        return None


def _cache_write(channel: str, ts: str) -> None:
    try:
        data = {}
        if _CACHE.exists():
            data = json.loads(_CACHE.read_text(encoding="utf-8"))
        data[channel] = ts
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception as e:                       # a cache miss is survivable
        print(f"  (couldn't cache the thread ts: {type(e).__name__})")


def _find_parent_ts(client, channel: str) -> str | None:
    """ts of the existing 'SCI Campaigns' parent in this DM, if any.

    Prefers a locally cached ts, because reading a group DM's history needs the
    mpim:history scope that the per-user token does NOT carry (only the Lucy bot
    does). Without the cache every run would start a new parent and the thread
    would fragment. Returns None if neither path finds one — the caller then
    posts a fresh parent and caches it.
    """
    ts = _cache_read(channel)
    if ts:
        return ts
    try:
        resp = client.conversations_history(channel=channel,
                                            limit=_HISTORY_LIMIT)
    except Exception as e:
        print(f"  (can't read the DM history — {str(e)[:80]}; relying on the "
              f"local thread cache)")
        return None
    for msg in resp.get("messages", []):
        if msg.get("thread_ts") and msg.get("thread_ts") != msg.get("ts"):
            continue                                  # a reply, not a parent
        if (msg.get("text") or "").strip() == THREAD_TITLE:
            _cache_write(channel, msg.get("ts"))
            return msg.get("ts")
    return None


def notify(week_ending: dt.date, *, dry_run: bool = True,
           recipients: list | None = None) -> dict:
    """Post 'WE <m.d.yyyy> complete' under the 'SCI Campaigns' thread."""
    users = recipients or RECIPIENTS
    text = f"WE {we_label(week_ending)} complete"
    if dry_run:
        return {"dry_run": True, "to_users": users, "thread": THREAD_TITLE,
                "text": text}
    client, as_bot = _pick_client()
    user_ids = [smp._resolve_user_id(client, u) for u in users]
    # One multi-party DM keyed on the member set — Slack returns the SAME
    # channel for the same users every time, so the thread persists.
    channel = client.conversations_open(users=",".join(user_ids))["channel"]["id"]
    parent = _find_parent_ts(client, channel)
    created = False
    if not parent:
        parent = client.chat_postMessage(
            channel=channel, text=THREAD_TITLE)["ts"]
        _cache_write(channel, parent)
        created = True
    resp = client.chat_postMessage(channel=channel, thread_ts=parent, text=text)
    return {"ok": resp.get("ok"), "channel": channel, "thread_ts": parent,
            "ts": resp.get("ts"), "created_parent": created,
            "as_bot": as_bot, "text": text}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week", required=True, metavar="YYYY-MM-DD",
                    help="the week ending the DM announces")
    ap.add_argument("--post", action="store_true",
                    help="actually send (default: dry-run, no send)")
    ap.add_argument("--only", default="",
                    help="comma-separated Slack user id(s) to DM INSTEAD of "
                         "the full list (targeted test)")
    args = ap.parse_args(argv)
    users = ([u.strip() for u in args.only.split(",") if u.strip()]
             if args.only else None)
    if users:
        print(f"  --only override: sending to {users} (test)")
    out = notify(dt.date.fromisoformat(args.week),
                 dry_run=not args.post, recipients=users)
    print(f"  {'DRY-RUN' if not args.post else 'SENT'}: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

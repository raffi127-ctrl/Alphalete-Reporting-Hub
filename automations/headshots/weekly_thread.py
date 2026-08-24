"""The Monday headshot thread in #11280-alphalete-marketing-inc-rafael-hidalgo.

Megan 2026-08-23: start a thread each Monday asking people to reply with the
headshot photo INCLUDING the person's name, so the bot knows who they are.
The bot (run.py) then watches the replies of that thread — not loose channel
posts, since this is a busy office channel.

Idempotency lives in the thread itself, same as new_start_followup: the post
carries a stable marker line, and before posting we look for this week's
marker in the channel. No state file to drift out of sync with Slack.

    # preview the exact post, send nothing:
    python -m automations.headshots.weekly_thread --dry-run

    # live (scheduled Monday mornings; safe to re-run — never double-posts):
    python -m automations.headshots.weekly_thread

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Optional

# Same channel bg_check_sync + the new-start threads use.
CHANNEL_ID = "C0AUAS88FGW"     # #11280-alphalete-marketing-inc-rafael-hidalgo

# Stable first line — the find/scan side keys off this exact phrase, so
# reword the BODY freely but never this marker.
MARKER = "Headshot Submissions"


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def week_monday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=today.weekday())


def prompt_text(monday: Optional[dt.date] = None) -> str:
    monday = monday or week_monday()
    # Megan's exact wording (2026-08-23) — change only with her sign-off.
    return (
        ":camera_with_flash: *{marker} — Week of {m}/{d}*\n"
        "• Reply in this thread with headshot photos\n"
        "• Put the person's FIRST & LAST name in the SAME reply"
    ).format(marker=MARKER, m=monday.month, d=monday.day)


def find_week_anchor(client=None, channel: str = CHANNEL_ID,
                     monday: Optional[dt.date] = None,
                     lookback: int = 200) -> Optional[dict]:
    """This week's marker post (ours), or None if it isn't up yet."""
    client = client or _client()
    monday = monday or week_monday()
    resp = client.conversations_history(channel=channel, limit=lookback)
    matches = []
    for msg in resp.get("messages", []):
        if msg.get("subtype"):
            continue
        text = msg.get("text", "") or ""
        if MARKER not in text:
            continue
        when = dt.datetime.fromtimestamp(float(msg["ts"])).date()
        if when >= monday:
            matches.append(msg)
    if not matches:
        return None
    return min(matches, key=lambda m: float(m["ts"]))


def post_prompt(*, dry_run: bool = True, channel: str = CHANNEL_ID,
                force: bool = False) -> Optional[str]:
    """Post this week's thread-starter. Returns its ts (existing or new).

    Safe on any day / any repeat run: only posts if this week's marker post
    isn't already in the channel. `force` skips only the Monday check, never
    the duplicate check.
    """
    today = dt.date.today()
    if today.weekday() != 0 and not force:
        print("Not Monday — nothing to post. (--force posts anyway.)")
        return None

    client = _client()
    existing = find_week_anchor(client, channel)
    if existing:
        print("This week's headshot thread is already up (ts={}) — not "
              "posting again.".format(existing["ts"]))
        return existing["ts"]

    text = prompt_text()
    if dry_run:
        print("--- Monday post (dry-run, NOT sent) ---")
        print("channel: {}".format(channel))
        print(text)
        return None
    resp = client.chat_postMessage(channel=channel, text=text)
    print("Posted this week's headshot thread (ts={}).".format(resp.get("ts")))
    return resp.get("ts")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Monday headshot thread-starter.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the exact post, send nothing")
    ap.add_argument("--force", action="store_true",
                    help="post even if today isn't Monday")
    ap.add_argument("--channel", default=CHANNEL_ID)
    args = ap.parse_args(argv)
    post_prompt(dry_run=args.dry_run, channel=args.channel, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
import os
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


# The Hub CARD id for this job — the launchd agent com.alphalete.headshots-monday
# auto-registers as the card 'headshots_monday'. It MUST be that id and NOT the
# on-demand rerun id 'headshots_monday_now', which is a card of its OWN: the Hub
# counts runs by card id, so a manual `_now` run left the scheduled card reading
# "no run logged" all day even though the thread had posted (Megan, 2026-08-24).
# The merged card (Megan 2026-08-25): the Monday thread, the 5-minute tick,
# Blue Ink and BG Check are all one job on one card. hub_activity keys on the
# CARD id, so logging the old "headshots_monday" would keep self-registering a
# duplicate library card beside it. The NAME stays step-specific — that is what
# the card's run feed shows, and it is how a failing step stays visible.
from automations.shared.new_start_steps import CARD_ID as HUB_CARD_ID
HUB_CARD_NAME = "Headshot Photo — Monday thread"


def _log_hub_run(started_at, status):
    """Publish this run to the Hub (standing rule: LaunchAgent reports publish
    to the Hub). Best-effort — a logging problem must never fail a post that
    already went out."""
    if os.environ.get("HUB_REPORT_ID"):
        return          # a runner is wrapping us and logs this run itself
    try:
        from automations.shared import hub_activity
        hub_activity.log_completed(HUB_CARD_ID, HUB_CARD_NAME,
                                   status=status, started_at=started_at)
    except Exception as e:                              # noqa: BLE001
        print("(activity log skipped: {}: {})".format(type(e).__name__, e))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Monday headshot thread-starter.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the exact post, send nothing")
    ap.add_argument("--force", action="store_true",
                    help="post even if today isn't Monday")
    ap.add_argument("--channel", default=CHANNEL_ID)
    args = ap.parse_args(argv)
    started_at = dt.datetime.now()
    ts, ok = None, False
    try:
        ts = post_prompt(dry_run=args.dry_run, channel=args.channel,
                         force=args.force)
        ok = True
        return 0
    finally:
        # Log only a run that actually settled the week's thread — `ts` is set
        # whether we posted it or found it already up. A --dry-run posts
        # nothing, and a non-Monday no-op has nothing to report; logging either
        # would clear the card on a day the thread never went out.
        if not args.dry_run and (ts or not ok):
            _log_hub_run(started_at, "success" if ok else "failed")


if __name__ == "__main__":
    sys.exit(main())

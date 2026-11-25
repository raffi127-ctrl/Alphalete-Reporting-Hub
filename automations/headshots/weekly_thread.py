"""The headshot thread in #rafs-office-recruiting-11280 — on any start day.

Megan 2026-08-23: start a thread asking people to reply with the headshot
photo INCLUDING the person's name, so the bot knows who they are. The bot
(run.py) then watches the replies of that thread — not loose channel posts,
since this is a busy office channel.

NOT MONDAYS ONLY, since 2026-11-24. It was built when new starts began on a
Monday and the agent fired Monday 8:30am, so a Wednesday start got no thread
at all — Megan: the thread goes up "any day that there's new starts
scheduled". The morning of a start is what triggers it now; the day of the
week decides nothing.

Idempotency lives in the thread itself, same as new_start_followup: the post
carries a stable marker line, and before posting we look for this week's
marker in the channel. No state file to drift out of sync with Slack.

    # preview the exact post, send nothing:
    python -m automations.headshots.weekly_thread --dry-run

    # live (scheduled each weekday morning; safe to re-run — never double-posts):
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
from automations.shared.new_start_steps import SLACK_CHANNEL_ID

CHANNEL_ID = SLACK_CHANNEL_ID  # #rafs-office-recruiting-11280

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
    # Back since 2026-11-17: the 📸 button is gone, so the post says how
    # again (one reply, the photo + the person's name).
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


def starts_this_week(monday: Optional[dt.date] = None,
                     office_key: str = "") -> bool:
    """Is anybody scheduled to start in this week? True when it cannot be told.

    UNREADABLE MEANS POST. The thread costs a line in a channel; a missing
    thread costs somebody their headshot on the one morning they are there to
    have it taken ([[feedback_empty_means_proven_zero]] cuts the other way
    here, and deliberately -- "I could not look" must not read as "nobody is
    starting", so it falls back to the old always-post behaviour).
    """
    try:
        from automations.icd_onboarding import board as _B
        from automations.icd_onboarding import fillers as _F
        week = _B.week_start_of(monday or week_monday())
        rows = _F.rows_anywhere(office_key or "raf", week, log=lambda *a: None)
    except Exception:           # noqa: BLE001 -- see the docstring
        return True
    live = [r for r in rows
            if not str(r.get(_B.TERMINATED_AT) or "").strip()]
    return bool(live)


def post_prompt(*, dry_run: bool = True, channel: str = CHANNEL_ID,
                force: bool = False, office_key: str = "") -> Optional[str]:
    """Post this week's thread-starter. Returns its ts (existing or new).

    ANY DAY THERE ARE NEW STARTS, not Mondays only (Megan, 2026-11-24: "right
    now I think we only have it on Mondays. It should be any day that there's
    new starts scheduled").

    WHY MONDAY-ONLY WAS WRONG IN BOTH DIRECTIONS. A start can be any day since
    2026-11-16, so a week whose Monday run did not happen -- the machine asleep,
    the job failed -- had no thread at all and nothing retried it, leaving a
    Wednesday starter with nowhere to put a photo. And it posted on Mondays
    with nobody starting, which is a prompt in a busy channel asking for
    headshots of no one.

    STILL ONE THREAD PER WEEK, in each office's own channel. The marker says
    "Week of M/D" and the replies all belong together -- a thread per day would
    split one week's headshots across five places and the bot reads one
    thread's replies. So this posts the FIRST day of the week that has
    somebody, and finds the existing thread every day after.

    Safe on any day / any repeat run: only posts if this week's marker post
    isn't already in the channel. `force` skips the has-anybody check, never
    the duplicate check.
    """
    client = _client()
    existing = find_week_anchor(client, channel)
    if existing:
        print("This week's headshot thread is already up (ts={}) — not "
              "posting again.".format(existing["ts"]))
        return existing["ts"]

    if not force and not starts_this_week(office_key=office_key):
        print("Nobody is scheduled to start this week — nothing to post. "
              "(--force posts anyway.)")
        return None

    text = prompt_text()
    if dry_run:
        print("--- Monday post (dry-run, NOT sent) ---")
        print("channel: {}".format(channel))
        print(text)
        return None
    resp = client.chat_postMessage(channel=channel, text=text)
    print("Posted this week's headshot thread (ts={}).".format(resp.get("ts")))
    # No 📸 Add headshot button under it any more (Megan 2026-11-17):
    # people reply with the photo + the name, and run.py reads the reply.
    return resp.get("ts")


# The Hub CARD id for this job — the launchd agent com.alphalete.headshots-monday
# auto-registers as the card 'headshots_monday'. It MUST be that id and NOT the
# on-demand rerun id 'headshots_monday_now', which is a card of its OWN: the Hub
# counts runs by card id, so a manual `_now` run left the scheduled card reading
# "no run logged" all day even though the thread had posted (Megan, 2026-08-24).
# The Headshot Bot card. hub_activity keys on the CARD id, so logging the old
# "headshots_monday" self-registered a duplicate library card beside the real
# one — which is why a manual `_now` run left the scheduled card reading "no run
# logged" all day even though the thread had posted. The NAME stays specific to
# the pass, so the run feed still distinguishes the Monday post from the
# 5-minute tick.
HUB_CARD_ID = "headshot-bot"
HUB_CARD_NAME = "Headshot Bot — Monday thread"


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
    ap.add_argument("--channel", default=None,
                    help="post in just this channel (default: every LIVE "
                         "office in headshots config.OFFICES)")
    ap.add_argument("--office", default=None,
                    help="with --channel: whose board decides whether anybody "
                         "is starting this week")
    args = ap.parse_args(argv)
    started_at = dt.datetime.now()
    ts, ok = None, False
    try:
        # Every live office gets the same thread, same wording, in its own
        # channel (Megan 2026-10-26: roll it out to the ICDs). One office
        # failing to post never stops the others.
        # THE OFFICE, not just its channel: whether anybody is starting this
        # week is a question about THAT office's board, and asking Raf's about
        # Omar's week is how a thread goes up in the wrong place or not at all.
        if args.channel:
            targets = [(args.channel, args.office or "")]
        else:
            from automations.headshots import config as _cfg
            targets = [(o.channel, o.key) for o in _cfg.live_offices()]
        failed = []
        for ch, key in targets:
            try:
                got = post_prompt(dry_run=args.dry_run, channel=ch,
                                  force=args.force, office_key=key)
                ts = ts or got
            except Exception as e:  # noqa: BLE001
                print("could not post in {}: {}: {}".format(
                    ch, type(e).__name__, e))
                failed.append(ch)
        ok = not failed
        return 0 if ok else 1
    finally:
        # Log only a run that actually settled the week's thread — `ts` is set
        # whether we posted it or found it already up. A --dry-run posts
        # nothing, and a non-Monday no-op has nothing to report; logging either
        # would clear the card on a day the thread never went out.
        if not args.dry_run and (ts or not ok):
            _log_hub_run(started_at, "success" if ok else "failed")


if __name__ == "__main__":
    sys.exit(main())

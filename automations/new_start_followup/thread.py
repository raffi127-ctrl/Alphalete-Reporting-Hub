"""Find the week's new-start thread in #rafs-office-recruiting and read who sent.

Shape of the thread (Raf's existing manual flow):
  Fri ~4:54pm  Aisha  "*D2D Alphalete New Starts Scheduled for Monday*"   <- anchor
  Sat  8:00am  Aisha  "<@U…> <@U…> …"                                     <- roll call
  Sat  ...     leaders reply "Sent" / "sent x4" / "Sentttttt x3"          <- confirmations
  Sun  ~1pm    Raf    numbered ✅ checklist + tags the stragglers

As of 7/19/2026 Lucy posts the Saturday roll call instead of Aisha (Raf's call),
building it from OBCL column B so nobody with a new start gets left out -- Aisha's
hand-built list was missing 4 leaders the week this was written. Aisha's version
is still recognised so the transition week (and any manual re-post) still parses.

A leader counts as done when they post a reply matching /sent/i AFTER the roll
call. Only replies after it count -- Aisha's setup messages and Friday chatter
sit above it. With no roll call at all, everything under the anchor counts.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Dict, List, Optional

from automations.shared import slack_metrics_post as smp

CHANNEL_ID = os.environ.get("NSF_SLACK_CHANNEL", "C06881A7WLV")  # #rafs-office-recruiting

# Aisha's Friday post. Matched loosely (case-insensitive substring on the
# de-formatted text) so bold markers or a trailing date don't break it.
ANCHOR_PATTERN = re.compile(r"new starts scheduled for monday", re.I)

# "Sent", "sent x4", "Sentttttt x3", "Sent (Sosa)", "sent them all".
SENT_PATTERN = re.compile(r"\bsen+t+\b", re.I)
# Trailing multiplier: "x4", "X 4", "×4".
COUNT_PATTERN = re.compile(r"[x×]\s*(\d+)", re.I)

MENTION_PATTERN = re.compile(r"<@([UW][A-Z0-9]+)>")

# Stable marker in Lucy's own roll call. Used to (a) find the boundary for
# counting confirmations and (b) avoid posting a second roll call on a re-run,
# so idempotency lives in the thread itself rather than in a state file that
# can drift out of sync with Slack.
ROLLCALL_MARKER = "New-Start Texts — Roll Call"


class Confirmation:
    def __init__(self, slack_id: str, ts: str, text: str, claimed: Optional[int]):
        self.slack_id = slack_id
        self.ts = ts
        self.text = text
        self.claimed = claimed  # the N in "sent x4", or None if unqualified

    @property
    def when(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(float(self.ts))


def _strip(text: str) -> str:
    """Slack escapes &<> on the way out; compare against the unescaped form."""
    return (text or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def find_anchor(client, channel: str, friday: dt.date, lookback: int = 200) -> Optional[dict]:
    """Aisha's 'New Starts Scheduled for Monday' post from `friday`."""
    resp = client.conversations_history(channel=channel, limit=lookback)
    for msg in resp.get("messages", []):
        if msg.get("subtype"):
            continue
        when = dt.datetime.fromtimestamp(float(msg["ts"])).date()
        if when != friday:
            continue
        if ANCHOR_PATTERN.search(_strip(msg.get("text", ""))):
            return msg
    return None


# Aisha's intro line above the copy/paste script.
_SCRIPT_INTRO = re.compile(r"copy and paste", re.I)


def find_script(replies: List[dict], anchor_ts: str) -> Optional[str]:
    """The copy/paste message Aisha posts for leaders to send their new starts.

    Structure she uses every week: an intro reply ("here is the message you want
    to send... copy and paste and make edits on the X markings") immediately
    followed by the script itself. So: find the intro, take the next reply from
    the same person.

    Worth pulling out because it lets the straggler texts CARRY the script.
    Otherwise the text has to offer to send it on request -- and nothing reads
    replies to Lucy's number, so that promise would never be kept.
    """
    ordered = sorted(replies, key=lambda m: float(m["ts"]))
    for i, msg in enumerate(ordered):
        if msg["ts"] == anchor_ts:
            continue
        if not _SCRIPT_INTRO.search(_strip(msg.get("text", ""))):
            continue
        author = msg.get("user")
        for nxt in ordered[i + 1:]:
            if nxt.get("user") != author or nxt.get("subtype"):
                continue
            body = _strip(nxt.get("text", "")).strip()
            if len(body) < 40 or MENTION_PATTERN.search(body):
                continue  # a stray one-liner or a tag list, not the script
            return body
        return None
    return None


def find_our_rollcall(replies: List[dict]) -> Optional[dict]:
    """Lucy's own roll call, if it's already been posted this week."""
    for msg in replies:
        if ROLLCALL_MARKER in _strip(msg.get("text", "")):
            return msg
    return None


def find_roll_call(replies: List[dict], anchor_ts: str) -> Optional[dict]:
    """The Saturday reply that kicks the leaders off.

    Lucy's own roll call wins when present. Otherwise falls back to Aisha's
    hand-typed version -- the first reply that is essentially nothing but
    mentions, since her other replies are prose or image uploads.
    """
    ours = find_our_rollcall(replies)
    if ours is not None:
        return ours

    for msg in replies:
        if msg["ts"] == anchor_ts:
            continue
        text = _strip(msg.get("text", "")).strip()
        ids = MENTION_PATTERN.findall(text)
        if len(ids) < 2:
            continue
        remainder = MENTION_PATTERN.sub("", text).strip()
        if len(remainder) > 40:  # mostly prose that happens to tag people
            continue
        return msg
    return None


def read_thread(friday: Optional[dt.date] = None, channel: str = CHANNEL_ID, client=None):
    """-> dict with the anchor, roll-call, tagged ids and confirmations.

    Raises if the anchor or roll call is missing -- posting a nudge against the
    wrong thread is worse than not posting.
    """
    client = client or smp._client()
    if friday is None:
        today = dt.date.today()
        friday = today - dt.timedelta(days=(today.weekday() - 4) % 7)

    anchor = find_anchor(client, channel, friday)
    if anchor is None:
        raise RuntimeError(
            "No 'New Starts Scheduled for Monday' post found in {} on {}. "
            "Aisha posts it Friday afternoon -- check the channel before "
            "re-running.".format(channel, friday.isoformat())
        )

    replies = client.conversations_replies(
        channel=channel, ts=anchor["ts"], limit=200
    ).get("messages", [])

    # The roll call is optional now that Lucy posts it: on Saturday morning the
    # 8am job runs BEFORE one exists, and the expected-leader list comes from
    # OBCL either way. With no roll call, confirmations are counted from the
    # anchor down.
    roll = find_roll_call(replies, anchor["ts"])
    boundary_ts = roll["ts"] if roll else anchor["ts"]
    tagged = MENTION_PATTERN.findall(_strip(roll.get("text", ""))) if roll else []

    confirmations = {}  # type: Dict[str, Confirmation]
    for msg in replies:
        if float(msg["ts"]) <= float(boundary_ts):
            continue
        if msg.get("subtype"):
            continue
        user = msg.get("user")
        text = _strip(msg.get("text", ""))
        if not user or not SENT_PATTERN.search(text):
            continue
        m = COUNT_PATTERN.search(text)
        claimed = int(m.group(1)) if m else None
        # Keep the FIRST confirmation -- that's when they actually did it.
        if user not in confirmations:
            confirmations[user] = Confirmation(user, msg["ts"], text, claimed)

    return {
        "channel": channel,
        "anchor_ts": anchor["ts"],
        "roll_call_ts": roll["ts"] if roll else None,
        "roll_call_at": dt.datetime.fromtimestamp(float(roll["ts"])) if roll else None,
        "roll_call_is_ours": roll is not None and ROLLCALL_MARKER in _strip(roll.get("text", "")),
        "tagged": tagged,
        "confirmations": confirmations,
        "replies": replies,
        "script": find_script(replies, anchor["ts"]),
    }

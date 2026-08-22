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

A leader counts as done when they post a reply matching /sent|done/i AFTER the
roll call. Only replies after it count -- Aisha's setup messages and Friday
chatter sit above it. With no roll call at all, everything under the anchor counts.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Dict, List, Optional

from automations.shared import slack_metrics_post as smp

# Moved from #rafs-office-recruiting (C06881A7WLV) on 2026-08-21 — Aisha now
# posts the weekly thread in #11280-alphalete-marketing-inc-rafael-hidalgo.
CHANNEL_ID = os.environ.get("NSF_SLACK_CHANNEL", "C0AUAS88FGW")

# TWO FUNNELS since the week of 8/24 (Megan 2026-08-22: "apply this to
# tiffani's thread each week as well"). Each recruiter posts her own
# same-titled Friday thread and the report runs the full roll-call/nudge/
# checklist cycle in EACH. Anchors are told apart by AUTHOR, not order —
# ordering broke the day Tiffani's post shadowed Aisha's.
# `required`: a week where Aisha doesn't post is a failure; a week where
# Tiffani doesn't post just means no 2nd-funnel starts — skip quietly.
# `tag`: whether Lucy's roll call @-mentions the leaders. Tiffani hand-tags her
# own funnel, so Lucy's post there carries plain names + counts — the marker
# and the counts without re-pinging anyone (Megan 2026-08-22).
FUNNELS = [
    {"key": "main", "label": "Main funnel",
     "poster": "U083X5ZJWSH",           # Aisha Ceron
     "required": True, "tag": True, "snapshot": "roster_snapshot.json"},
    {"key": "second", "label": "2nd funnel (Tiffani)",
     "poster": "U0B9924FHCL",           # Tiffani Brown
     "required": False, "tag": False, "snapshot": "roster_snapshot_2nd.json"},
]


def funnel_by_key(key: str) -> dict:
    for f in FUNNELS:
        if f["key"] == key:
            return f
    raise KeyError("no funnel {!r} — known: {}".format(
        key, ", ".join(f["key"] for f in FUNNELS)))

# Aisha's Friday post. Matched loosely (case-insensitive substring on the
# de-formatted text) so bold markers or a trailing date don't break it.
ANCHOR_PATTERN = re.compile(r"new starts scheduled for monday", re.I)

# "Sent", "sent x4", "Sentttttt x3", "Sent (Sosa)", "sent them all", plus the
# "Done" / "Done!" some leaders reply instead of "Sent" (Megan 2026-07-26: count
# those too -- Tiffani wrote "Done!" on the 7/27 week and got nudged again
# because Lucy didn't read it as a confirmation).
SENT_PATTERN = re.compile(r"\b(?:sen+t+|done)\b", re.I)
# Trailing multiplier: "x4", "X 4", "×4" — and the flipped "4x" / "5 x"
# (Pranish + Bill both wrote it that way on the 8/24 week).
COUNT_PATTERN = re.compile(r"[x×]\s*(\d+)|(\d+)\s*[x×]", re.I)

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


def find_anchor(client, channel: str, friday: dt.date, lookback: int = 200,
                poster: Optional[str] = None) -> Optional[dict]:
    """The 'New Starts Scheduled for Monday' post from `friday`.

    Since the week of 8/24 there are TWO same-titled Friday posts — one per
    funnel (see FUNNELS). With `poster` given, only that author's post counts;
    without it, the EARLIEST match wins (Aisha posts before Tiffani), never
    the newest — ordering by newest broke the day Tiffani's post shadowed
    Aisha's.
    """
    resp = client.conversations_history(channel=channel, limit=lookback)
    matches = []
    for msg in resp.get("messages", []):
        if msg.get("subtype"):
            continue
        when = dt.datetime.fromtimestamp(float(msg["ts"])).date()
        if when != friday:
            continue
        if poster and msg.get("user") != poster:
            continue
        if ANCHOR_PATTERN.search(_strip(msg.get("text", ""))):
            matches.append(msg)
    if not matches:
        return None
    return min(matches, key=lambda m: float(m["ts"]))


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
    """The Saturday reply that kicks the leaders off — the EARLIEST roll call.

    A thread can hold both a hand-typed roll call (Tiffani tags her own funnel;
    Aisha did in the transition weeks) and Lucy's own. Confirmations count from
    the FIRST one — a leader who replied "Sent" right after the hand tags must
    not lose credit because Lucy's post landed later. A hand-typed roll call is
    the first reply that is essentially nothing but mentions, since the other
    replies are prose or image uploads.
    """
    candidates = []
    ours = find_our_rollcall(replies)
    if ours is not None:
        candidates.append(ours)

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
        candidates.append(msg)
        break
    if not candidates:
        return None
    return min(candidates, key=lambda m: float(m["ts"]))


def read_thread(friday: Optional[dt.date] = None, channel: str = CHANNEL_ID,
                client=None, poster: Optional[str] = None):
    """-> dict with the anchor, roll-call, tagged ids and confirmations.

    Raises if the anchor or roll call is missing -- posting a nudge against the
    wrong thread is worse than not posting.
    """
    client = client or smp._client()
    if friday is None:
        today = dt.date.today()
        friday = today - dt.timedelta(days=(today.weekday() - 4) % 7)

    anchor = find_anchor(client, channel, friday, poster=poster)
    if anchor is None:
        raise RuntimeError(
            "No 'New Starts Scheduled for Monday' post found in {} on {}{}. "
            "It goes up Friday afternoon -- check the channel before "
            "re-running.".format(
                channel, friday.isoformat(),
                " by <@{}>".format(poster) if poster else "")
        )

    replies = client.conversations_replies(
        channel=channel, ts=anchor["ts"], limit=200
    ).get("messages", [])

    # The roll call is optional now that Lucy posts it: on Saturday morning the
    # 8am job runs BEFORE one exists, and the expected-leader list comes from
    # OBCL either way. With no roll call, confirmations are counted from the
    # anchor down.
    roll = find_roll_call(replies, anchor["ts"])
    ours = find_our_rollcall(replies)
    boundary_ts = roll["ts"] if roll else anchor["ts"]
    # Tags come from every roll call in the thread (hand-typed AND Lucy's) —
    # in the no-tag funnel Lucy's post has no mentions, so the hand-typed one
    # is what says who got pinged.
    tagged = MENTION_PATTERN.findall(_strip(roll.get("text", ""))) if roll else []
    if ours is not None and roll is not None and ours["ts"] != roll["ts"]:
        for sid in MENTION_PATTERN.findall(_strip(ours.get("text", ""))):
            if sid not in tagged:
                tagged.append(sid)

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
        claimed = int(m.group(1) or m.group(2)) if m else None
        # Keep the FIRST confirmation -- that's when they actually did it.
        if user not in confirmations:
            confirmations[user] = Confirmation(user, msg["ts"], text, claimed)

    return {
        "channel": channel,
        "anchor_ts": anchor["ts"],
        "roll_call_ts": roll["ts"] if roll else None,
        "roll_call_at": dt.datetime.fromtimestamp(float(roll["ts"])) if roll else None,
        "roll_call_is_ours": roll is not None and ROLLCALL_MARKER in _strip(roll.get("text", "")),
        # Lucy's own roll call, independent of which one is the boundary —
        # the idempotency check ("did WE already post?") keys off this.
        "our_rollcall_ts": ours["ts"] if ours else None,
        "tagged": tagged,
        "confirmations": confirmations,
        "replies": replies,
        "script": find_script(replies, anchor["ts"]),
    }

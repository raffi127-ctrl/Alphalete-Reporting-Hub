"""Who has LEFT #rafs-office-recruiting — don't tag or text former employees.

Raf's rule: a leader who ran the 2nd round but is no longer in the channel
shouldn't be @-tagged or texted. Their new starts still need chasing, so they're
shown with "No longer a channel member" instead of quietly disappearing.

Why this is done the hard way: Lucy's Slack token has NO `channels:read`, so
`conversations.members` is off the table (missing_scope). It DOES have
`channels:history`, and Slack records joins and leaves as ordinary messages with
subtype `channel_join` / `channel_leave` -- so membership changes can be
replayed from history.

The catch is that history is scanned in a bounded window, so a leave from long
ago scrolls out of reach. That's what the state file fixes: once someone is seen
leaving they STAY marked as gone until a later join is seen. The window only has
to catch each event once, ever.

Silence means present: a leader with no events in the window is assumed to be a
member (they joined before it). Only an actual observed leave marks someone gone
-- the failure we can't accept is wrongly marking an ACTIVE leader as departed
and never chasing their new starts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Set

from automations.shared import slack_metrics_post as smp

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "output" / "new_start_membership.json"

# ~8 pages x 200 covers several months in this channel; joins/leaves are rare.
DEFAULT_MAX_PAGES = 8


def _load_state() -> Dict[str, dict]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("users", {})
        except ValueError:
            return {}
    return {}


def _save_state(users: Dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "_note": (
            "Latest observed channel_join / channel_leave per user in "
            "#rafs-office-recruiting, replayed from history because Lucy's token "
            "has no channels:read. Sticky so an old leave isn't forgotten when it "
            "scrolls out of the scan window. Safe to delete — it rebuilds."
        ),
        "users": users,
    }
    STATE_PATH.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def scan(client=None, channel: str = None, max_pages: int = DEFAULT_MAX_PAGES) -> Dict[str, dict]:
    """Replay join/leave events into {user_id: {"status", "ts"}}, newest wins."""
    from automations.new_start_followup.thread import CHANNEL_ID

    client = client or smp._client()
    channel = channel or CHANNEL_ID

    users = _load_state()
    cursor = None
    for _ in range(max_pages):
        resp = client.conversations_history(channel=channel, limit=200, cursor=cursor)
        for msg in resp.get("messages", []):
            subtype = msg.get("subtype")
            if subtype not in ("channel_join", "channel_leave"):
                continue
            uid = msg.get("user")
            if not uid:
                continue
            ts = msg["ts"]
            prev = users.get(uid)
            # Newest event wins, so a rejoin after a leave clears the flag.
            if prev is None or float(ts) > float(prev.get("ts", 0)):
                users[uid] = {
                    "status": "left" if subtype == "channel_leave" else "joined",
                    "ts": ts,
                }
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break

    _save_state(users)
    return users


def departed_ids(client=None, channel: str = None,
                 max_pages: int = DEFAULT_MAX_PAGES) -> Set[str]:
    """Slack IDs whose most recent observed event was leaving the channel."""
    users = scan(client=client, channel=channel, max_pages=max_pages)
    return {uid for uid, rec in users.items() if rec.get("status") == "left"}

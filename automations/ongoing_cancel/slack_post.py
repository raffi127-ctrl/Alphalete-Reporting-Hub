"""Slack post module — finds today's 'Metrics M/DD' parent thread in
#alphalete-sales and replies with the Ongoing Cancel image.

Reads the user's Slack token from `~/.config/recruiting-report/slack-user-token`
(or env var SLACK_USER_TOKEN). Each teammate installs the Slack app once;
posts then come from THEIR Slack account (per-user OAuth user-token, scopes
chat:write + files:write + channels:history + groups:history).
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

CHANNEL_ID = "C068PH3RFSM"  # #alphalete-sales
TOKEN_PATH = Path.home() / ".config" / "recruiting-report" / "slack-user-token"


class SlackPostError(RuntimeError):
    pass


def _load_token() -> str:
    tok = os.environ.get("SLACK_USER_TOKEN")
    if tok:
        return tok.strip()
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    raise SlackPostError(
        f"No Slack user token found. Save it to {TOKEN_PATH} or set "
        f"SLACK_USER_TOKEN env var. See setup notes in the Ongoing Cancel "
        f"Hub card."
    )


def _client():
    """Build an SSL-context-aware Slack client. Python 3.14's bundled
    urllib doesn't ship with system root certs on macOS, so we hand the
    WebClient an explicit cafile-backed SSL context from certifi."""
    import ssl
    import certifi
    from slack_sdk import WebClient
    ctx = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=_load_token(), ssl=ctx)


def find_metrics_thread_ts(client, today: dt.date) -> str:
    """Search recent #alphalete-sales messages for the 'Metrics M/DD' parent
    posted today. Returns its thread_ts (Slack message timestamp). Raises if
    the parent thread isn't found — caller surfaces a friendly 'no header
    posted yet' error."""
    # Matching patterns: 'Metrics 5/27', 'Metrics 05/27', '* Metrics 5/27' (bullet)
    candidates = [
        f"Metrics {today.month}/{today.day}",
        f"Metrics {today.month:02d}/{today.day:02d}",
    ]
    # Pull the last day's messages — 24h is enough.
    oldest = (dt.datetime.combine(today, dt.time.min)).timestamp()
    resp = client.conversations_history(
        channel=CHANNEL_ID, oldest=str(oldest), limit=100
    )
    for msg in resp.get("messages", []):
        text = msg.get("text", "")
        if any(c in text for c in candidates):
            return msg.get("thread_ts") or msg.get("ts")
    raise SlackPostError(
        f"Couldn't find today's 'Metrics {today.month}/{today.day}' header "
        f"thread in #alphalete-sales. Post the header thread there first, "
        f"then click Run Again."
    )


def post_reply_with_image(image_path: Path,
                          today: dt.date | None = None,
                          dry_run: bool = False) -> dict:
    """Find today's Metrics thread + reply with the Ongoing Cancel image.
    Returns the Slack API response (or a dict describing the dry-run)."""
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "would_post_image": str(image_path),
                "to_channel": CHANNEL_ID, "title": "Ongoing Cancel"}
    client = _client()
    thread_ts = find_metrics_thread_ts(client, today)
    # files_upload_v2 attaches to the thread in one shot.
    resp = client.files_upload_v2(
        channel=CHANNEL_ID,
        thread_ts=thread_ts,
        file=str(image_path),
        filename=f"Ongoing Cancel {today.month}.{today.day}.png",
        initial_comment="Ongoing Cancel",
    )
    return {"ok": resp.get("ok"), "thread_ts": thread_ts,
            "file": resp.get("file", {}).get("id")}

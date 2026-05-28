"""Shared Slack-post utilities for reports that reply in the daily
'Metrics M/DD' thread in #alphalete-sales.

Each report:
  1. Finds today's parent thread (or fails with a friendly 'no header
     posted yet' error so the user knows what to do).
  2. Replies in that thread with an image + 'Report Name' comment.
  3. Adds a reaction emoji on the parent thread, matching Eve's
     manual flow (each metric has its own emoji on the parent post —
     e.g. 🔄 Ongoing Cancel, ❎ Disconnected New Internets).
"""
from __future__ import annotations

import datetime as dt
import os
import ssl
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
        f"SLACK_USER_TOKEN env var. See "
        f"automations/ongoing_cancel/SETUP.md for one-time install steps."
    )


def _client():
    import certifi
    from slack_sdk import WebClient
    ctx = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=_load_token(), ssl=ctx)


def find_metrics_thread_ts(client, today: dt.date) -> str:
    candidates = [
        f"Metrics {today.month}/{today.day}",
        f"Metrics {today.month:02d}/{today.day:02d}",
    ]
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
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


def post_reply_text_only(
    text: str,
    *,
    react_emoji: str | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
) -> dict:
    """Reply in today's Metrics thread with just a text message (no file
    attachment). Used by reports where 'nothing new' = a one-liner instead
    of an empty-state image. Still adds the parent-thread reaction so the
    metric is marked done on the header."""
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "would_post_text": text,
                "to_channel": CHANNEL_ID, "react_emoji": react_emoji}
    client = _client()
    thread_ts = find_metrics_thread_ts(client, today)
    resp = client.chat_postMessage(channel=CHANNEL_ID, thread_ts=thread_ts,
                                    text=text)
    out = {"ok": resp.get("ok"), "thread_ts": thread_ts, "ts": resp.get("ts")}
    if react_emoji:
        try:
            r = client.reactions_add(channel=CHANNEL_ID, timestamp=thread_ts,
                                     name=react_emoji)
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            out["reaction_warning"] = str(e)
    return out


def post_reply_with_image(
    image_path: Path,
    *,
    comment: str,
    react_emoji: str | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    file_name: str | None = None,
) -> dict:
    """Reply in today's Metrics thread with an image attachment + optional
    reaction emoji on the parent.

    react_emoji: short name WITHOUT colons, e.g. 'arrows_counterclockwise',
    'negative_squared_cross_mark'.
    """
    today = today or dt.date.today()
    if dry_run:
        return {
            "dry_run": True,
            "would_post_image": str(image_path),
            "to_channel": CHANNEL_ID,
            "comment": comment,
            "react_emoji": react_emoji,
        }
    client = _client()
    thread_ts = find_metrics_thread_ts(client, today)
    upload_resp = client.files_upload_v2(
        channel=CHANNEL_ID,
        thread_ts=thread_ts,
        file=str(image_path),
        filename=file_name or f"{comment} {today.month}.{today.day}.png",
        initial_comment=comment,
    )
    out = {
        "ok": upload_resp.get("ok"),
        "thread_ts": thread_ts,
        "file": upload_resp.get("file", {}).get("id"),
    }
    if react_emoji:
        try:
            r = client.reactions_add(
                channel=CHANNEL_ID, timestamp=thread_ts, name=react_emoji
            )
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            # Already-reacted is fine; surface other errors only.
            out["reaction_warning"] = str(e)
    return out

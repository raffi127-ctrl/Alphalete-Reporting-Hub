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
    """Read the xoxp- token from env var or file.

    Reads the file as utf-8-sig (auto-strips a leading BOM) because
    Windows Notepad + PowerShell 5.x's Set-Content default to writing
    UTF-8 *with* BOM. A BOM in the token corrupts the
    'Authorization: Bearer <token>' header — slack_sdk then crashes with
    'UnicodeEncodeError: latin-1 codec can't encode character \\ufeff'
    when urllib tries to send the request (Eve, 2026-05-28).
    """
    tok = os.environ.get("SLACK_USER_TOKEN")
    if tok:
        return tok.lstrip("﻿").strip()
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text(encoding="utf-8-sig").strip()
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


def _ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 4 → '4th', 11 → '11th', 21 → '21st'…"""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{'st' if n % 10 == 1 else 'nd' if n % 10 == 2 else 'rd' if n % 10 == 3 else 'th'}"


_SPANISH_MONTHS = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
    12: "diciembre",
}


def find_metrics_thread_ts(client, today: dt.date) -> str:
    """Find today's Metrics parent thread in #alphalete-sales.

    Primary match: the daily Slack Workflow that posts at 7:00 AM with
    display name 'Metrics' (bot_profile.name / username == 'Metrics').
    Its body text starts with 'for <date>:' rendered in the viewer's
    locale — no 'Metrics' word in the body, so identity match is the
    only reliable signal.

    Fallback: body-text match for manually-posted headers in either
    English ('Metrics for: May 28th 2026') or legacy short form
    ('Metrics 5/28'). Spanish month names included for completeness.
    """
    text_candidates = [
        f"Metrics for: {today.strftime('%B')} {_ordinal(today.day)} {today.year}",
        f"Metrics for: {today.strftime('%B')} {_ordinal(today.day)}",
        f"Metrics {today.month}/{today.day}",
        f"Metrics {today.month:02d}/{today.day:02d}",
        f"for {today.day} de {_SPANISH_MONTHS[today.month]} de {today.year}",
        f"for {today.day} de {_SPANISH_MONTHS[today.month]}",
    ]
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    resp = client.conversations_history(
        channel=CHANNEL_ID, oldest=str(oldest), limit=100
    )
    for msg in resp.get("messages", []):
        # Identity match — Workflow Builder bot named 'Metrics'.
        bot_name = (msg.get("bot_profile") or {}).get("name") or msg.get("username") or ""
        if bot_name.strip().lower() == "metrics":
            return msg.get("thread_ts") or msg.get("ts")
        # Body-text fallback for manual posts.
        text = msg.get("text", "")
        if any(c in text for c in text_candidates):
            return msg.get("thread_ts") or msg.get("ts")
    expected = (f"'Metrics for: {today.strftime('%B')} "
                f"{_ordinal(today.day)} {today.year}'")
    raise SlackPostError(
        f"Couldn't find today's {expected} header thread (or the Slack "
        f"workflow post) in #alphalete-sales. Post the header thread "
        f"there first, then click Run Again."
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


def post_reply_with_file(
    file_path: Path,
    *,
    comment: str,
    react_emoji: str | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    file_name: str | None = None,
) -> dict:
    """Reply in today's Metrics thread with an arbitrary file attachment
    (.xlsx, .csv, .pdf, etc.) + optional reaction emoji on the parent.

    Same shape as post_reply_with_image but the default upload filename
    preserves the source file's extension (instead of forcing .png), so
    Slack renders the right preview for spreadsheets / docs / etc.
    """
    today = today or dt.date.today()
    if dry_run:
        return {
            "dry_run": True,
            "would_post_file": str(file_path),
            "to_channel": CHANNEL_ID,
            "comment": comment,
            "react_emoji": react_emoji,
        }
    client = _client()
    thread_ts = find_metrics_thread_ts(client, today)
    default_name = f"{comment} {today.month}.{today.day}{file_path.suffix}"
    upload_resp = client.files_upload_v2(
        channel=CHANNEL_ID,
        thread_ts=thread_ts,
        file=str(file_path),
        filename=file_name or default_name,
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
            out["reaction_warning"] = str(e)
    return out

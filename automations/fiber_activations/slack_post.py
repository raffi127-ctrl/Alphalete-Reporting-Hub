"""Post the daily Fiber + Country screenshots to #level10-alphalete.

Flow (mirrors Eve's manual cadence, verified from the channel history):
  - The weekly parent thread is titled 'Activations Report Tracker WE MM.DD',
    where MM.DD is the WE Sunday of the current Wed→Tue cycle (the sheet's WE
    column = Sunday). A new one is created every Wednesday; the rest of the
    week each day's screenshots reply under it.
  - This module find-or-creates that parent (so a Wednesday run opens the new
    thread automatically), then replies with the two PNGs. The reply text ==
    the PNG file name (post name == file name).
  - On Wednesday only, the Fiber reply tags Rafael / Maud / Dylan.

Posts go out as the xoxp token's user (Eve / Evelyn Sobrino, U088E2KJEV8) —
the same token the other report posts use, loaded by the shared helper.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from automations.fiber_activations.pull import cycle_sunday
from automations.shared import slack_metrics_post as smp

CHANNEL_ID = "C075PCEL92M"  # #level10-alphalete (private)

# Tagged on the Wednesday (first-of-week) Fiber post only.
TAG_USER_IDS = ("U045Z8N0ZQC", "U045USN7NCD", "U048V0YA5FC")  # Rafael, Maud, Dylan


def thread_title(today: dt.date) -> str:
    """'Activations Report Tracker WE 05.31' — WE = cycle Sunday, zero-padded."""
    we = cycle_sunday(today)
    return f"Activations Report Tracker WE {we.month:02d}.{we.day:02d}"


def _find_thread_ts(client, title: str, today: dt.date):
    """Return the ts of this week's tracker parent, or None if not posted yet.

    Scans channel history back to the cycle's Wednesday. Matches on the title
    text (ignoring the surrounding *bold* markers the parent is posted with)."""
    we = cycle_sunday(today)
    cycle_wed = we - dt.timedelta(days=4)
    oldest = dt.datetime.combine(cycle_wed, dt.time.min).timestamp()
    resp = client.conversations_history(
        channel=CHANNEL_ID, oldest=str(oldest), limit=200
    )
    for msg in resp.get("messages", []):
        if title in (msg.get("text", "") or ""):
            return msg.get("thread_ts") or msg.get("ts")
    return None


def ensure_thread(client, today: dt.date) -> dict:
    """Find this week's tracker thread or create it (posted bold, as Eve)."""
    title = thread_title(today)
    ts = _find_thread_ts(client, title, today)
    if ts:
        return {"thread_ts": ts, "created": False, "title": title}
    resp = client.chat_postMessage(channel=CHANNEL_ID, text=f"*{title}*")
    return {"thread_ts": resp.get("ts"), "created": True, "title": title}


def _reply_image(client, thread_ts, path: Path, comment: str):
    return client.files_upload_v2(
        channel=CHANNEL_ID,
        thread_ts=thread_ts,
        file=str(path),
        filename=path.name,          # 'Fiber Activations Report by 5.30.png'
        initial_comment=comment,     # post name == file stem (bolded)
    )


def post_daily(
    fiber_path: Path,
    country_path: Path,
    today: dt.date,
    *,
    dry_run: bool = False,
) -> dict:
    """Reply with both PNGs in this week's tracker thread (creating it if the
    cycle just started). Returns a summary dict."""
    title = thread_title(today)
    is_wed = today.weekday() == 2

    # Post text == file name. Bold to match Eve's manual posts. Wednesday's
    # Fiber post also tags the three leads.
    fiber_comment = f"*{fiber_path.stem}*"
    if is_wed:
        fiber_comment += " " + " ".join(f"<@{u}>" for u in TAG_USER_IDS)
    country_comment = f"*{country_path.stem}*"

    if dry_run:
        return {
            "dry_run": True,
            "channel": CHANNEL_ID,
            "thread_title": title,
            "would_create_thread_if_missing": True,
            "tags_on_fiber": list(TAG_USER_IDS) if is_wed else [],
            "posts": [
                {"file": fiber_path.name, "comment": fiber_comment},
                {"file": country_path.name, "comment": country_comment},
            ],
        }

    client = smp._client()
    thread = ensure_thread(client, today)
    thread_ts = thread["thread_ts"]

    r1 = _reply_image(client, thread_ts, fiber_path, fiber_comment)
    r2 = _reply_image(client, thread_ts, country_path, country_comment)
    return {
        "ok": bool(r1.get("ok") and r2.get("ok")),
        "channel": CHANNEL_ID,
        "thread_title": title,
        "thread_ts": thread_ts,
        "thread_created": thread["created"],
        "fiber_file_id": r1.get("file", {}).get("id"),
        "country_file_id": r2.get("file", {}).get("id"),
        "tagged": list(TAG_USER_IDS) if is_wed else [],
    }

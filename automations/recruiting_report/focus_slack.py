"""DM the Carlos Daily Focus tab screenshot to the recruiting group.

After the 'Carlos Hidalgo' tab is filled, the daily run renders it to a PNG
(focus_render) and DMs it to a fixed group DM (Carlos + Elena + Valeria + Eve)
as the shared Slack user token's user. No channel post — this is a private
multi-person DM.

Reuses the shared token/client from slack_metrics_post (same xoxp- token the
other report posts use, posting as Evelyn Sobrino).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

from automations.shared import slack_metrics_post as smp

# Group-DM recipients (resolved + confirmed by Megan 2026-06-05). The posting
# token's own user (Eve) is added automatically by Slack, so this is exactly
# the four-person DM: Carlos, Elena, Valeria, Eve.
RECIPIENTS = {
    "Carlos Hidalgo":   "U046G04P5LG",
    "Elena Camargo":    "U0B1G4T0MUN",
    "Valeria Rodea":    "U06JQ4S1MRA",
    "Evelyn Sobrino":   "U088E2KJEV8",
}


def _caption(today: dt.date, summary: Optional[str]) -> str:
    # Format: "6/5/26 Daily Recruiting Focus Report".
    # Build M/D/YY by hand — %-m/%-d aren't Windows-safe (%y is fine).
    date_str = f"{today.month}/{today.day}/{today:%y}"
    # Slack mrkdwn bold = single asterisks. Bold the title line only.
    head = f"*{date_str} Daily Recruiting Focus Report*"
    return f"{head}\n{summary}" if summary else head


def post_carlos_screenshots(
    png_paths,
    today: Optional[dt.date] = None,
    summary: Optional[str] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Open the group DM and upload one or more PNGs in a single message.

    ``png_paths`` is a path or an ordered list of paths (3 owners each).
    The dated caption is the message's initial_comment; the images attach
    in top-to-bottom order. Returns a dict describing what was (or, on
    dry_run, would be) sent. Raises smp.SlackPostError on token / API error.
    """
    today = today or dt.date.today()
    if isinstance(png_paths, (str, Path)):
        png_paths = [png_paths]
    paths = [Path(p) for p in png_paths]
    user_ids = list(RECIPIENTS.values())
    caption = _caption(today, summary)

    if dry_run:
        return {
            "dry_run": True,
            "recipients": list(RECIPIENTS),
            "user_ids": user_ids,
            "files": [str(p) for p in paths],
            "caption": caption,
        }

    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise smp.SlackPostError(f"Screenshot(s) not found: {', '.join(missing)}")

    client = smp._client()

    # Open (or reuse) the multi-person DM with the four users.
    resp = client.conversations_open(users=",".join(user_ids))
    if not resp.get("ok"):
        raise smp.SlackPostError(f"conversations.open failed: {resp.get('error')}")
    channel = resp["channel"]["id"]

    n = len(paths)
    file_uploads = [
        {
            "file": str(p),
            "filename": p.name,
            "title": f"Daily Recruiting Focus — Carlos ({i} of {n})",
        }
        for i, p in enumerate(paths, 1)
    ]
    up = client.files_upload_v2(
        channel=channel,
        file_uploads=file_uploads,
        initial_comment=caption,
    )
    if not up.get("ok"):
        raise smp.SlackPostError(f"files.upload failed: {up.get('error')}")

    return {
        "dry_run": False,
        "channel": channel,
        "recipients": list(RECIPIENTS),
        "user_ids": user_ids,
        "files": [str(p) for p in paths],
        "caption": caption,
    }


# Back-compat alias (single screenshot → list of one).
post_carlos_screenshot = post_carlos_screenshots

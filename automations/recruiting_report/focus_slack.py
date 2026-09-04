"""DM a filled Daily Focus captainship tab to that captainship's group DM.

After a captainship's tab is filled, the daily run renders it to PNG(s)
(focus_shot) and DMs them to a fixed group DM as the shared Slack user token's
user. No channel post — these are private multi-person DMs.

Reuses the shared token/client from slack_metrics_post (same xoxp- token the
other report posts use — on the mini that token is 'Lucy Reporting', which is
who these DMs arrive from).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

from automations.shared import slack_metrics_post as smp

# Per-captainship group-DM recipients, keyed by the captainship name used in
# daily_focus.CAPTAINSHIPS / find_captainship_worksheet. The posting token's own
# user is auto-added by Slack to every group DM, so it is on each DM implicitly
# even when not listed.
#
# A captainship with no entry here simply gets no DM — daily_focus walks THIS
# dict, so deleting a key is the whole off-switch. The tab still fills.
#
# - "Colten Wright" / "Jairo Ruiz": confirmed by Megan 2026-07-15 when the two
#   new captainship tabs went live.
#
# RETIRED 2026-09-04 — "Carlos" (Carlos Hidalgo, Elena Camargo, Valeria Rodea,
# Evelyn Sobrino, Maud Miller; live since 2026-06-05). Carlos asked for it to
# stop ("can someone end this automation please") and Megan confirmed killing
# the whole DM, not just his seat in it — so nobody gets the Carlos-tab
# screenshot anymore. The Carlos tab still fills at 4am and 6:30pm like every
# other tab; only the DM is gone. To bring it back, restore the block below and
# nothing else:
#
#     "Carlos": {
#         "Carlos Hidalgo":   "U046G04P5LG",
#         "Elena Camargo":    "U0B1G4T0MUN",
#         "Valeria Rodea":    "U06JQ4S1MRA",
#         "Evelyn Sobrino":   "U088E2KJEV8",
#         "Maud Miller":      "U045USN7NCD",
#     },
FOCUS_DM_RECIPIENTS = {
    "Colten Wright": {
        "Colten Wright":    "U047M3AAN0G",
        "Eveliz Wright":    "U048WU3EUFJ",
        "Valeria Zavala":   "U054BLVL94N",
    },
    "Jairo Ruiz": {
        "Jairo Ruiz":       "U04Q6T14M34",
        "Colten Wright":    "U047M3AAN0G",
        "Analay Ruiz":      "U069URK7752",
    },
}


def _caption(today: dt.date, summary: Optional[str]) -> str:
    # Format: "6/5/26 Daily Recruiting Focus Report".
    # Build M/D/YY by hand — %-m/%-d aren't Windows-safe (%y is fine).
    date_str = f"{today.month}/{today.day}/{today:%y}"
    # Slack mrkdwn bold = single asterisks. Bold the title line only.
    head = f"*{date_str} Daily Recruiting Focus Report*"
    return f"{head}\n{summary}" if summary else head


def post_focus_screenshots(
    png_paths,
    recipients: dict,
    tab_label: str,
    today: Optional[dt.date] = None,
    summary: Optional[str] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Open a group DM with ``recipients`` and upload one or more PNGs.

    ``png_paths`` is a path or an ordered list of paths (3 owners each).
    ``recipients`` is a {display_name: user_id} map (the posting token's own
    user is auto-added by Slack). ``tab_label`` names the tab in the image
    titles (e.g. "Carlos", "Colten Wright"). The dated caption is the
    message's initial_comment; images attach top-to-bottom. Returns a dict
    describing what was (or, on dry_run, would be) sent. Raises
    smp.SlackPostError on token / API error.
    """
    today = today or dt.date.today()
    if isinstance(png_paths, (str, Path)):
        png_paths = [png_paths]
    paths = [Path(p) for p in png_paths]
    user_ids = list(recipients.values())
    caption = _caption(today, summary)

    if dry_run:
        return {
            "dry_run": True,
            "recipients": list(recipients),
            "user_ids": user_ids,
            "files": [str(p) for p in paths],
            "caption": caption,
        }

    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise smp.SlackPostError(f"Screenshot(s) not found: {', '.join(missing)}")

    client = smp._client()

    # Open (or reuse) the multi-person DM with the listed users.
    resp = client.conversations_open(users=",".join(user_ids))
    if not resp.get("ok"):
        raise smp.SlackPostError(f"conversations.open failed: {resp.get('error')}")
    channel = resp["channel"]["id"]

    n = len(paths)
    file_uploads = [
        {
            "file": str(p),
            "filename": p.name,
            "title": f"Daily Recruiting Focus — {tab_label} ({i} of {n})",
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
        "recipients": list(recipients),
        "user_ids": user_ids,
        "files": [str(p) for p in paths],
        "caption": caption,
    }


# The Carlos-only back-compat helpers (RECIPIENTS, post_carlos_screenshots,
# post_carlos_screenshot) went out with the Carlos DM on 2026-09-04. They read
# FOCUS_DM_RECIPIENTS["Carlos"] at import time, so leaving them would have made
# this module raise KeyError for every OTHER captainship's DM too.

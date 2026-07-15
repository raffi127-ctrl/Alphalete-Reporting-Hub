"""DM each filled Daily Focus captainship tab to its recruiting group DM.

After a captainship tab is filled, the daily run renders it to PNG(s)
(focus_render) and DMs them to that captainship's group (see
FOCUS_DM_RECIPIENTS). No channel post — these are private multi-person DMs.

Posts AS Lucy (the automated-reports identity, alphaletereporting@gmail.com)
via slack_metrics_post._bot_client() — so the DM comes from Lucy, not the
person running it. Prefers one shared group DM (needs Lucy's mpim:write scope)
and falls back to an individual DM per recipient if that scope is missing.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

from automations.shared import slack_metrics_post as smp

# Per-captainship group-DM recipients, keyed by the captainship name used in
# daily_focus.CAPTAINSHIPS / find_captainship_worksheet. The posting token's own
# user (Eve, U088E2KJEV8) is auto-added by Slack to every group DM, so she is on
# each DM implicitly even when not listed.
#
# - "Carlos": resolved + confirmed by Megan 2026-06-05 (Carlos, Elena, Valeria,
#   Eve, Maud).
# - "Colten Wright" / "Jairo Ruiz": confirmed by Megan 2026-07-15 when the two
#   new captainship tabs went live.
FOCUS_DM_RECIPIENTS = {
    "Carlos": {
        "Carlos Hidalgo":   "U046G04P5LG",
        "Elena Camargo":    "U0B1G4T0MUN",
        "Valeria Rodea":    "U06JQ4S1MRA",
        "Evelyn Sobrino":   "U088E2KJEV8",
        "Maud Miller":      "U045USN7NCD",
    },
    "Colten Wright": {
        "Colten Wright":    "U047M3AAN0G",
        "Rafael Hidalgo":   "U045Z8N0ZQC",
        "Megan Hidalgo":    "U04G5HJBGFN",
    },
    "Jairo Ruiz": {
        "Jairo Ruiz":       "U04Q6T14M34",
        "Colten Wright":    "U047M3AAN0G",
        "Rafael Hidalgo":   "U045Z8N0ZQC",
        "Megan Hidalgo":    "U04G5HJBGFN",
        "Analay Ruiz":      "U069URK7752",
    },
}

# Back-compat: the original Carlos-only constant.
RECIPIENTS = FOCUS_DM_RECIPIENTS["Carlos"]


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
    as_bot: bool = True,
) -> dict:
    """DM one or more PNGs of a captainship tab to ``recipients`` as Lucy.

    ``png_paths`` is a path or an ordered list of paths (3 owners each).
    ``recipients`` is a {display_name: user_id} map. ``tab_label`` names the
    tab in the image titles (e.g. "Carlos", "Colten Wright"). The dated caption
    is the message's initial_comment; images attach top-to-bottom.

    Posts via the Lucy bot token by default (``as_bot=True``) so the DM comes
    FROM Lucy, not the person running it (``as_bot=False`` uses the user token).
    Tries ONE shared group DM (needs Lucy's mpim:write scope); if that fails
    (missing scope or any group-open error), falls back to an individual DM per
    recipient (im:write) so the screenshots still reach everyone. Returns a dict
    describing what was (or, on dry_run, would be) sent; ``mode`` is 'group_dm'
    or 'individual_dms'. Raises smp.SlackPostError on token / total failure.
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
            "as_bot": as_bot,
        }

    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise smp.SlackPostError(f"Screenshot(s) not found: {', '.join(missing)}")

    # Post AS Lucy (bot token) by default so the DM is from the automated-
    # reports identity, not the user running it.
    client = smp._bot_client() if as_bot else smp._client()

    n = len(paths)

    def _file_uploads():
        return [
            {
                "file": str(p),
                "filename": p.name,
                "title": f"Daily Recruiting Focus — {tab_label} ({i} of {n})",
            }
            for i, p in enumerate(paths, 1)
        ]

    # Prefer ONE multi-person DM (single shared thread — needs mpim:write). If
    # Lucy lacks that scope (or the group open/upload fails), fall back to an
    # individual DM to each user (im:write) so everyone still gets the images.
    try:
        resp = client.conversations_open(users=",".join(user_ids))
        if not resp.get("ok"):
            raise smp.SlackPostError(f"conversations.open failed: {resp.get('error')}")
        channel = resp["channel"]["id"]
        up = client.files_upload_v2(
            channel=channel,
            file_uploads=_file_uploads(),
            initial_comment=caption,
        )
        if not up.get("ok"):
            raise smp.SlackPostError(f"files.upload failed: {up.get('error')}")
        return {
            "dry_run": False,
            "mode": "group_dm",
            "channel": channel,
            "recipients": list(recipients),
            "user_ids": user_ids,
            "files": [str(p) for p in paths],
            "caption": caption,
            "as_bot": as_bot,
        }
    except Exception as group_err:  # noqa: BLE001 — fall back to individual DMs
        channels = []
        last_err = group_err
        for uid in user_ids:
            try:
                r = client.conversations_open(users=uid)
                if not r.get("ok"):
                    last_err = smp.SlackPostError(
                        f"conversations.open failed for {uid}: {r.get('error')}")
                    continue
                ch = r["channel"]["id"]
                client.files_upload_v2(
                    channel=ch,
                    file_uploads=_file_uploads(),
                    initial_comment=caption,
                )
                channels.append(ch)
            except Exception as one_err:  # noqa: BLE001
                last_err = one_err
        if not channels:
            # Nobody got it — surface the original failure.
            raise last_err
        return {
            "dry_run": False,
            "mode": "individual_dms",
            "channels": channels,
            "recipients": list(recipients),
            "user_ids": user_ids,
            "files": [str(p) for p in paths],
            "caption": caption,
            "as_bot": as_bot,
        }


def post_carlos_screenshots(
    png_paths,
    today: Optional[dt.date] = None,
    summary: Optional[str] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Back-compat wrapper: post the Carlos tab to the Carlos group DM."""
    return post_focus_screenshots(
        png_paths, RECIPIENTS, "Carlos", today, summary, dry_run=dry_run)


# Back-compat alias (single screenshot → list of one).
post_carlos_screenshot = post_carlos_screenshots

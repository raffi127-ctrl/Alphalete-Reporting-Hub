"""Post the captured PNGs into three per-day Slack threads, in BOTH of Carlos's
channels (#alphalete-gp-sales + #a-players-b2b).

Threads (a bold dated parent, image replies underneath):
  * "Today's Activity"  — hourly replies, AT&T + Box, captioned by campaign+slot
  * "Time Tracker"      — same cadence
  * "B2B Dispositions"  — one reply per territory (AT&T + Box), at 6:30pm

Reuses the shared 'Lucy' user token (slack_metrics_post._client) + files_upload_v2,
exactly like tableau_screenshots. Slack can't share one thread across channels,
so each channel gets its own copy of each thread (find-or-create by dated title).

Idempotent per REPLY CAPTION: the day-orchestrator retries a failed run, and the
hourly cadence posts many times into the same parent, so "already posted" has to
be keyed on the exact caption (campaign + time-slot, or campaign + territory),
never a reply count.
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from typing import Dict, List, Optional

from automations.b2b_dispositions import config as cfg
from automations.shared import slack_metrics_post as smp


# Preview recipient: Megan Hidalgo. VERIFIED id (schedule_config warns a prior
# session DM'd Carlos's B2B images to Raf U045Z8N0ZQC by confusing them — Megan
# is U04G5HJBGFN; resolve via users.info if ever unsure).
PREVIEW_USER = "U04G5HJBGFN"


def preview_dm(specs: List[Dict], today: Optional[dt.date] = None, *,
               user: str = PREVIEW_USER, dry_run: bool = False) -> Dict:
    """DM each reply to `user` (Megan) for review — posts NOTHING to the channels.
    `specs` = [{'thread','caption','paths':[...]}]. A reply's images go in ONE DM
    message (matching the real 'both images in one reply'), so the preview shows
    exactly what the channel will get."""
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "to_user": user,
                "dms": [{"caption": s["caption"],
                         "files": [Path(p).name for p in s["paths"]]}
                        for s in specs]}
    client = smp._client()
    uid = smp._resolve_user_id(client, user)
    channel = client.conversations_open(users=uid)["channel"]["id"]
    sent, errors = [], []
    for s in specs:
        uploads = [{"file": str(Path(p)), "filename": Path(p).name}
                   for p in s["paths"] if Path(p).exists()]
        if not uploads:
            errors.append(f"{s['title']} (no files)")
            continue
        comment = f"*[preview]*  {s['title']}"
        try:
            client.files_upload_v2(file_uploads=uploads, channel=channel,
                                   initial_comment=comment)
            sent.append(s["title"])
            time.sleep(2)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s['title']}: {type(e).__name__} {str(e)[:80]}")
    return {"to_user": user, "sent": sent, "errors": errors, "ok": not errors}


def _short_mdy(today: dt.date) -> str:
    return f"{today.month}/{today.day}/{today.year % 100:02d}"


def thread_title(prefix: str, slot: str, today: Optional[dt.date] = None) -> str:
    """Parent text for one run's thread, e.g. 'Hourly Activity 7/30/26 - 4 PM'.
    ':00' is stripped so on-the-hour slots read '4 PM' (Megan 7/30)."""
    today = today or dt.date.today()
    return f"{prefix} {_short_mdy(today)} - {slot.replace(':00', '')}".strip()


def day_title(prefix: str, today: Optional[dt.date] = None) -> str:
    """Parent text for the ONE thread a day, e.g. 'Hourly Activity 8/6/26'.

    Deliberately carries no slot: that's what lets 12pm through 6:30pm all find
    the same parent instead of minting a thread an hour (Carlos 8/6)."""
    today = today or dt.date.today()
    return f"{prefix} {_short_mdy(today)}".strip()


def reply_caption(slot: str, mentions: Optional[List[str]] = None) -> str:
    """The per-run caption inside the day's thread: the time, then the people to
    notify. The mentions are the point — a thread that stays open all day stops
    generating notifications, so without them nobody sees the 4pm update."""
    who = " ".join("<@%s>" % u for u in (mentions or []))
    slot = (slot or "").replace(":00", "")
    return (slot + (" " + who if who else "")).strip()


def _reply_exists(client, channel: str, parent_ts: str, caption: str) -> bool:
    """Has this slot already been replied into the day's thread?

    Idempotency has to key on the REPLY now, not the parent. The parent lives all
    day, so "the thread exists" no longer means "this hour already posted" — and
    the orchestrator retries failed runs.
    """
    try:
        resp = client.conversations_replies(channel=channel, ts=parent_ts,
                                            limit=200)
    except Exception:  # noqa: BLE001
        return False
    for m in resp.get("messages", []):
        if m.get("ts") == parent_ts:
            continue
        if caption and caption in (m.get("text") or ""):
            return True
    return False


def day_title(prefix: str, today: Optional[dt.date] = None) -> str:
    """Parent text for the ONE thread a day, e.g. 'Hourly Activity 8/6/26'.

    Deliberately carries no slot: that's what lets 12pm through 6:30pm all find
    the same parent instead of minting a thread an hour (Carlos 8/6)."""
    today = today or dt.date.today()
    return f"{prefix} {_short_mdy(today)}".strip()


def reply_caption(slot: str, mentions: Optional[List[str]] = None) -> str:
    """The per-run caption inside the day's thread: the time, then the people to
    notify. The mentions are the point — a thread that stays open all day stops
    generating notifications, so without them nobody sees the 4pm update."""
    who = " ".join("<@%s>" % u for u in (mentions or []))
    slot = (slot or "").replace(":00", "")
    return (slot + (" " + who if who else "")).strip()


def _reply_exists(client, channel: str, parent_ts: str, caption: str) -> bool:
    """Has this slot already been replied into the day's thread?

    Idempotency has to key on the REPLY now, not the parent. The parent lives all
    day, so "the thread exists" no longer means "this hour already posted" — and
    the orchestrator does retry failed runs."""
    try:
        resp = client.conversations_replies(channel=channel, ts=parent_ts,
                                            limit=200)
    except Exception:  # noqa: BLE001
        return False
    for m in resp.get("messages", []):
        if m.get("ts") == parent_ts:
            continue
        if caption and caption in (m.get("text") or ""):
            return True
    return False


def post_daily_thread(prefix: str, slot: str, paths: List,
                      today: Optional[dt.date] = None, *,
                      dry_run: bool = False,
                      channels: Optional[List[str]] = None,
                      mentions: Optional[List[str]] = None) -> Dict:
    """ONE thread per day: find-or-create today's dated parent, then add this
    run's images as a reply captioned with the time slot and the people to tag
    (Carlos 8/6 — a thread per hour was burying the channel).

    Idempotent per SLOT inside the thread, not per parent."""
    today = today or dt.date.today()
    channels = channels or cfg.CHANNELS
    mentions = cfg.SLACK_MENTION_USERS if mentions is None else mentions
    title = day_title(prefix, today)
    caption = reply_caption(slot, mentions)
    slot_key = (slot or "").replace(":00", "")

    if dry_run:
        return {"dry_run": True, "title": title, "caption": caption,
                "channels": [cfg.CHANNEL_LABEL.get(c, c) for c in channels],
                "files": [Path(p).name for p in paths]}

    client = smp._client()
    results = []
    for channel in channels:
        clabel = cfg.CHANNEL_LABEL.get(channel, channel)
        try:
            uploads = [{"file": str(Path(p)), "filename": Path(p).name}
                       for p in paths if Path(p).exists()]
            if not uploads:
                results.append({"channel": clabel, "ok": False,
                                "error": "no image files"})
                continue
            ts = _find_parent_ts(client, channel, title, today)
            if ts is None:
                parent = client.chat_postMessage(channel=channel,
                                                 text=f"*{title}*")
                ts = parent.get("ts")
            elif _reply_exists(client, channel, ts, slot_key):
                results.append({"channel": clabel, "skipped": True, "ok": True})
                continue
            up = client.files_upload_v2(file_uploads=uploads, channel=channel,
                                        thread_ts=ts, initial_comment=caption)
            results.append({"channel": clabel, "ts": ts,
                            "ok": up.get("ok", True)})
        except Exception as e:  # noqa: BLE001
            results.append({"channel": clabel, "ok": False,
                            "error": f"{type(e).__name__}: {str(e)[:140]}"})
    return {"title": title, "caption": caption,
            "ok": all(r.get("ok") for r in results), "channels": results}


def retitle_today(old_title: str, new_title: str,
                  today: Optional[dt.date] = None) -> Dict:
    """chat_update today's parent whose text contains `old_title` -> `new_title`,
    in every channel. Runs as Lucy (the author) — only the message's author can
    edit it. One-off cleanup (e.g. dropping an errant '(Final)' tag)."""
    today = today or dt.date.today()
    client = smp._client()
    out = []
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    for channel in cfg.CHANNELS:
        clabel = cfg.CHANNEL_LABEL.get(channel, channel)
        try:
            resp = client.conversations_history(
                channel=channel, oldest=str(oldest), limit=200)
            hit = next((m for m in resp.get("messages", [])
                        if old_title in (m.get("text") or "")), None)
            if not hit:
                out.append(f"{clabel}: not found")
                continue
            client.chat_update(channel=channel, ts=hit["ts"],
                               text=f"*{new_title}*")
            out.append(f"{clabel}: updated")
        except Exception as e:  # noqa: BLE001
            out.append(f"{clabel}: FAIL {type(e).__name__} {str(e)[:60]}")
    return {"old": old_title, "new": new_title, "results": out}


def _title_exists(client, channel: str, title: str, today: dt.date) -> bool:
    """Has this exact titled thread already posted in `channel` today? Guards a
    duplicate on an orchestrator retry — each hour's title is unique, so a match
    means this hour already went out."""
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    try:
        resp = client.conversations_history(
            channel=channel, oldest=str(oldest), limit=200)
    except Exception:
        return False
    for msg in resp.get("messages", []):
        if title in (msg.get("text", "") or ""):
            return True
    return False


def _find_parent_ts(client, channel: str, title: str, today: dt.date):
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    try:
        resp = client.conversations_history(
            channel=channel, oldest=str(oldest), limit=200)
    except Exception:
        return None
    for m in resp.get("messages", []):
        if title in (m.get("text") or ""):
            return m.get("thread_ts") or m.get("ts")
    return None


def post_daily_thread(prefix: str, slot: str, paths: List,
                      today: Optional[dt.date] = None, *,
                      dry_run: bool = False,
                      channels: Optional[List[str]] = None,
                      mentions: Optional[List[str]] = None) -> Dict:
    """ONE thread per day: find-or-create today's dated parent, then add this
    run's images as a reply captioned with the time slot and the people to tag
    (Carlos 8/6 — an hourly thread each was burying the channel).

    Idempotent per SLOT within the thread, not per parent: the parent now
    survives all day, so its existence says nothing about whether this hour
    already went out, and the orchestrator does retry.
    """
    today = today or dt.date.today()
    channels = channels or cfg.CHANNELS
    mentions = cfg.SLACK_MENTION_USERS if mentions is None else mentions
    title = day_title(prefix, today)
    caption = reply_caption(slot, mentions)
    slot_key = (slot or "").replace(":00", "")

    if dry_run:
        return {"dry_run": True, "title": title, "caption": caption,
                "channels": [cfg.CHANNEL_LABEL.get(c, c) for c in channels],
                "files": [Path(p).name for p in paths]}

    client = smp._client()
    results = []
    for channel in channels:
        clabel = cfg.CHANNEL_LABEL.get(channel, channel)
        try:
            uploads = [{"file": str(Path(p)), "filename": Path(p).name}
                       for p in paths if Path(p).exists()]
            if not uploads:
                results.append({"channel": clabel, "ok": False,
                                "error": "no image files"})
                continue
            ts = _find_parent_ts(client, channel, title, today)
            if ts is None:
                parent = client.chat_postMessage(channel=channel,
                                                 text=f"*{title}*")
                ts = parent.get("ts")
            elif _reply_exists(client, channel, ts, slot_key):
                results.append({"channel": clabel, "skipped": True, "ok": True})
                continue
            up = client.files_upload_v2(file_uploads=uploads, channel=channel,
                                        thread_ts=ts, initial_comment=caption)
            results.append({"channel": clabel, "ts": ts,
                            "ok": up.get("ok", True)})
        except Exception as e:  # noqa: BLE001
            results.append({"channel": clabel, "ok": False,
                            "error": f"{type(e).__name__}: {str(e)[:140]}"})
    return {"title": title, "caption": caption,
            "ok": all(r.get("ok") for r in results), "channels": results}


def post_thread(title: str, paths: List, today: Optional[dt.date] = None, *,
                dry_run: bool = False, channels: Optional[List[str]] = None,
                repost: bool = False) -> Dict:
    """Post ONE new thread per run: a titled parent ('Hourly Activity 7/30/26 -
    4 PM') plus a single reply carrying the images. NO pinning — each hour is its
    own thread so nothing gets lost (Megan 7/30). Idempotent per title.

    repost=True: find TODAY's existing parent with this title and add the images
    as a NEW reply to it (for re-posting corrected photos into a thread whose old
    photos were deleted); creates the parent only if it doesn't exist."""
    today = today or dt.date.today()
    channels = channels or cfg.CHANNELS
    if dry_run:
        return {"dry_run": True, "title": title, "repost": repost,
                "channels": [cfg.CHANNEL_LABEL.get(c, c) for c in channels],
                "files": [Path(p).name for p in paths]}
    client = smp._client()
    results = []
    for channel in channels:
        clabel = cfg.CHANNEL_LABEL.get(channel, channel)
        try:
            uploads = [{"file": str(Path(p)), "filename": Path(p).name}
                       for p in paths if Path(p).exists()]
            if not uploads:
                results.append({"channel": clabel, "ok": False,
                                "error": "no image files"})
                continue
            ts = None
            if repost:
                ts = _find_parent_ts(client, channel, title, today)
            elif _title_exists(client, channel, title, today):
                results.append({"channel": clabel, "skipped": True, "ok": True})
                continue
            if ts is None:
                parent = client.chat_postMessage(channel=channel, text=f"*{title}*")
                ts = parent.get("ts")
            up = client.files_upload_v2(file_uploads=uploads, channel=channel,
                                        thread_ts=ts)
            results.append({"channel": clabel, "ts": ts,
                            "ok": up.get("ok", True),
                            "mode": "repost" if repost else "new"})
        except Exception as e:  # noqa: BLE001
            results.append({"channel": clabel, "ok": False,
                            "error": f"{type(e).__name__}: {str(e)[:140]}"})
    return {"title": title, "ok": all(r.get("ok") for r in results),
            "channels": results}

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
            errors.append(f"{s['caption']} (no files)")
            continue
        comment = f"*[preview → {s['thread']}]*  {s['caption']}"
        try:
            client.files_upload_v2(file_uploads=uploads, channel=channel,
                                   initial_comment=comment)
            sent.append(s["caption"])
            time.sleep(2)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s['caption']}: {type(e).__name__} {str(e)[:80]}")
    return {"to_user": user, "sent": sent, "errors": errors, "ok": not errors}


def parent_title(thread_name: str, today: dt.date) -> str:
    return f"{thread_name} — {today.month}/{today.day}/{today.year}"


def parent_text(thread_name: str, today: dt.date) -> str:
    return f"*{parent_title(thread_name, today)}*"


def find_parent_ts(client, channel: str, thread_name: str,
                   today: dt.date) -> Optional[str]:
    """ts of today's parent for `thread_name` in `channel`, or None."""
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    title = parent_title(thread_name, today)
    resp = client.conversations_history(
        channel=channel, oldest=str(oldest), limit=200)
    for msg in resp.get("messages", []):
        if title in (msg.get("text", "") or ""):
            return msg.get("thread_ts") or msg.get("ts")
    return None


def ensure_parent(client, channel: str, thread_name: str,
                  today: dt.date) -> str:
    ts = find_parent_ts(client, channel, thread_name, today)
    if ts:
        return ts
    resp = client.chat_postMessage(
        channel=channel, text=parent_text(thread_name, today))
    return resp.get("ts")


def refresh_pin(client, channel: str, thread_name: str, today: dt.date,
                parent_ts: str) -> None:
    """Keep TODAY's header pinned in `channel` and unpin any prior day's for this
    thread — so the current day's thread is always the pinned one at the top
    (Megan 7/29). Best-effort: needs pins:read + pins:write on the Lucy token; a
    missing scope just logs, never fails the post."""
    today_title = parent_title(thread_name, today)
    try:
        pins = client.pins_list(channel=channel).get("items", [])
    except Exception as e:  # noqa: BLE001
        print(f"  pins_list failed on {cfg.CHANNEL_LABEL.get(channel, channel)} "
              f"({type(e).__name__}) — is pins:read granted?", flush=True)
        pins = []
    for it in pins:
        m = it.get("message") or {}
        txt = (m.get("text") or "").replace("&amp;", "&")
        # A prior day's header for THIS thread: carries the thread name but not
        # today's dated title.
        if thread_name in txt and today_title not in txt and m.get("ts"):
            try:
                client.pins_remove(channel=channel, timestamp=m["ts"])
            except Exception:
                pass
    try:
        client.pins_add(channel=channel, timestamp=parent_ts)
    except Exception as e:  # noqa: BLE001
        # already_pinned is fine; anything else is likely a scope gap worth a note
        if "already_pinned" not in str(e):
            print(f"  pins_add failed on {cfg.CHANNEL_LABEL.get(channel, channel)} "
                  f"({str(e)[:60]}) — is pins:write granted?", flush=True)


def _existing_captions(client, channel: str, thread_ts: str) -> set:
    """Captions already posted under today's parent (for idempotency). Slack
    stores '&' as '&amp;' — un-escape so 'AT&T — 1:00 PM' matches."""
    resp = client.conversations_replies(channel=channel, ts=thread_ts, limit=300)
    out = set()
    for m in resp.get("messages", []):
        if m.get("ts") == thread_ts:
            continue
        txt = (m.get("text") or "").replace("&amp;", "&")
        if txt:
            out.add(txt.strip())
    return out


def post_replies(thread_name: str, replies: List[Dict],
                 today: Optional[dt.date] = None, *, dry_run: bool = False,
                 channels: Optional[List[str]] = None) -> Dict:
    """Post each reply (PNG + caption) under today's `thread_name` parent, in
    every channel. `replies` = [{'caption': str, 'path': Path}, ...] in order.

    dry_run reports what WOULD post (and to where) without touching Slack.
    Idempotent: a caption already in the thread is skipped, so re-running the
    same time-slot never duplicates."""
    today = today or dt.date.today()
    channels = channels or cfg.CHANNELS

    if dry_run:
        return {"dry_run": True, "thread": thread_name,
                "channels": [cfg.CHANNEL_LABEL.get(c, c) for c in channels],
                "parent": parent_text(thread_name, today),
                "replies": [{"caption": r["caption"],
                             "files": [Path(p).name for p in r["paths"]]}
                            for r in replies]}

    client = smp._client()
    results = []
    for channel in channels:
        clabel = cfg.CHANNEL_LABEL.get(channel, channel)
        try:
            thread_ts = ensure_parent(client, channel, thread_name, today)
            refresh_pin(client, channel, thread_name, today, thread_ts)
            already = _existing_captions(client, channel, thread_ts)
            posted, skipped = [], []
            for r in replies:
                caption = f"*{r['caption']}*"
                if r["caption"] in already or caption in already:
                    skipped.append(r["caption"])
                    continue
                # One reply message can carry MULTIPLE files (the hourly reply
                # attaches both campaign images together — Megan 7/29).
                uploads = [{"file": str(Path(p)), "filename": Path(p).name}
                           for p in r["paths"] if Path(p).exists()]
                if not uploads:
                    skipped.append(f"{r['caption']} (no files)")
                    continue
                up = client.files_upload_v2(
                    file_uploads=uploads, channel=channel, thread_ts=thread_ts,
                    initial_comment=caption)
                posted.append({"caption": r["caption"], "ok": up.get("ok")})
                # Slack posts a big file's message later than a small one queued
                # after it; pause so replies land in order.
                time.sleep(3)
            results.append({"channel": clabel, "thread_ts": thread_ts,
                            "posted": posted, "skipped": skipped, "ok": True})
        except Exception as e:  # noqa: BLE001
            results.append({"channel": clabel, "ok": False,
                            "error": f"{type(e).__name__}: {str(e)[:140]}"})
    return {"thread": thread_name, "ok": all(r.get("ok") for r in results),
            "channels": results}

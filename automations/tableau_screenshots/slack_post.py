"""Post the captured tracker PNGs into their OWN dated thread -- in BOTH
#alphalete-sales AND #top-leaders-alphalete-org.

Each channel gets its OWN copy of the thread (Slack can't share one thread across
channels): a bold dated parent + one ":emoji: Tracker Name" line per tracker,
then each PNG as a threaded reply captioned "*Tracker Name - Mon D*" with the
tracker's emoji reacted onto the parent (the header's checkmark-emoji row).

Layout mirrors the Metrics thread (Megan 2026-07-04). The automation creates its
OWN parent in each channel each morning (find-or-create), posted AS Lucy -- no
human, no dependency on Jolie's post, not the Metrics thread.

Reuses the shared Slack token path (slack_metrics_post._client -> the 'Lucy'
xoxp user token that daily_metrics uses) and files_upload_v2.

NOTE: #top-leaders-alphalete-org (C067TTGFEFR) is PRIVATE -- Lucy must be a
member or files_upload_v2 there fails with not_in_channel.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from automations.shared import slack_metrics_post as smp

# Post to BOTH channels. Set TABLEAU_TRACKERS_CHANNEL_ID to a single scratch
# channel while building to keep the real channels safe (overrides the whole list).
_ALPHALETE_SALES = "C068PH3RFSM"          # #alphalete-sales
_TOP_LEADERS = "C067TTGFEFR"              # #top-leaders-alphalete-org (private)
_override = os.environ.get("TABLEAU_TRACKERS_CHANNEL_ID")
CHANNELS = [_override] if _override else [_ALPHALETE_SALES, _TOP_LEADERS]

TITLE_PREFIX = "Alphalete Tableau Trackers"


def header_title(today: dt.date) -> str:
    """'Alphalete Tableau Trackers 7/4/2026' (M/D/YYYY, matches Megan's spec)."""
    return f"{TITLE_PREFIX} {today.month}/{today.day}/{today.year}"


def header_text(pages: list, today: dt.date) -> str:
    """Bold dated title + one ':react: Title' line per tracker (parent message)."""
    lines = [f"*{header_title(today)}*", ""]
    lines += [f":{p['react']}: {p['title']}" for p in pages]
    return "\n".join(lines)


def reply_caption(spec: dict, today: dt.date) -> str:
    """'*AT&T Internet Country Sales Tracker - Jul 4*' -- bold, name + date."""
    return f"*{spec['title']} - {today.strftime('%b')} {today.day}*"


def find_thread_ts(client, channel: str, today: dt.date):
    """ts of today's tracker parent in `channel`, or None if not posted yet."""
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    title = header_title(today)
    resp = client.conversations_history(
        channel=channel, oldest=str(oldest), limit=200)
    for msg in resp.get("messages", []):
        if title in (msg.get("text", "") or ""):
            return msg.get("thread_ts") or msg.get("ts")
    return None


def ensure_thread(client, channel: str, pages: list, today: dt.date) -> dict:
    """Find today's tracker parent in `channel` or create it (bold header, Lucy)."""
    ts = find_thread_ts(client, channel, today)
    if ts:
        return {"thread_ts": ts, "created": False}
    resp = client.chat_postMessage(channel=channel, text=header_text(pages, today))
    return {"thread_ts": resp.get("ts"), "created": True}


def _post_to_channel(client, channel: str, captures: list, pages: list,
                     today: dt.date) -> dict:
    """Ensure the parent + post every image reply (with parent reaction) in one
    channel. A failure in one channel is caught by the caller so the other still
    posts."""
    thread = ensure_thread(client, channel, pages, today)
    thread_ts = thread["thread_ts"]
    results = []
    for spec, png in captures:
        up = client.files_upload_v2(
            channel=channel, thread_ts=thread_ts, file=str(png),
            filename=Path(png).name, initial_comment=reply_caption(spec, today))
        out = {"id": spec["id"], "ok": up.get("ok"),
               "file": (up.get("file") or {}).get("id")}
        try:
            r = client.reactions_add(
                channel=channel, timestamp=thread_ts, name=spec["react"])
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            out["reaction_warning"] = str(e)[:80]
        results.append(out)
    return {"channel": channel, "thread_ts": thread_ts,
            "created": thread["created"], "posted": results,
            "ok": all(r.get("ok") for r in results) if results else False}


def _preview_into(client, channel: str, captures: list, pages: list,
                  today: dt.date) -> dict:
    """Post the PREVIEW thread (banner header + image replies) into one DM/MPIM."""
    banner = ("*(PREVIEW — this is what will post to #alphalete-sales and "
              "#top-leaders-alphalete-org; nothing has been posted to the "
              "channels yet.)*\n\n")
    hdr = client.chat_postMessage(channel=channel,
                                  text=banner + header_text(pages, today))
    ts = hdr["ts"]
    posted = []
    for spec, png in captures:
        up = client.files_upload_v2(
            channel=channel, thread_ts=ts, file=str(png),
            filename=Path(png).name, initial_comment=reply_caption(spec, today))
        posted.append({"id": spec["id"], "ok": up.get("ok")})
    return {"channel": channel, "thread_ts": ts, "posted": posted,
            "ok": all(p.get("ok") for p in posted) if posted else False}


def preview_dm(captures: list, pages: list, users: list,
               today: dt.date | None = None, *, dry_run: bool = False) -> dict:
    """DM the full thread (header + real image replies) to `users` for review,
    posting NOTHING to the channels. Tries one group DM (both people in one
    thread); falls back to an individual DM each if the workspace blocks MPIMs.
    Sent AS Lucy (the identity that will post for real)."""
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "to_users": users,
                "header": header_text(pages, today),
                "replies": [{"file": Path(p).name,
                             "caption": reply_caption(s, today)}
                            for s, p in captures]}
    # Use the USER token (_client) -- on the mini that's Lucy, and it's the token
    # rashad_metrics' review run already uses to DM Megan + Raf (the bot token
    # isn't installed on the mini).
    client = smp._client()
    user_ids = [smp._resolve_user_id(client, u) for u in users]
    try:
        channel = client.conversations_open(
            users=",".join(user_ids))["channel"]["id"]
        res = _preview_into(client, channel, captures, pages, today)
        return {"ok": res["ok"], "mode": "group_dm", "user_ids": user_ids,
                **res}
    except Exception as e:
        print(f"  group DM unavailable ({type(e).__name__}) — DMing each "
              f"individually.", flush=True)
        results = []
        for uid in user_ids:
            ch = client.conversations_open(users=uid)["channel"]["id"]
            results.append(_preview_into(client, ch, captures, pages, today))
        return {"ok": all(r["ok"] for r in results), "mode": "individual_dms",
                "user_ids": user_ids, "results": results}


def post_all(captures: list, pages: list, today: dt.date | None = None,
             *, dry_run: bool = False) -> dict:
    """Post the thread + one image reply per captured tracker, to every channel
    in CHANNELS. `captures` is (spec, png_path) in post order; `pages` is the full
    ordered list used to build the header (so the header lists every tracker even
    if one failed to capture)."""
    today = today or dt.date.today()

    if dry_run:
        return {
            "dry_run": True,
            "channels": list(CHANNELS),
            "header": header_text(pages, today),
            "replies": [
                {"file": Path(p).name, "caption": reply_caption(spec, today),
                 "react": spec["react"]}
                for spec, p in captures
            ],
        }

    client = smp._client()
    channel_results = []
    for channel in CHANNELS:
        try:
            channel_results.append(
                _post_to_channel(client, channel, captures, pages, today))
        except Exception as e:
            channel_results.append(
                {"channel": channel, "ok": False,
                 "error": f"{type(e).__name__}: {str(e)[:120]}"})

    return {
        "ok": all(c.get("ok") for c in channel_results) if channel_results else False,
        "channels": channel_results,
    }

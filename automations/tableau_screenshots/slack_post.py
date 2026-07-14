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
import time
from pathlib import Path

from automations.shared import slack_metrics_post as smp

# The same 8 COUNTRY-wide trackers go to three orgs (Raf, 2026-07-14). Same
# images everywhere -- these are country/org-wide boards, not per-office cuts,
# which is why the title dropped "Alphalete". One card per org on the Hub, same
# convention as rashad_metrics (#elevate-sales) / aya_metrics (#indelible-sales).
# Lucy (U0BCFGCR5PV) is a MEMBER of all four channels -- verified 2026-07-14. The
# three private ones (#top-leaders, #elevate-sales, #indelible-sales) fail
# files_upload_v2 with not_in_channel if she is ever removed.
ORG_CHANNELS = {
    "alphalete":   ["C068PH3RFSM",        # #alphalete-sales
                    "C067TTGFEFR"],       # #top-leaders-alphalete-org (private)
    "elevate":     ["C0B3KTCCMT7"],       # #elevate-sales (private)
    "indelible":   ["C0AA85Y3FPE"],       # #indelible-sales (private)
    "palace":      ["C09AVM17PAR"],       # #palace-sales (private)
    "elite_prime": ["C06A6A8ED34"],       # #elite-prime-sales (private)
}
ORGS = list(ORG_CHANNELS)
DEFAULT_ORG = "alphalete"

# Human labels for the Hub card / logs.
ORG_LABEL = {"alphalete": "#alphalete-sales + #top-leaders-alphalete-org",
             "elevate": "#elevate-sales",
             "indelible": "#indelible-sales",
             "palace": "#palace-sales",
             "elite_prime": "#elite-prime-sales"}


def channels_for(org: str) -> list:
    """The channel id(s) this org posts into. Set TABLEAU_TRACKERS_CHANNEL_ID to a
    single scratch channel while building to keep every real channel safe (it
    overrides the whole list, for every org)."""
    override = os.environ.get("TABLEAU_TRACKERS_CHANNEL_ID")
    if override:
        return [override]
    try:
        return list(ORG_CHANNELS[org])
    except KeyError:
        raise SystemExit(f"unknown org {org!r}. known: {', '.join(ORGS)}")


TITLE_PREFIX = "Tableau Country Trackers"
# The pre-2026-07-14 title. Kept ONLY so find_thread_ts still recognises a thread
# posted under the old name (otherwise a same-day rerun would not find today's
# parent and would post a SECOND tracker thread into the channel). Retitled in
# place on the next touch; delete this once no live thread uses it.
_LEGACY_TITLE_PREFIX = "Alphalete Tableau Trackers"


def header_title(today: dt.date) -> str:
    """'Tableau Country Trackers 7/14/2026' (M/D/YYYY, matches Megan's spec)."""
    return f"{TITLE_PREFIX} {today.month}/{today.day}/{today.year}"


def _legacy_title(today: dt.date) -> str:
    return f"{_LEGACY_TITLE_PREFIX} {today.month}/{today.day}/{today.year}"


def header_text(pages: list, today: dt.date) -> str:
    """Bold dated title + one ':react: Title' line per tracker (parent message)."""
    lines = [f"*{header_title(today)}*", ""]
    lines += [f":{p['react']}: {p['title']}" for p in pages]
    return "\n".join(lines)


def reply_caption(spec: dict, today: dt.date) -> str:
    """'*AT&T Internet Country Sales Tracker - Jul 4*' -- bold, name + date."""
    return f"*{spec['title']} - {today.strftime('%b')} {today.day}*"


def find_thread_ts(client, channel: str, today: dt.date):
    """(ts, is_legacy) of today's tracker parent in `channel`, or (None, False).

    Matches the CURRENT title first, then the legacy one — a thread posted this
    morning under the old name must still be found, or a rerun would post a
    second tracker thread into the same channel."""
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    title, legacy = header_title(today), _legacy_title(today)
    resp = client.conversations_history(
        channel=channel, oldest=str(oldest), limit=200)
    msgs = resp.get("messages", [])
    for msg in msgs:
        if title in (msg.get("text", "") or ""):
            return (msg.get("thread_ts") or msg.get("ts")), False
    for msg in msgs:
        if legacy in (msg.get("text", "") or ""):
            return (msg.get("thread_ts") or msg.get("ts")), True
    return None, False


def ensure_thread(client, channel: str, pages: list, today: dt.date) -> dict:
    """Find today's tracker parent in `channel` or create it (bold header, Lucy).
    A parent still carrying the legacy title is RETITLED in place, so today's
    thread ends up reading the same as every other channel's."""
    ts, is_legacy = find_thread_ts(client, channel, today)
    if ts:
        if is_legacy:
            try:
                client.chat_update(channel=channel, ts=ts,
                                   text=header_text(pages, today))
                print(f"  {channel}: retitled today's parent → {header_title(today)}",
                      flush=True)
            except Exception as e:
                print(f"  {channel}: retitle skipped ({type(e).__name__})", flush=True)
        return {"thread_ts": ts, "created": False}
    resp = client.chat_postMessage(channel=channel, text=header_text(pages, today))
    return {"thread_ts": resp.get("ts"), "created": True}


def delete_image_replies(client, channel: str, thread_ts: str) -> int:
    """Delete every IMAGE reply under today's parent (the parent itself is never
    touched, so the thread link + its reactions survive). Used by --replace to
    re-post a corrected set of images IN ORDER: Slack appends replies, so a single
    re-upload would land at the bottom instead of in its header position."""
    resp = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    deleted = 0
    for msg in resp.get("messages", []):
        if msg.get("ts") == thread_ts or not msg.get("files"):
            continue
        for f in msg.get("files") or []:
            try:
                client.files_delete(file=f["id"])
            except Exception:
                pass          # already gone, or removed with the message
        try:
            client.chat_delete(channel=channel, ts=msg["ts"])
            deleted += 1
        except Exception:
            pass              # files_delete can take the message with it
    return deleted


def count_image_replies(client, channel: str, thread_ts: str) -> int:
    """How many image replies today's parent already has."""
    resp = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    return sum(1 for m in resp.get("messages", [])
               if m.get("ts") != thread_ts and m.get("files"))


def _post_to_channel(client, channel: str, captures: list, pages: list,
                     today: dt.date, replace: bool = False) -> dict:
    """Ensure the parent + post every image reply (with parent reaction) in one
    channel. A failure in one channel is caught by the caller so the others still
    post.

    IDEMPOTENT — posting the same day twice must not duplicate. This matters
    because a partial run exits non-zero and the ORCHESTRATOR RETRIES IT (up to
    MAX_RUN_RETRIES): without this, every retry would append another 8 images to
    the channels that already succeeded, so healing one broken channel would
    trash the healthy ones. Per channel:
      already has the full set -> SKIP (ok, nothing posted)
      has a partial set        -> clear + re-post (heal a half-finished upload)
      has none                 -> post
      replace=True             -> always clear + re-post, in header order
    """
    thread = ensure_thread(client, channel, pages, today)
    thread_ts = thread["thread_ts"]
    removed = 0
    existing = 0 if thread["created"] else count_image_replies(client, channel,
                                                               thread_ts)
    if not replace and existing >= len(captures) > 0:
        print(f"  {channel}: already has {existing} image(s) today — skipping "
              f"(nothing re-posted)", flush=True)
        return {"channel": channel, "thread_ts": thread_ts, "created": False,
                "posted": [], "removed": 0, "skipped": True, "ok": True}
    if (replace or existing) and not thread["created"]:
        removed = delete_image_replies(client, channel, thread_ts)
        if removed:
            why = "replacing" if replace else "healing a partial set"
            print(f"  {channel}: cleared {removed} old image reply(ies) ({why})",
                  flush=True)
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
        # Slack posts a large file's message LATER than a small one uploaded
        # after it, so images land out of header order. Pause so each image's
        # message posts before the next upload starts (keeps them in order).
        time.sleep(3)
    return {"channel": channel, "thread_ts": thread_ts,
            "created": thread["created"], "posted": results, "removed": removed,
            "skipped": False,
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


def retitle_today(pages: list, today: dt.date | None = None,
                  *, org: str = DEFAULT_ORG) -> dict:
    """Rename today's ALREADY-POSTED parent to the current title, touching nothing
    else. For the day the title changes: the images under the old thread are fine,
    so re-posting them just to fix the header would churn every reply's timestamp.
    Never creates a thread; a no-op if today's parent is already current."""
    today = today or dt.date.today()
    client = smp._client()
    out = []
    for channel in channels_for(org):
        ts, is_legacy = find_thread_ts(client, channel, today)
        if not ts:
            out.append({"channel": channel, "status": "no thread today"})
            continue
        if not is_legacy:
            out.append({"channel": channel, "status": "already current"})
            continue
        try:
            client.chat_update(channel=channel, ts=ts,
                               text=header_text(pages, today))
            out.append({"channel": channel, "status": "retitled", "ts": ts})
        except Exception as e:
            out.append({"channel": channel,
                        "status": f"FAILED {type(e).__name__}: {str(e)[:80]}"})
    return {"org": org, "results": out}


def post_all(captures: list, pages: list, today: dt.date | None = None,
             *, dry_run: bool = False, replace: bool = False,
             org: str = DEFAULT_ORG) -> dict:
    """Post the thread + one image reply per captured tracker, to every channel
    this ORG posts into. `captures` is (spec, png_path) in post order; `pages` is
    the full ordered list used to build the header (so the header lists every
    tracker even if one failed to capture). replace=True re-posts today's thread:
    clear the old image replies, then post this set in order (for a same-day crop
    fix)."""
    today = today or dt.date.today()
    channels = channels_for(org)

    if dry_run:
        return {
            "dry_run": True,
            "replace": replace,
            "org": org,
            "channels": list(channels),
            "header": header_text(pages, today),
            "replies": [
                {"file": Path(p).name, "caption": reply_caption(spec, today),
                 "react": spec["react"]}
                for spec, p in captures
            ],
        }

    client = smp._client()
    channel_results = []
    for channel in channels:
        try:
            channel_results.append(
                _post_to_channel(client, channel, captures, pages, today,
                                 replace=replace))
        except Exception as e:
            channel_results.append(
                {"channel": channel, "ok": False,
                 "error": f"{type(e).__name__}: {str(e)[:120]}"})

    return {
        "ok": all(c.get("ok") for c in channel_results) if channel_results else False,
        "org": org,
        "channels": channel_results,
    }

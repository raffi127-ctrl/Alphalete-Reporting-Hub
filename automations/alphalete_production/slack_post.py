"""Post the captured PNGs into their OWN dated thread in #alphalete-sales, as Lucy.

Layout mirrors the Tableau-trackers post + the Metrics thread: a bold dated parent
'\U0001F43A Alphalete Production MM/DD/YYYY' + one ':emoji: Section' line per section,
then every PNG as a threaded reply captioned '*Title MM/DD/YYYY*' (uniform date on all,
Megan 7/5), with each section's emoji reacted onto the parent.

Replaces Jolie Calinagan's two manual morning screenshot posts. Creates its OWN parent
each morning (find-or-create), no human dependency. Uses the shared Lucy user token
(slack_metrics_post._client) + files_upload_v2. Posts to #alphalete-sales AND, per
Raf 8/23, its own copy of the thread to #alphalete-lvl1-chat (smp.MIRROR_CHANNELS).
"""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

from automations.shared import slack_metrics_post as smp

_ALPHALETE_SALES = "C068PH3RFSM"
CHANNEL = os.environ.get("ALPHALETE_PRODUCTION_CHANNEL_ID", _ALPHALETE_SALES)

TITLE_PREFIX = "\U0001F43A Alphalete Production"     # wolf


def _date(today: dt.date) -> str:
    return today.strftime("%m/%d/%Y")


def header_title(today: dt.date) -> str:
    return f"{TITLE_PREFIX} {_date(today)}"


def header_text(sections: list, today: dt.date, captures: list | None = None) -> str:
    """Bold dated title + one ':emoji: Section' line per section (parent message).

    The Zero Streak line lists its depths like the B2B twin —
    ':no_entry_sign: Zero Streak 7.24 (1 Day, 2 Days, 3 Days)' — built from the
    rendered levels; falls back to the plain title if none were produced."""
    zmeta = sorted([m for m, _ in (captures or []) if m.get("kind") == "zeros"],
                   key=lambda m: m.get("level", 0))
    lines = [f"*{header_title(today)}*", ""]
    for s in sections:
        if s.get("kind") == "zeros" and zmeta:
            base = zmeta[0]["title"].split(" — ")[0]          # "Zero Streak 7.24"
            levels = ", ".join(m["title"].split(" — ")[1] for m in zmeta)
            lines.append(f":{s['react']}: {base} ({levels})")
        else:
            lines.append(f":{s['react']}: {s['title']}")
    return "\n".join(lines)


def reply_caption(meta: dict, today: dt.date) -> str:
    """'*Ceaseless Team Sales 07/05/2026*' -- bold, title (+team) + uniform date.
    Zero Streak captions follow the B2B twin instead: no redundant date (the
    depth already carries the anchor m.d), with the rep count appended."""
    if meta.get("no_date"):
        cap = f"*{meta['title']}*"
        reps = meta.get("reps")
        if reps is not None:
            cap += f"  —  {reps} rep{'' if reps == 1 else 's'}"
        return cap
    return f"*{meta['title']} {_date(today)}*"


def _reactions(sections: list) -> list:
    seen, out = set(), []
    for s in sections:                 # one reaction per distinct section emoji
        if s["react"] not in seen:
            seen.add(s["react"])
            out.append(s["react"])
    return out


def find_thread_ts(client, channel: str, today: dt.date):
    """Today's 🐺 parent thread ts. PAGINATE today's history — a busy channel blows
    past one 200-msg page, so a mid-day rerun otherwise can't see the 4am parent and
    spawns a duplicate thread (happened 7/14). Return the OLDEST match = the canonical
    morning thread, so reruns always APPEND to it."""
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    # match the EMOJI-FREE title: Slack stores the 🐺 as the shortcode ':wolf:' in the
    # message text, so matching on the unicode 🐺 never hit -> every rerun duplicated.
    title = header_title(today).split(" ", 1)[1]        # "Alphalete Production MM/DD/YYYY"
    found, cursor = None, None
    for _ in range(20):                     # cap pages (~4000 msgs) so we never loop forever
        resp = client.conversations_history(
            channel=channel, oldest=str(oldest), limit=200,
            **({"cursor": cursor} if cursor else {}))
        for msg in resp.get("messages", []):        # newest-first within a page
            if title in (msg.get("text", "") or ""):
                found = msg.get("thread_ts") or msg.get("ts")   # overwrite -> ends at oldest match
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return found


def _post_thread(client, channel: str, captures: list, sections: list,
                 today: dt.date, *, banner: str = "") -> dict:
    ts = None if banner else find_thread_ts(client, channel, today)
    created = ts is None
    if ts is None:
        ts = client.chat_postMessage(
            channel=channel, text=banner + header_text(sections, today, captures))["ts"]
    if not banner:                     # real post: react the section emojis onto parent
        for name in _reactions(sections):
            try:
                client.reactions_add(channel=channel, timestamp=ts, name=name)
            except Exception:
                pass
    posted = []
    for meta, png in captures:
        up = client.files_upload_v2(
            channel=channel, thread_ts=ts, file=str(png), filename=Path(png).name,
            initial_comment=reply_caption(meta, today))
        posted.append({"id": meta.get("id"), "title": meta["title"], "ok": up.get("ok")})
        time.sleep(3)                  # keep images in order (large files post late)
    return {"channel": channel, "thread_ts": ts, "created": created, "posted": posted,
            "ok": all(p.get("ok") for p in posted) if posted else False}


def post_all(captures: list, sections: list, today: dt.date | None = None,
             *, dry_run: bool = False) -> dict:
    # Raf 8/23: the whole thread ALSO posts to #alphalete-lvl1-chat — its own
    # copy per channel (Slack can't share a thread), config in smp.MIRROR_CHANNELS.
    channels = [CHANNEL] + smp.mirror_channels(CHANNEL)
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "channel": CHANNEL, "mirrors_to": channels[1:],
                "header": header_text(sections, today, captures),
                "replies": [{"file": Path(p).name, "caption": reply_caption(m, today)}
                            for m, p in captures]}
    client = smp._client()
    results = [_post_thread(client, ch, captures, sections, today)
               for ch in channels]
    out = dict(results[0])
    out["ok"] = all(r.get("ok") for r in results)
    if len(results) > 1:
        out["mirrors"] = results[1:]
    return out


def preview_dm(captures: list, sections: list, users: list,
               today: dt.date | None = None, *, dry_run: bool = False) -> dict:
    """DM the full thread to `users` for review; posts NOTHING to the channel."""
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "to_users": users,
                "header": header_text(sections, today, captures),
                "replies": [{"file": Path(p).name, "caption": reply_caption(m, today)}
                            for m, p in captures]}
    banner = ("*(PREVIEW — this is what will post to #alphalete-sales; nothing "
              "has posted to the channel yet.)*\n\n")
    client = smp._client()
    uids = [smp._resolve_user_id(client, u) for u in users]
    try:
        ch = client.conversations_open(users=",".join(uids))["channel"]["id"]
        res = _post_thread(client, ch, captures, sections, today, banner=banner)
        return {"ok": res["ok"], "mode": "group_dm", **res}
    except Exception as e:
        print(f"  group DM unavailable ({type(e).__name__}) — DMing each.", flush=True)
        results = [_post_thread(client, client.conversations_open(users=u)["channel"]["id"],
                                captures, sections, today, banner=banner) for u in uids]
        return {"ok": all(r["ok"] for r in results), "mode": "individual", "results": results}

"""Post the captured PNGs into their OWN dated thread in #alphalete-sales, as Lucy.

Layout mirrors the Tableau-trackers post + the Metrics thread: a bold dated parent
'\U0001F43A Alphalete Production MM/DD/YYYY' + one ':emoji: Section' line per section,
then every PNG as a threaded reply captioned '*Title MM/DD/YYYY*' (uniform date on all,
Megan 7/5), with each section's emoji reacted onto the parent.

Replaces Jolie Calinagan's two manual morning screenshot posts. Creates its OWN parent
each morning (find-or-create), no human dependency. Uses the shared Lucy user token
(slack_metrics_post._client) + files_upload_v2. Single channel: #alphalete-sales.
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


def header_text(sections: list, today: dt.date) -> str:
    """Bold dated title + one ':emoji: Section' line per section (parent message)."""
    lines = [f"*{header_title(today)}*", ""]
    lines += [f":{s['react']}: {s['title']}" for s in sections]
    return "\n".join(lines)


def reply_caption(meta: dict, today: dt.date) -> str:
    """'*Ceaseless Team Sales 07/05/2026*' -- bold, title (+team) + uniform date."""
    return f"*{meta['title']} {_date(today)}*"


def _reactions(sections: list) -> list:
    seen, out = set(), []
    for s in sections:                 # one reaction per distinct section emoji
        if s["react"] not in seen:
            seen.add(s["react"])
            out.append(s["react"])
    return out


def find_thread_ts(client, channel: str, today: dt.date):
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    title = header_title(today)
    resp = client.conversations_history(channel=channel, oldest=str(oldest), limit=200)
    for msg in resp.get("messages", []):
        if title in (msg.get("text", "") or ""):
            return msg.get("thread_ts") or msg.get("ts")
    return None


def _post_thread(client, channel: str, captures: list, sections: list,
                 today: dt.date, *, banner: str = "") -> dict:
    ts = None if banner else find_thread_ts(client, channel, today)
    created = ts is None
    if ts is None:
        ts = client.chat_postMessage(
            channel=channel, text=banner + header_text(sections, today))["ts"]
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
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "channel": CHANNEL,
                "header": header_text(sections, today),
                "replies": [{"file": Path(p).name, "caption": reply_caption(m, today)}
                            for m, p in captures]}
    client = smp._client()
    return _post_thread(client, CHANNEL, captures, sections, today)


def preview_dm(captures: list, sections: list, users: list,
               today: dt.date | None = None, *, dry_run: bool = False) -> dict:
    """DM the full thread to `users` for review; posts NOTHING to the channel."""
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "to_users": users,
                "header": header_text(sections, today),
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

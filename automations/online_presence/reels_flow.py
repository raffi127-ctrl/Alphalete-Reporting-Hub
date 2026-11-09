"""The weekly reel: the week's posted photos -> one short video -> ✅ -> posted.

Rides the 10-minute Lucy 3 pass, for LIVE offices that post from their own
computer (post_via "eco"):

  THURSDAY from 10am office time, if 3+ photos went out since last Thursday:
    Lucy makes the reel (brand_audit.reels), writes a caption, and posts in
    the office's room: a short header to react on, the video + caption in its
    thread.
  then, every pass until it's settled:
    ✅ on the header  -> a social_post job (media "video") to the office's
                         computer; watch.collect puts 🚀 on it when it's out
    ❌ + a note        -> a fresh caption in the thread (the note applied)
    💀                 -> skipped this week

One reel a week per office, never two: the week is the key in reels.json.
Approvers are the office's own (the same list photos use).
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

REEL_DAY = 3          # Thursday (Mon=0)
REEL_HOUR = 10
MIN_PHOTOS = 3


def _load(path: Path) -> Dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, d: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=2))


def week_key(now: dt.datetime) -> str:
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def week_photos(P, now: dt.datetime) -> List[Path]:
    """Photos that actually went out in the last 7 days, oldest first."""
    from automations.brand_audit import social_inbox as S
    inbox = S._load_state(P.path("social_inbox.json"))
    since = now.timestamp() - 7 * 86400
    out = []
    for ts, st in inbox.items():
        if not isinstance(st, dict) or not st.get("published"):
            continue
        try:
            when = float(ts)
        except ValueError:
            continue
        p = Path(st.get("photo_path") or "")
        if when >= since and p.exists():
            out.append((when, p))
    return [p for _, p in sorted(out)]


def _caption(P, photo: Path, n: int, feedback: str = "", avoid=None) -> str:
    from automations.brand_audit import social_inbox as S
    ctx = (f"A short weekly recap reel of {n} moments from {P.business_name}'s week "
           "(team, wins, promotions, culture). Write ONE caption for the whole reel, "
           "not for this single photo.")
    return S.caption_for(photo.read_bytes(), ctx, P.business_name, avoid=avoid or [],
                         feedback=feedback, style_path=P.style_file)


def _cap_text(cap: str) -> str:
    return (":sparkles: *Caption* — react :white_check_mark: to post the reel, :x: + "
            f"a note for a different caption, :skull: to skip this week:\n\n{cap}")


def step(P, cl, *, live: bool, now: dt.datetime | None = None) -> List[Dict]:
    """One pass for one office. Returns actions."""
    from automations.brand_audit import social_inbox as S
    from automations.brand_audit.config import (SOCIAL_APPROVE_EMOJI, SOCIAL_KILL_EMOJI,
                                                SOCIAL_REJECT_EMOJI)
    if P.post_via != "eco" or not P.social:
        return []
    now = now or dt.datetime.now(ZoneInfo(P.timezone))
    state_file = P.path("reels.json")
    state = _load(state_file)
    wk = week_key(now)
    cur = state.get(wk)
    who = P.counted_approvers
    acts: List[Dict] = []

    # 1) make + propose (Thursday, once)
    if cur is None:
        if now.weekday() != REEL_DAY or now.hour < REEL_HOUR:
            return []
        photos = week_photos(P, now)
        if len(photos) < MIN_PHOTOS:
            if live:
                state[wk] = {"status": "skipped", "note": f"only {len(photos)} photos"}
                _save(state_file, state)
            return [{"action": "no_reel", "note": f"{len(photos)} photos this week"}]
        cap = _caption(P, photos[0], len(photos))
        out = P.path(f"reel_{wk}.mp4")
        act = {"action": "propose_reel" if live else "would_propose_reel",
               "note": f"{len(photos)} photos", "caption": cap}
        if not live:
            return [act]
        from automations.brand_audit import reels
        reels.make_reel(photos, out)
        head = (f":clapper: *This week's reel for {P.business_name}* — video and "
                "caption in the thread.")
        r = cl.chat_postMessage(channel=P.slack_channel, text=head)
        ts = r.get("ts")
        cl.files_upload_v2(channel=P.slack_channel, thread_ts=ts, file=str(out),
                           title=f"Reel {wk}", initial_comment=":movie_camera: The reel")
        c = cl.chat_postMessage(channel=P.slack_channel, thread_ts=ts,
                                text=_cap_text(cap))
        state[wk] = {"status": "proposed", "ts": ts, "caption_ts": c.get("ts"),
                     "video": str(out),
                     "caption": cap, "rejected": [], "photo": str(photos[0]),
                     "n": len(photos)}
        _save(state_file, state)
        return [act]

    if cur.get("status") == "blocked" and cur.get("blocked_day", "") < now.date().isoformat():
        cur["status"] = "proposed"            # Zoho was out yesterday: try again
    if cur.get("status") != "proposed":
        if live:
            _save(state_file, state)
        return []

    # 2) reactions -- ✅ / ❌ on the CURRENT caption message (each new caption
    # is a new message, so an old ❌ never re-fires); 💀 anywhere skips.
    # ✅ wins over ❌, as with photos.
    allrx = S._thread_reactions(cl, cur["ts"], P.slack_channel)
    rx = allrx.get(cur.get("caption_ts"))
    if any(S._reacted(v, SOCIAL_KILL_EMOJI, who) for v in allrx.values()):
        acts.append({"action": "reel_skipped"})
        if live:
            cur["status"] = "skipped"
            cl.chat_postMessage(channel=P.slack_channel, thread_ts=cur["ts"],
                                text=":ok_hand: Skipping this week's reel.")
    elif S._reacted(rx, SOCIAL_APPROVE_EMOJI, who):
        acts.append({"action": "reel_queue_to_office", "caption": cur["caption"]})
        if live:
            from automations.online_presence import relay
            cur["eco_job"] = relay.enqueue_post(P.key, cur["caption"], Path(cur["video"]),
                                                P.pages, live=True, thread_ts=cur["ts"],
                                                media="video")
            cur["status"] = "queued"
    elif S._reacted(rx, SOCIAL_REJECT_EMOJI, who):
        fb = S._human_reply_after(cl, cur["ts"], cur.get("caption_ts") or cur["ts"],
                                  P.slack_channel)
        note = (fb or {}).get("text", "")
        cur.setdefault("rejected", []).append(cur["caption"])
        new = _caption(P, Path(cur["photo"]), cur.get("n", 0), feedback=note,
                       avoid=cur["rejected"])
        acts.append({"action": "reel_new_caption", "caption": new})
        if live:
            cur["caption"] = new
            c = cl.chat_postMessage(channel=P.slack_channel, thread_ts=cur["ts"],
                                    text=":arrows_counterclockwise: " + _cap_text(new))
            cur["caption_ts"] = c.get("ts")
    else:
        acts.append({"action": "reel_awaiting_approval"})
    if live:
        _save(state_file, state)
    return acts

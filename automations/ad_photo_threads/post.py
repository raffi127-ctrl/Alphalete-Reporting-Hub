"""Post a day's screenshots into one Slack thread PER AD.

Raf 2026-09-21: "all the screenshots that came from ATT sales representative
Frisco automatically get posted in that thread" — so each ad gets its own
thread the first time it shows up, and every evening one reply is added to it:
the day, who interviewed from that ad (✅/❌, stars, account number) and their
Zoom screenshots. Reviewing an ad for the week = opening its thread.

State (which thread belongs to which ad, which days are already posted) lives
in output/ad_photo_threads/state.json, keyed by channel, so a re-run never
double-posts and a test channel never collides with the real one.

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from automations.ad_photo_threads import collect, config

REPO = Path(__file__).resolve().parents[2]
STATE_PATH = REPO / "output" / "ad_photo_threads" / "state.json"
MAX_FILES_PER_REPLY = 10          # Slack's cap on files in one message


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_PATH)


PILOT_TAG = ":test_tube: *[PILOT]* "


def parent_text(title: str, pilot: bool = False) -> str:
    return (f"{PILOT_TAG if pilot else ''}:clapper: *Ad Photos — {title}*\n"
            "1st-round screenshots from this ad, added every evening.")


def pilot_intro(day) -> str:
    return (f"{PILOT_TAG}*Ad Photo Threads — sample run*\n"
            f"This is a test using the {day:%A} {day.month}/{day.day} 1st rounds. "
            "Each thread below is one Indeed ad with its candidates and Zoom "
            "screenshots. Nothing has been posted to the channel yet. "
            "Reply here with any changes before we go live.")


def _label(c: collect.Candidate) -> str:
    return next((s["office_id"] for s in config.SOURCES if s["label"] == c.source), "")


def _stars(s: str) -> str:
    n = "".join(ch for ch in (s or "") if ch.isdigit())
    return f"{n}⭐" if n else ""


def reply_text(rep: collect.DayReport, cands: List[collect.Candidate]) -> str:
    """One line per candidate, then a note for the group-call shots."""
    # month/day by hand: `%-m` is Mac-only and dies on Windows.
    lines = [f"*{rep.day:%a} {rep.day.month}/{rep.day.day}* · {len(cands)} "
             f"candidate{'s' if len(cands) != 1 else ''}"]
    for c in cands:
        ok = c.qualify.lower().startswith("qualif")
        bits = [c.name, _stars(c.stars), _label(c), c.interviewer]
        lines.append(f"{'✅' if ok else '❌'} " + " · ".join(b for b in bits if b))
    no_shot = [c.name for c in cands if not c.images]
    if no_shot:
        lines.append(f"_No screenshot: {', '.join(no_shot)}_")
    if any(c.shared for c in cands):
        lines.append("_Some photos are the time slot's group call, so they can "
                     "show candidates from other ads too._")
    return "\n".join(lines)


def _unique_images(cands: List[collect.Candidate]) -> List[dict]:
    seen, out = set(), []
    for c in cands:
        for f in c.images:
            if f.get("id") not in seen:
                seen.add(f.get("id"))
                out.append(f)
    return out


def plan(rep: collect.DayReport) -> List[dict]:
    """What would be posted: one entry per recognised ad, biggest first.
    Candidates whose title can't be told are NOT posted (they're listed in the
    run summary instead) — posting them under a guessed ad is the exact
    mistake this report exists to avoid."""
    groups = rep.by_ad()
    keys = sorted((k for k in groups if k), key=lambda k: -len(groups[k]))
    return [{"key": k, "title": rep.book.display(k), "cands": groups[k],
             "text": reply_text(rep, groups[k]),
             "images": _unique_images(groups[k])} for k in keys]


def publish(rep: collect.DayReport, channel: str, *, cl=None,
            pilot: bool = False, max_ads: Optional[int] = None) -> Dict[str, int]:
    """Post the day. Returns counts. Idempotent per (channel, ad, day).
    pilot=True (test DM): one intro post first, and every thread tagged
    [PILOT] so nobody mistakes the sample for the live report."""
    from automations.sara_down.run import _download_image
    cl = cl or collect._client()
    state = _load_state()
    ch_state = state.setdefault(channel, {})
    day = rep.day.isoformat()
    counts = {"threads_new": 0, "replies": 0, "skipped_done": 0, "photos": 0}

    intro_key = f"_pilot_intro_{day}"
    if pilot and not ch_state.get(intro_key):
        cl.chat_postMessage(channel=channel, text=pilot_intro(rep.day))
        ch_state[intro_key] = True
        _save_state(state)

    items = plan(rep)
    if max_ads:
        # A sample (Eve 9/21: 30 threads in a DM is too much): the biggest ads
        # that actually have screenshots, so the sample shows the real thing.
        items = [i for i in items if i["images"]][:max_ads]

    for item in items:
        ad = ch_state.setdefault(item["key"], {"thread_ts": "", "days": []})
        if day in ad["days"]:
            counts["skipped_done"] += 1
            continue
        if not ad["thread_ts"]:
            r = cl.chat_postMessage(channel=channel,
                                    text=parent_text(item["title"], pilot))
            ad["thread_ts"] = r["ts"]
            counts["threads_new"] += 1
            _save_state(state)

        with tempfile.TemporaryDirectory() as tmp:
            uploads = []
            for i, f in enumerate(item["images"]):
                data, subtype = _download_image(f)
                p = Path(tmp) / f"{i:02d}.{subtype or 'png'}"
                p.write_bytes(data)
                uploads.append({"file": str(p), "filename": p.name})
            if not uploads:
                cl.chat_postMessage(channel=channel, thread_ts=ad["thread_ts"],
                                    text=item["text"])
            for n in range(0, len(uploads), MAX_FILES_PER_REPLY):
                chunk = uploads[n:n + MAX_FILES_PER_REPLY]
                kw = {"initial_comment": item["text"]} if n == 0 else {}
                cl.files_upload_v2(channel=channel, thread_ts=ad["thread_ts"],
                                   file_uploads=chunk, **kw)
            counts["photos"] += len(uploads)

        ad["days"].append(day)
        counts["replies"] += 1
        _save_state(state)
    return counts

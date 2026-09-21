"""Post a day's screenshots into one Slack thread PER AD.

Raf 2026-09-21: "all the screenshots that came from ATT sales representative
Frisco automatically get posted in that thread" — so each ad gets its own
thread the first time it shows up, and every evening one reply is added to it:
the day, who interviewed from that ad (✅/❌, stars, account number) and their
Zoom screenshots. Reviewing an ad for the week = opening its thread.

WEEKLY + PINNED (Raf 2026-09-21: "Yes, fresh PINned thread per ad"): an ad's
thread lives Monday–Sunday. The first day an ad shows up in a new week it gets
a fresh thread, which is pinned, and last week's thread for that ad is
unpinned — so the channel's pins are always "this week's ads", never a year of
them. A pin that Slack refuses never stops the photos from posting.

State (which thread belongs to which ad in which week, which days are already
posted) lives in output/ad_photo_threads/state.json, keyed by channel, so a
re-run never double-posts and a test channel never collides with the real one.

Python 3.9-safe (runs on the mini): no runtime `X | Y`, no 3.10+ syntax.
"""
from __future__ import annotations

import datetime as dt
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


def week_monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def parent_text(title: str, monday: dt.date, pilot: bool = False) -> str:
    return (f"{PILOT_TAG if pilot else ''}:clapper: *Ad Photos — {title}*\n"
            f"Week of {monday.month}/{monday.day} · 1st-round screenshots from "
            "this ad, added every evening.")


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


def _pin(cl, channel: str, ts: str, add: bool) -> Optional[str]:
    """Pin/unpin; returns the error text instead of raising — a missing
    pins:write must cost the pin, not the day's photos."""
    try:
        (cl.pins_add if add else cl.pins_remove)(channel=channel, timestamp=ts)
        return None
    except Exception as e:                       # noqa: BLE001
        msg = str(e)
        if "already_pinned" in msg or "no_pin" in msg:
            return None
        return msg.splitlines()[0][:160]


def day_done(channel: str, day: dt.date) -> bool:
    return day.isoformat() in _load_state().get(channel, {}).get("done_days", [])


def mark_day_done(channel: str, day: dt.date) -> None:
    state = _load_state()
    done = state.setdefault(channel, {}).setdefault("done_days", [])
    if day.isoformat() not in done:
        done.append(day.isoformat())
        done[:] = sorted(done)[-60:]
    _save_state(state)


def publish(rep: collect.DayReport, channel: str, *, cl=None,
            pilot: bool = False, max_ads: Optional[int] = None) -> Dict[str, int]:
    """Post the day. Returns counts. Idempotent per (channel, ad, day).
    pilot=True (test DM): one intro post first, and every thread tagged
    [PILOT] so nobody mistakes the sample for the live report."""
    from automations.sara_down.run import _download_image
    cl = cl or collect._client()
    state = _load_state()
    ch_state = state.setdefault(channel, {})
    weeks = ch_state.setdefault("weeks", {})
    monday = week_monday(rep.day)
    wk = weeks.setdefault(monday.isoformat(), {})
    day = rep.day.isoformat()
    counts = {"threads_new": 0, "replies": 0, "skipped_done": 0, "photos": 0,
              "pin_errors": 0, "to_pin": [], "to_unpin": []}

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
        ad = wk.setdefault(item["key"], {"thread_ts": "", "days": [], "pinned": False})
        if day in ad["days"]:
            counts["skipped_done"] += 1
            continue
        if not ad["thread_ts"]:
            r = cl.chat_postMessage(channel=channel,
                                    text=parent_text(item["title"], monday, pilot))
            ad["thread_ts"] = r["ts"]
            ad["title"] = item["title"]
            counts["threads_new"] += 1
            err = _pin(cl, channel, ad["thread_ts"], True)
            ad["pinned"] = err is None
            if err:
                counts["pin_errors"] += 1
                print(f"  pin failed for {item['title']!r}: {err}")
            # Retire last week's pin for this ad — the newest earlier week only.
            for old_wk in sorted((w for w in weeks if w < monday.isoformat()), reverse=True):
                old = weeks[old_wk].get(item["key"])
                if old:
                    if old.get("pinned") and not _pin(cl, channel, old["thread_ts"], False):
                        old["pinned"] = False
                    break
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

    # Threads a PERSON pinned (Lucy's token has no pins:write — Eve pins by
    # hand, 2026-09-21): once this week's threads exist, last week's are hers
    # to unpin. Listed once each, including ads that stopped running. Read
    # from state, not from this run, so a run that died after opening a
    # thread still gets it into the next run's reminder.
    if not pilot:
        for key, ad in wk.items():
            if ad.get("thread_ts") and not ad.get("pinned") \
                    and not ad.get("pin_reminded"):
                counts["to_pin"].append((ad.get("title") or key, ad["thread_ts"]))
                ad["pin_reminded"] = True
    if counts["to_pin"]:
        prev = sorted(w for w in weeks if w < monday.isoformat())
        if prev:
            for key, old in weeks[prev[-1]].items():
                if (old.get("thread_ts") and not old.get("pinned")
                        and not old.get("unpin_reminded")):
                    counts["to_unpin"].append((old.get("title") or key, old["thread_ts"]))
                    old["unpin_reminded"] = True
        _save_state(state)
    return counts


def permalink(channel: str, ts: str) -> str:
    """Built, not fetched: chat.getPermalink is one more call that can fail."""
    return f"https://ao-pbns.slack.com/archives/{channel}/p{ts.replace('.', '')}"


def pin_reminder_text(channel: str, day: dt.date, to_pin, to_unpin) -> str:
    lines = [f":pushpin: *Ad Photo Threads — pin reminder ({day:%a} {day.month}/{day.day})*"]
    if to_pin:
        lines.append("\n*Pin these new threads:*")
        lines += [f"• <{permalink(channel, ts)}|{title}>" for title, ts in to_pin]
    if to_unpin:
        lines.append("\n*Unpin last week's:*")
        lines += [f"• <{permalink(channel, ts)}|{title}>" for title, ts in to_unpin]
    return "\n".join(lines)


def send_pin_reminder(channel: str, day: dt.date, counts: dict, *, cl=None) -> bool:
    """DM the pinner the links. False if there was nothing to say."""
    if not (counts.get("to_pin") or counts.get("to_unpin")):
        return False
    cl = cl or collect._client()
    dm = cl.conversations_open(users=config.PIN_REMINDER_USER)["channel"]["id"]
    cl.chat_postMessage(channel=dm, text=pin_reminder_text(
        channel, day, counts.get("to_pin"), counts.get("to_unpin")),
        unfurl_links=False)
    return True

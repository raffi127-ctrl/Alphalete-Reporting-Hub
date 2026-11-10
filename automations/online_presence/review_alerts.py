"""A bad Google review: tell the office within minutes, not at noon.

Megan 2026-11-08: "bad review alerts should be notified asap". Rides the
10-minute Lucy 3 tick (online_presence.run), so a new 1-3★ review is in
front of the office about ten minutes after Google has it:

    the office's room   -- short header, the review in the thread
    the owner           -- a DM (an office row's owner_slack_id)
    the alerts channel  -- a copy, so Megan sees every office's bad reviews

Lucy's reply draft follows separately (review_replies, same pass), so the
alert never waits on Claude. Indeed / Glassdoor / Reddit are NOT here:
Lucy can't read Indeed or Glassdoor (robot checks), and Reddit needs an
emailed keyword alert set up first. Indeed is notify-only, never replied to.

FIRST LOOK SEEDS, NEVER BLASTS. The first time an office is checked, every
review already on Google is recorded as seen and nothing is sent -- an office
going live must not get a DM for every 2★ review from 2023.

ONE ALERT PER REVIEW, EVER, keyed by Google's review id. A review edited from
5★ to 2★ is a new bad review and alerts once.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

BAD_BELOW = 4            # 1, 2, 3 stars
LOOK_AT = 25             # newest reviews read per office per pass


def _load(path: Path) -> Dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, d: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=2))


def _key(rv: Dict) -> str:
    return f"{rv.get('review_id') or rv.get('name')}|{rv.get('rating')}"


def messages(P, rv: Dict) -> tuple:
    """(header, thread detail). Header SHORT; the review lives in the thread."""
    stars = rv.get("rating") or "?"
    head = (f":rotating_light: *New {stars}★ Google review — {P.business_name}*")
    text = (rv.get("text") or "").strip() or "(rating only, no text)"
    when = (rv.get("publish_time") or "")[:10]
    detail = (f"*{rv.get('author') or 'A reviewer'}* · {when}\n> {text}\n\n"
              "Lucy's reply draft follows in this channel for ✅ / ❌.")
    return head, detail


def check(P, cl, *, live: bool, reviews: List[Dict] | None = None) -> List[Dict]:
    """New bad reviews for one office (or Alphalete). Returns actions."""
    from automations.brand_audit import gbp_api
    from automations.online_presence.rooms import SOCIAL_ALERTS as _SOCIAL_ALERTS
    if not P.gbp_location:
        return []
    if reviews is None:
        try:
            reviews = gbp_api.list_reviews(P.gbp_location, limit=LOOK_AT)
        except Exception as e:
            return [{"action": "review_read_failed", "error": str(e)[:120]}]
    state_file = P.path("review_alerts.json")
    st = _load(state_file)
    seen = set(st.get("seen") or [])
    keys = [_key(r) for r in reviews]
    if not st.get("seeded"):
        if live:
            _save(state_file, {"seeded": True, "seen": sorted(set(keys))})
        return [{"action": "seeded", "note": f"{len(keys)} existing reviews marked seen"}]
    acts = []
    for rv, k in zip(reviews, keys):
        if k in seen:
            continue
        seen.add(k)
        stars = rv.get("rating")
        if not (isinstance(stars, (int, float)) and stars < BAD_BELOW):
            continue
        if rv.get("has_reply"):
            continue                      # someone already answered it
        head, detail = messages(P, rv)
        acts.append({"action": "bad_review_alert" if live else "would_alert",
                     "note": f"{stars}★ {rv.get('author')}"})
        if not live:
            continue
        rooms = [P.reviews_channel]
        if P.key != "alphalete" and _SOCIAL_ALERTS not in rooms:
            rooms.append(_SOCIAL_ALERTS)
        for ch in rooms:
            r = cl.chat_postMessage(channel=ch, text=head)
            cl.chat_postMessage(channel=ch, thread_ts=r.get("ts"), text=detail)
        if P.owner_slack_id:
            cl.chat_postMessage(channel=P.owner_slack_id, text=f"{head}\n{detail}")
    if live:
        _save(state_file, {"seeded": True, "seen": sorted(seen)[-2000:]})
    return acts

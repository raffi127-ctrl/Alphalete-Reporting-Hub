"""Facebook review replies (Alphalete's page), the same way Google's work
(Megan 2026-11-14: "build everything you can" -- BIS covers Facebook reviews).

    python -m automations.brand_audit.fb_reviews              # practice: shows what it WOULD do
    python -m automations.brand_audit.fb_reviews --live       # posts (approved ones + 4-5★ thank-yous)

  * recommends (positive)   -> a thank-you posts on its own, at most 10 a day
  * doesn't recommend       -> a drafted reply card in the reviews Slack channel;
                               ✅ posts it, ❌ writes a new one (same as Google)
  * a review the page already answered is skipped, never double-replied

Reads with the page's own key (from keys.json's system-user token +
facebook_page_id). Offices: needs each office's Facebook page shared with
Alphalete's Meta business first -- not wired yet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List

GRAPH = "https://graph.facebook.com/v23.0"
DAILY_CAP = 10            # thank-yous posted per day
DRAFT_CAP = 3             # cards waiting on ✅ per day, so an old backlog doesn't flood the channel
STATE = Path.home() / ".config" / "brand-audit" / "fb_review_replies.json"


def _keys() -> Dict:
    return json.loads((Path.home() / ".config" / "brand-audit" / "keys.json").read_text())


def _page_token(k: Dict) -> str:
    import requests
    r = requests.get(f"{GRAPH}/{k['facebook_page_id']}", timeout=20,
                     params={"access_token": k["facebook_page_token"], "fields": "access_token"}).json()
    if not r.get("access_token"):
        raise RuntimeError(f"no Facebook page key: {r.get('error', {}).get('message', r)}")
    return r["access_token"]


def get_reviews(page_id: str, token: str) -> List[Dict]:
    import requests
    out, url = [], f"{GRAPH}/{page_id}/ratings"
    params = {"access_token": token, "limit": 50,
              "fields": "created_time,recommendation_type,review_text,open_graph_story{id}"}
    while url and len(out) < 500:
        r = requests.get(url, params=params, timeout=30).json()
        if "error" in r:
            raise RuntimeError(r["error"].get("message"))
        out += r.get("data") or []
        url, params = (r.get("paging") or {}).get("next"), None
    return [x for x in out if (x.get("open_graph_story") or {}).get("id")]


def already_answered(story_id: str, page_id: str, token: str) -> bool:
    import requests
    r = requests.get(f"{GRAPH}/{story_id}/comments", timeout=20,
                     params={"access_token": token, "fields": "from{id}", "limit": 50}).json()
    return any((c.get("from") or {}).get("id") == page_id for c in r.get("data") or [])


def post_reply(story_id: str, text: str, token: str) -> None:
    import requests
    r = requests.post(f"{GRAPH}/{story_id}/comments", timeout=30,
                      data={"access_token": token, "message": text}).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("message"))


def as_review(fb: Dict) -> Dict:
    """Facebook's shape -> the review_replies drafter's shape."""
    positive = fb.get("recommendation_type") == "positive"
    words = (fb.get("review_text") or "").strip()
    # Facebook has no stars: say "recommends", so a reply never thanks them
    # for a "five-star rating" they didn't give.
    if not words:
        words = ("(They recommend us on Facebook, with no written review.)" if positive
                 else "(They don't recommend us on Facebook, with no written review.)")
    return {"rating": 5 if positive else 1, "author": "a Facebook reviewer",
            "text": words + " [This is a Facebook recommendation, not a star rating: never mention stars.]",
            "source": "Facebook"}


def process(*, live: bool = False) -> List[Dict]:
    from automations.brand_audit import review_replies as RR
    from automations.brand_audit.config import SOCIAL_APPROVE_EMOJI, SOCIAL_REJECT_EMOJI
    k = _keys()
    page_id = k["facebook_page_id"]
    token = _page_token(k)
    P = RR._profile(None)                          # Alphalete
    state = json.loads(STATE.read_text()) if STATE.exists() else {"reviews": {}, "posted_counts": {}}
    today = dt.date.today().isoformat()
    posted_today = state["posted_counts"].get(today, 0)
    drafted_today = state.setdefault("draft_counts", {}).get(today, 0)
    cl = RR._client() if live else None
    actions = []
    for fb in get_reviews(page_id, token):
        sid = fb["open_graph_story"]["id"]
        if sid in state["reviews"]:
            continue
        if already_answered(sid, page_id, token):
            state["reviews"][sid] = {"answered_before": True}
            continue
        rv = as_review(fb)
        positive = rv["rating"] == 5
        if positive and posted_today >= DAILY_CAP:
            continue                               # tomorrow's run picks it up
        if not positive and drafted_today >= DRAFT_CAP:
            continue
        reply = RR.draft_reply(rv, "Alphalete Marketing", contact=P.contact_email)
        if positive:
            actions.append({"action": "auto_post", "story": sid, "reply": reply})
            if live:
                post_reply(sid, reply, token)
                posted_today += 1
                state["reviews"][sid] = {"posted": True, "reply": reply}
            continue
        if drafted_today >= DRAFT_CAP:
            continue
        drafted_today += 1
        actions.append({"action": "draft", "story": sid, "reply": reply})
        if live:
            card = (f":speech_balloon: *Facebook review* (doesn't recommend)\n> {rv['text'][:900]}\n\n"
                    f"*Lucy's reply:*\n{reply}\n\n:white_check_mark: approve & post  ·  :x: write me a new one")
            r = cl.chat_postMessage(channel=P.reviews_channel, text=card)
            state["reviews"][sid] = {"reply": reply, "card_ts": r.get("ts"), "review": rv}
    # approvals on open cards
    if live:
        for sid, st in state["reviews"].items():
            if st.get("posted") or not st.get("card_ts"):
                continue
            rx = RR._thread_reactions(cl, st["card_ts"], P.reviews_channel).get(st["card_ts"])
            if RR._reacted(rx, SOCIAL_REJECT_EMOJI, P.counted_approvers):
                new = RR.draft_reply(st["review"], "Alphalete Marketing", contact=P.contact_email,
                                     avoid=[st["reply"]])
                r = cl.chat_postMessage(channel=P.reviews_channel,
                                        text=f":speech_balloon: *Facebook review, new draft*\n{new}\n\n"
                                             ":white_check_mark: approve & post  ·  :x: write me a new one")
                st.update({"reply": new, "card_ts": r.get("ts")})
                actions.append({"action": "redraft", "story": sid})
            elif RR._reacted(rx, SOCIAL_APPROVE_EMOJI, P.counted_approvers):
                post_reply(sid, st["reply"], token)
                st["posted"] = True
                actions.append({"action": "approved", "story": sid})
        state["posted_counts"][today] = posted_today
        state["draft_counts"][today] = drafted_today
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))
    return actions


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="brand_audit.fb_reviews")
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args(argv)
    acts = process(live=a.live)
    for x in acts:
        print(f"{x['action']}: {x.get('story')}" + (f"\n    {x['reply'][:160]}" if x.get("reply") else ""))
    print(f"=== {'live' if a.live else 'practice (nothing posted)'}: {len(acts)} action(s) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

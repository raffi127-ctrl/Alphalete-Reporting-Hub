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
import re
import sys
from pathlib import Path
from typing import Dict, List

GRAPH = "https://graph.facebook.com/v23.0"
DAILY_CAP = 10            # thank-yous posted per day
DRAFT_CAP = 3             # cards waiting on ✅ per day, so an old backlog doesn't flood the channel
STATE = Path.home() / ".config" / "brand-audit" / "fb_review_replies.json"


def _keys() -> Dict:
    return json.loads((Path.home() / ".config" / "brand-audit" / "keys.json").read_text())


BUSINESS_ID = "1600512619997772"           # Alphalete Marketing's Meta business


def _page_token(k: Dict, page_id: str = "") -> str:
    import requests
    r = requests.get(f"{GRAPH}/{page_id or k['facebook_page_id']}", timeout=20,
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


def shared_pages() -> List[Dict]:
    """Pages offices have shared with Alphalete's Meta business (launch call)."""
    import requests
    k = _keys()
    r = requests.get(f"{GRAPH}/{BUSINESS_ID}/client_pages", timeout=20,
                     params={"access_token": k["facebook_page_token"], "fields": "id,name,link", "limit": 200}).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("message"))
    return r.get("data") or []


def connect(page_id: str) -> Dict:
    """Give Lucy's Meta helper reply access to a page the office shared, then
    prove it by reading the page's reviews."""
    import requests
    k = _keys()
    me = requests.get(f"{GRAPH}/me", params={"access_token": k["facebook_page_token"]}, timeout=20).json()
    r = requests.post(f"{GRAPH}/{page_id}/assigned_users", timeout=30,
                      data={"access_token": k["facebook_page_token"], "user": me.get("id"),
                            "business": BUSINESS_ID, "tasks": json.dumps(["MODERATE", "CREATE_CONTENT", "MANAGE"])}).json()
    if "error" in r and "already" not in r["error"].get("message", "").lower():
        return {"ok": False, "why": r["error"].get("message")}
    try:
        n = len(get_reviews(page_id, _page_token(k, page_id)))
    except Exception as e:
        return {"ok": False, "why": str(e)[:200]}
    return {"ok": True, "reviews": n}


def process(*, live: bool = False, profile=None) -> List[Dict]:
    """profile = an ECO office (offices.Presence) with facebook_page_id; None = Alphalete."""
    from automations.brand_audit import review_replies as RR
    from automations.brand_audit.config import SOCIAL_APPROVE_EMOJI, SOCIAL_REJECT_EMOJI
    k = _keys()
    P = RR._profile(profile)
    page_id = getattr(profile, "facebook_page_id", "") if profile else k["facebook_page_id"]
    if not page_id:
        return [{"action": "no_facebook_page"}]
    token = _page_token(k, page_id)
    name = profile.business_name if profile else "Alphalete Marketing"
    state_file = profile.path("fb_review_replies.json") if profile else STATE
    cap = (getattr(P, "auto_reply_daily_cap", 0) or DAILY_CAP) if profile else DAILY_CAP
    dcap = (getattr(P, "review_draft_daily_cap", 0) or DRAFT_CAP) if profile else DRAFT_CAP
    state = json.loads(state_file.read_text()) if state_file.exists() else {"reviews": {}, "posted_counts": {}}
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
        if positive and posted_today >= cap:
            continue                               # tomorrow's run picks it up
        if not positive and drafted_today >= dcap:
            continue
        reply = RR.draft_reply(rv, name, contact=P.contact_email)
        if positive:
            actions.append({"action": "auto_post", "story": sid, "reply": reply})
            if live:
                post_reply(sid, reply, token)
                posted_today += 1
                state["reviews"][sid] = {"posted": True, "reply": reply}
            continue
        if drafted_today >= dcap:
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
                new = RR.draft_reply(st["review"], name, contact=P.contact_email,
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
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=1))
    return actions


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="brand_audit.fb_reviews")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--connect", default="", metavar="OFFICE",
                    help="after the owner shares their page: find it, connect it, save it to the office")
    a = ap.parse_args(argv)
    if a.connect:
        from dataclasses import replace
        from automations.online_presence import offices
        p = offices.get(a.connect)
        if not p:
            print(f"✗ no office {a.connect!r}")
            return 1
        want = re.sub(r"[^a-z0-9]", "", p.business_name.lower())
        pages = shared_pages()
        match = [x for x in pages if re.sub(r"[^a-z0-9]", "", (x.get("name") or "").lower()) == want]
        if len(match) != 1:
            print(f"✗ {len(match)} shared page(s) named like {p.business_name!r}. Shared with us now: "
                  + (", ".join(x.get("name", x["id"]) for x in pages) or "none")
                  + ". Use Launch Studio step 9 to pick by hand.")
            return 1
        res = connect(match[0]["id"])
        if not res["ok"]:
            print(f"✗ not connected: {res['why']}")
            return 1
        offices.save(replace(p, facebook_page_id=match[0]["id"]))
        print(f"✓ {match[0].get('name')} connected ({res['reviews']} reviews readable); saved to {p.key}")
        return 0
    acts = process(live=a.live)
    for x in acts:
        print(f"{x['action']}: {x.get('story')}" + (f"\n    {x['reply'][:160]}" if x.get("reply") else ""))
    print(f"=== {'live' if a.live else 'practice (nothing posted)'}: {len(acts)} action(s) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

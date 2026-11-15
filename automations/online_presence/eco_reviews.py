"""Google reviews through the office's OWN computer (Megan 2026-11-15: "the
goal [is] for everything to move over to the relay machine so we can offer
EVERYTHING to each ICD").

For an office whose row says  "reviews_via": "eco":

    Lucy 3                                  the office's computer
    ------                                  ---------------------
    google_signin job (set-up call)  --->   owner signs in to THEIR Google once
    google_reviews job (every 30 min) --->  reads unanswered reviews, answers them
    drafts (Claude) + ✅/❌ cards (Slack)    (never: Alphalete's keys stay here)
    google_reply job (approved reply) --->  posts it from the owner's sign-in

Nothing about drafting or approvals changes: review_replies.process_reviews
runs exactly as before, it just READS from the office's last answer and
POSTS by queueing a job (fetch= / post= / can_post=).

The jobs ride the relay's existing kinds (social_check = read, social_post =
publish) with payload["do"], and the office echoes "do" in its answer, so
these never get mistaken for a Zoho check (watch.collect sees only the rest).
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

DOS = ("google_signin", "google_reviews", "google_reply")
READ_EVERY_MIN = 30
READ_GIVE_UP_HOURS = 3          # an offline computer never answered: ask again
SIGNIN_MINUTES = 14             # inside the office run's 20-minute hard stop
OAUTH_CLIENT = Path.home() / ".config" / "recruiting-report" / "oauth-client.json"


def _file(P) -> Path:
    return P.path("eco_reviews.json")


def _load(P) -> Dict:
    try:
        return json.loads(_file(P).read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(P, s: Dict) -> None:
    f = _file(P)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(s, indent=1))


def is_eco(P) -> bool:
    return getattr(P, "reviews_via", "lucy") == "eco"


def signed_in(P) -> bool:
    s = _load(P)
    return bool(s.get("signed_in") and s.get("location"))


# ---- set-up: the owner signs in ------------------------------------------------
def _client_details() -> Tuple[str, str]:
    """Our Google app's id. An "installed" (Desktop) app's secret is not a
    secret by Google's own rules -- it ships inside every desktop app -- so it
    may ride the job. The owner's sign-in never leaves their computer."""
    d = json.loads(OAUTH_CLIENT.read_text())
    d = d.get("installed") or d.get("web") or d
    return d["client_id"], d["client_secret"]


def queue_signin(P) -> str:
    from automations.online_presence import relay
    cid, secret = _client_details()
    job = relay.enqueue(P.key, "social_check", {"do": "google_signin", "client_id": cid,
                                                "client_secret": secret, "minutes": SIGNIN_MINUTES},
                        live=True)
    s = _load(P)
    s["signin_job"] = job
    _save(P, s)
    return job


def pick_listing(P, listings: List[Dict]) -> str:
    """The owner's listing that IS this office: same location id as the
    listing linked on sign-up, else the only one they manage."""
    want = (P.gbp_location or "").rstrip("/").split("/")[-1]
    if want:
        for x in listings:
            if x.get("path", "").rstrip("/").split("/")[-1] == want:
                return x["path"]
    return listings[0]["path"] if len(listings) == 1 else ""


# ---- answers from the office's computer -----------------------------------------
def split(rows: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """(ours, the rest). The rest go to watch.collect unchanged."""
    ours = [r for r in rows if (r.get("result") or {}).get("do") in DOS]
    return ours, [r for r in rows if r not in ours]


def _owner_dm(P, cl, s: Dict, why: str, dry: bool) -> Dict:
    today = dt.date.today().isoformat()
    if s.get("dm_day") == today or not P.owner_slack_id:
        return {"action": "dm_already_sent_today" if s.get("dm_day") == today else "no_owner_to_dm",
                "note": why}
    text = (f":warning: Lucy can't reach your Google reviews right now ({why}). "
            "Message Megan or Eve and we'll get you signed back in -- it takes a minute.")
    if not dry:
        cl.chat_postMessage(channel=P.owner_slack_id, text=text)
        s["dm_day"] = today
    return {"action": "dm_owner", "note": text}


def collect(P, rows: List[Dict], cl, *, dry: bool) -> List[Dict]:
    """Act on this office's answered review jobs (already split out)."""
    from automations.brand_audit import review_replies as RR
    s = _load(P)
    rr_file = P.path("review_replies.json")
    rr = RR._load(rr_file)
    by_name = {(e.get("review") or {}).get("name"): e for e in (rr.get("reviews") or {}).values()
               if isinstance(e, dict)}
    acts: List[Dict] = []
    for r in rows:
        res = r.get("result") or {}
        do, status = res.get("do"), res.get("status")
        if do == "google_signin":
            if status == "signed_in":
                loc = pick_listing(P, res.get("listings") or [])
                s.update(signed_in=bool(loc), location=loc, listings=res.get("listings") or [])
                acts.append({"action": "google_signed_in" if loc else "google_listing_not_found",
                             "note": loc or ", ".join(x.get("title", "") for x in res.get("listings") or [])
                             or "they manage no Google listing on that account"})
            else:
                acts.append({"action": f"google_signin_{status}", "note": res.get("error", "")})
        elif do == "google_reviews":
            s.pop("pending_read", None)
            if status == "ok":
                s.update(reviews=res.get("reviews") or [], read_at=time.time(), signed_in=True)
                acts.append({"action": "reviews_read", "note": f"{len(s['reviews'])} unanswered"})
            else:
                if status == "signed_out":
                    s["signed_in"] = False
                acts.append({"action": f"reviews_read_{status}", "note": res.get("error", "")})
                acts.append(_owner_dm(P, cl, s, "your Google sign-in ran out" if status == "signed_out"
                                      else "Google said no", dry))
        elif do == "google_reply":
            e = by_name.get(res.get("name"))
            if status == "replied":
                acts.append({"action": "reply_posted", "note": res.get("name", "")})
                if e is not None:
                    e["confirmed"] = True
                continue
            # didn't go out: undo "posted" so process_reviews tries again (an
            # auto reply on its retry pass; an approved card on its ✅)
            acts.append({"action": f"reply_{status}", "note": res.get("error", "")})
            if e is not None:
                e["posted"] = False
                e["post_error"] = res.get("error") or status
            if status == "signed_out":
                s["signed_in"] = False
                acts.append(_owner_dm(P, cl, s, "your Google sign-in ran out", dry))
    if not dry:
        _save(P, s)
        RR._save(rr, rr_file)
    return acts


# ---- what process_reviews reads + how it posts --------------------------------------
def reviews(P) -> List[Dict]:
    """The office's last answer, in review_replies' shape."""
    out = []
    for x in _load(P).get("reviews") or []:
        out.append({"name": x.get("name"), "rating": x.get("rating"), "text": x.get("text", ""),
                    "author": x.get("author", ""), "publish_time": x.get("time", ""),
                    "when": (x.get("time") or "")[:10], "has_reply": False})
    return out


def poster(P):
    """process_reviews' post step: queue the reply to the office's computer."""
    def _post(rv: Dict, reply: str, company=None) -> Dict:
        from automations.online_presence import relay
        if not rv.get("name"):
            raise NotImplementedError("no review to reply to")
        job = relay.enqueue(P.key, "social_post", {"do": "google_reply", "name": rv["name"],
                                                   "comment": reply}, live=True)
        return {"queued": job}
    return _post


def ensure_read(P, *, live: bool) -> Dict | None:
    """Queue a read every READ_EVERY_MIN, one at a time."""
    s = _load(P)
    if not s.get("location"):
        return None
    now = time.time()
    pend = s.get("pending_read") or {}
    if pend and now - pend.get("at", 0) < READ_GIVE_UP_HOURS * 3600:
        return None
    if now - float(s.get("read_at") or 0) < READ_EVERY_MIN * 60:
        return None
    if not live:
        return {"action": "would_queue_review_read"}
    from automations.brand_audit import review_replies as RR
    rr = RR._load(P.path("review_replies.json"))
    # cards still waiting on ✅ are already in hand: leave room for new ones
    skip = [(e.get("review") or {}).get("name") for e in (rr.get("reviews") or {}).values()
            if isinstance(e, dict) and not e.get("posted") and (e.get("review") or {}).get("name")]
    from automations.online_presence import relay
    job = relay.enqueue(P.key, "social_check", {"do": "google_reviews", "location": s["location"],
                                                "skip": skip[:200]}, live=True)
    s["pending_read"] = {"job": job, "at": now}
    _save(P, s)
    return {"action": "review_read_queued", "note": job}

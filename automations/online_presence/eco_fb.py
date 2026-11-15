"""Facebook reviews through the office's OWN computer (Megan 2026-11-15:
"yes build the facebook part on the office computer").

CONNECTING (once, from Megan's Mac -- the only place Alphalete's Meta key is):
    python -m automations.online_presence.eco_fb --connect raf
  1. fb_hello  -> the office computer makes a one-time lock, sends back its
                  public half
  2. here: make a key for THAT office's page only (the page was shared with
     Alphalete's Meta business on the set-up call), seal it to that lock
     (icd_alerts/sealed.py)
  3. fb_key    -> the office computer opens it, proves it can read the page,
                  keeps it. The jobs sheet only ever held scrambled text.

EVERY PASS (Lucy 3, inside online_presence.run, offices with reviews_via eco):
  fb_reviews every 30 min -> the office's unanswered Facebook reviews;
  fb_reviews.process drafts (thank-yous on their own, "doesn't recommend"
  waits for ✅) and queues fb_reply jobs; the office computer posts them.
Lucy 3 never needs a Meta key for this.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

DOS = ("fb_hello", "fb_key", "fb_reviews", "fb_reply")
READ_EVERY_MIN = 30
READ_GIVE_UP_HOURS = 3


def _file(P) -> Path:
    return P.path("eco_fb.json")


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
    return getattr(P, "reviews_via", "lucy") == "eco" and bool(getattr(P, "facebook_page_id", ""))


def connected(P) -> bool:
    return bool(_load(P).get("connected"))


# ---- connecting (Megan's Mac) ----------------------------------------------------
def _wait(office: str, job: str, minutes: int, say=print) -> Dict:
    from automations.online_presence import relay
    end = time.time() + minutes * 60
    while time.time() < end:
        for j in relay._call({"office_job_log": {"office": office}}).get("jobs") or []:
            if j["job_id"] == job and j["status"] not in ("queued", "offered"):
                return j.get("result") or {}
        time.sleep(15)
    return {"status": "timed_out"}


def connect(P, say=print) -> Dict:
    from automations.brand_audit import fb_reviews
    from automations.icd_alerts import sealed
    from automations.online_presence import relay
    if not P.facebook_page_id:
        return {"ok": False, "why": "no Facebook page on this office yet (fb_reviews --connect first)"}
    job = relay.enqueue(P.key, "social_check", {"do": "fb_hello"}, live=True)
    say("asked %s's computer for a lock (job %s), waiting..." % (P.key, job[:8]))
    res = _wait(P.key, job, 12, say)
    if res.get("status") != "ready" or not res.get("public"):
        return {"ok": False, "why": "no lock came back: %s" % (res.get("error") or res.get("status"))}
    token = fb_reviews._page_token(fb_reviews._keys(), P.facebook_page_id)
    box = sealed.seal(token, res["public"])
    job = relay.enqueue(P.key, "social_check", {"do": "fb_key", "page_id": P.facebook_page_id, "box": box},
                        live=True)
    say("sent the sealed page key (job %s), waiting..." % job[:8])
    res = _wait(P.key, job, 12, say)
    if res.get("status") != "connected":
        return {"ok": False, "why": res.get("error") or res.get("status")}
    return {"ok": True, "page": res.get("page", "")}


# ---- answers (Lucy 3) ------------------------------------------------------------
def collect(P, rows: List[Dict], cl, *, dry: bool) -> List[Dict]:
    s = _load(P)
    fb_file = P.path("fb_review_replies.json")
    try:
        fb_state = json.loads(fb_file.read_text())
    except Exception:  # noqa: BLE001
        fb_state = {"reviews": {}, "posted_counts": {}}
    acts: List[Dict] = []
    for r in rows:
        res = r.get("result") or {}
        do, status = res.get("do"), res.get("status")
        if do == "fb_hello":
            continue                                   # connect() reads that one itself
        if do == "fb_key":
            s["connected"] = status == "connected"
            acts.append({"action": "facebook_connected" if s["connected"] else "facebook_key_" + str(status),
                         "note": res.get("page") or res.get("error", "")})
        elif do == "fb_reviews":
            s.pop("pending_read", None)
            if status == "ok":
                s.update(reviews=res.get("reviews") or [], read_at=time.time(), connected=True)
                acts.append({"action": "fb_reviews_read", "note": "%d unanswered" % len(s["reviews"])})
            else:
                if status == "signed_out":
                    s["connected"] = False
                acts.append({"action": "fb_reviews_read_" + str(status), "note": res.get("error", "")})
        elif do == "fb_reply":
            story = res.get("story")
            st = (fb_state.get("reviews") or {}).get(story)
            if status == "replied":
                acts.append({"action": "fb_reply_posted", "note": story})
                continue
            acts.append({"action": "fb_reply_" + str(status), "note": res.get("error", "")})
            if st is not None:
                if st.get("card_ts"):
                    st["posted"] = False               # its ✅ posts it again next pass
                    st["post_error"] = res.get("error") or status
                else:
                    fb_state["reviews"].pop(story, None)   # a thank-you: re-read, re-drafted
    if not dry:
        _save(P, s)
        fb_file.parent.mkdir(parents=True, exist_ok=True)
        fb_file.write_text(json.dumps(fb_state, indent=1))
    return acts


def reviews(P) -> List[Dict]:
    """The office's last answer, in fb_reviews' shape."""
    return [{"open_graph_story": {"id": x["story"]}, "recommendation_type": x.get("recommendation_type", ""),
             "review_text": x.get("review_text", ""), "created_time": x.get("created_time", "")}
            for x in _load(P).get("reviews") or [] if x.get("story")]


def poster(P):
    def _post(story: str, text: str) -> None:
        from automations.online_presence import relay
        relay.enqueue(P.key, "social_post", {"do": "fb_reply", "story": story, "comment": text}, live=True)
    return _post


def ensure_read(P, *, live: bool) -> Dict | None:
    s = _load(P)
    if not s.get("connected"):
        return None
    now = time.time()
    pend = s.get("pending_read") or {}
    if pend and now - pend.get("at", 0) < READ_GIVE_UP_HOURS * 3600:
        return None
    if now - float(s.get("read_at") or 0) < READ_EVERY_MIN * 60:
        return None
    if not live:
        return {"action": "would_queue_fb_read"}
    try:
        fb_state = json.loads(P.path("fb_review_replies.json").read_text())
    except Exception:  # noqa: BLE001
        fb_state = {}
    skip = list((fb_state.get("reviews") or {}).keys())      # already in hand or handled
    from automations.online_presence import relay
    job = relay.enqueue(P.key, "social_check", {"do": "fb_reviews", "skip": skip[-300:]}, live=True)
    s["pending_read"] = {"job": job, "at": now}
    _save(P, s)
    return {"action": "fb_read_queued", "note": job}


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="online_presence.eco_fb")
    ap.add_argument("--connect", required=True, metavar="OFFICE")
    a = ap.parse_args(argv)
    from automations.online_presence import offices
    p = offices.get(a.connect)
    if not p:
        print("✗ no office %r" % a.connect)
        return 1
    res = connect(p)
    print(("✓ %s's computer can answer Facebook reviews for %s" % (p.key, res["page"])) if res["ok"]
          else "✗ not connected: %s" % res["why"])
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

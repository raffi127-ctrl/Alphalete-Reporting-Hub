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

DOS = ("fb_hello", "fb_key", "fb_reviews", "fb_reply", "fb_signin")
READ_EVERY_MIN = 30
READ_GIVE_UP_HOURS = 3
# ONE REPLY AT A TIME, SPACED OUT (Megan 2026-11-16). A review by a person is
# answered by the office computer typing it on facebook.com; a burst of those
# is what gets an account a security check. So replies wait in an outbox here
# and go out one per OUTBOX_GAP_MIN, never two in flight.
OUTBOX_GAP_MIN = 20
INFLIGHT_GIVE_UP_HOURS = 3
CHECKPOINT_RETRY_HOURS = 24


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
    return bool(getattr(P, "facebook_page_id", "")) and (
        getattr(P, "reviews_via", "lucy") == "eco" or getattr(P, "facebook_via", "lucy") == "eco")


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
def _refused(err: str) -> bool:
    """Facebook's 'you may not comment here' answers -- no retry fixes them."""
    e = (err or "").lower()
    return "permission" in e or "(#10)" in e or "(#200)" in e
_DM = {
    "needs_signin": "Facebook needs you to sign in again on your office computer",
    "checkpoint": "Facebook is asking for a security check on your account",
    "not_page": "the Facebook account signed in on your office computer can't comment as your page",
}


def _owner_dm(P, cl, s: Dict, why: str, dry: bool) -> Dict:
    import datetime as dt
    today = dt.date.today().isoformat()
    text = (":warning: Lucy can't answer your Facebook reviews right now (%s). Message Megan or Eve "
            "and we'll sort it out -- it takes a minute." % _DM.get(why, why))
    if s.get("dm_day") == today or not getattr(P, "owner_slack_id", ""):
        return {"action": "dm_already_sent_today" if s.get("dm_day") == today else "no_owner_to_dm",
                "note": text}
    if not dry:
        cl.chat_postMessage(channel=P.owner_slack_id, text=text)
        s["dm_day"] = today
    return {"action": "dm_owner", "note": text}


def _unpark_refused(fb_state: Dict) -> int:
    """Reviews parked because Facebook's API refused them (written by a
    person) can be answered now the office computer is signed in to
    facebook.com: drop them so the next read brings them back to be drafted."""
    revs = fb_state.get("reviews") or {}
    gone = [k for k, v in revs.items() if v.get("blocked") and _refused(v["blocked"])]
    for k in gone:
        revs.pop(k, None)
        (fb_state.get("fails") or {}).pop(k, None)
    return len(gone)


def _ever_posted(fb_state: Dict) -> bool:
    """Has a reply from this page ever landed?

    The `ever_posted` counter only starts at the version that added it, so on
    its own it reads FALSE for a page with a history -- raf's had two replies
    land on 11/15, which is exactly the office the warning above was written
    for, so the cold start would have made it cry wolf on day one. Fall back to
    the state already on disk: a review marked posted and NOT blocked is one
    that went out. A parked review carries `blocked`, so it never counts."""
    if int(fb_state.get("ever_posted") or 0):
        return True
    for st in (fb_state.get("reviews") or {}).values():
        if isinstance(st, dict) and st.get("posted") and not st.get("blocked"):
            return True
    return False


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
        if do == "fb_signin":
            if status == "signed_in":
                s["fb_signed_in"] = True
                s.pop("paused", None)
                n = _unpark_refused(fb_state)
                acts.append({"action": "facebook_signed_in",
                             "note": "%d earlier refused review(s) will be answered" % n})
            else:
                acts.append({"action": "facebook_signin_" + str(status), "note": res.get("error", "")})
            continue
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
            fly = s.get("inflight") or {}
            if fly.get("story") == story:
                s.pop("inflight", None)
            if status in ("needs_signin", "checkpoint", "busy"):
                # Not this review's fault: it goes back to the front, untouched.
                if fly.get("story") == story:
                    s.setdefault("outbox", []).insert(0, {"story": story, "comment": fly.get("comment", "")})
                if status != "busy":
                    s["paused"] = {"why": status, "at": time.time()}
                    acts.append(_owner_dm(P, cl, s, status, dry))
                acts.append({"action": "fb_reply_" + status, "note": res.get("error", "")})
                continue
            if status == "not_page":
                fb_state.setdefault("reviews", {})[story] = dict(st or {}, posted=True,
                                                                 blocked=res.get("error", "not_page"))
                acts.append({"action": "fb_reply_not_page", "note": res.get("error", "")})
                acts.append(_owner_dm(P, cl, s, status, dry))
                continue
            if status == "replied":
                # Remember that this page CAN post. The refusal branch below
                # reads it to tell a per-review dead end from a page that has
                # never managed a single reply.
                fb_state["ever_posted"] = int(fb_state.get("ever_posted") or 0) + 1
                acts.append({"action": "fb_reply_posted",
                             "note": "%s (%s)" % (story, res.get("via") or "api")})
                continue
            err = res.get("error") or str(status)
            # FACEBOOK SAYS NO FOR GOOD on some reviews ("Permissions error": the
            # reviewer's post can't take a comment from the page). Retrying those
            # looped 140+ times on 11/15-16 -- a thank-you was dropped, re-read,
            # re-drafted and re-sent every 30 min. A refusal, or a second failure
            # of anything, parks the review as "blocked": kept in the state (so the
            # read skips it and nothing re-drafts it), never sent again.
            fails = max(int((st or {}).get("fails") or 0),
                        int((fb_state.get("fails") or {}).get(story) or 0)) + 1
            if status != "signed_out" and (_refused(err) or fails >= 2):
                fb_state.setdefault("reviews", {})[story] = dict(st or {}, posted=True, blocked=err[:400],
                                                                 fails=fails)
                acts.append({"action": "fb_reply_blocked",
                             "note": "%s: %s" % (story, err[:200])})
                # A PAGE WITH NO SUCCESSFUL REPLY ON RECORD IS NOT A PER-REVIEW
                # DEAD END. Parking is right for "this one review won't take a
                # comment" and it is how the 140x retry loop was stopped, so the
                # parking above is untouched -- but parking EVERY review on a
                # page that has never managed one turns a loud loop into SILENT
                # non-delivery: reviews go unanswered and the pass still reports
                # success. One extra act says that out loud, and it is a
                # separate act rather than a renamed one so anything reading
                # fb_reply_blocked keeps working.
                # [[feedback_green_means_delivered]]
                #
                # WHAT IT POINTS AT, corrected 2026-11-16: this note used to
                # blame the page token's pages_manage_engagement scope. That was
                # my guess from raf's 70-refusals-zero-successes day and it was
                # WRONG -- Graph never lets a Page comment on a review written
                # by a PERSON, whatever scopes the token holds (fb4c8ae; Megan
                # checked by hand). Since that commit a refusal falls through to
                # office_fb_browser, so reaching here with nothing ever posted
                # means NEITHER path has worked, and the thing a person can
                # actually act on is the browser path's sign-in.
                if not _ever_posted(fb_state):
                    acts.append({
                        "action": "fb_page_never_posted",
                        "note": "no reply from this page has ever landed, by API "
                                "or by browser, so this is the page's reply path "
                                "and not this one review -- check that Lucy is "
                                "signed in to facebook.com as the page "
                                "(fb_signin). Last refusal: " + err[:200]})
                continue
            acts.append({"action": "fb_reply_" + str(status), "note": err})
            if st is not None:
                st["fails"] = fails
                if st.get("card_ts"):
                    st["posted"] = False               # its ✅ posts it again next pass
                    st["post_error"] = err
                else:
                    fb_state["reviews"].pop(story, None)   # a thank-you: re-read, re-drafted
                    # (a pop loses the count, so remember it on the side)
                    fb_state.setdefault("fails", {})[story] = fails
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
    """Replies go in the outbox; send_next() hands them over one at a time."""
    def _post(story: str, text: str) -> None:
        s = _load(P)
        box = s.setdefault("outbox", [])
        if story != (s.get("inflight") or {}).get("story") and all(x["story"] != story for x in box):
            box.append({"story": story, "comment": text})
        _save(P, s)
    return _post


def send_next(P, *, live: bool, now: float | None = None) -> Dict | None:
    s = _load(P)
    now = now or time.time()
    box = s.get("outbox") or []
    if not box:
        return None
    pause = s.get("paused") or {}
    if pause:
        if pause.get("why") == "checkpoint" and now - pause.get("at", 0) >= CHECKPOINT_RETRY_HOURS * 3600:
            s.pop("paused", None)                       # one careful try a day after a check
        else:
            return {"action": "fb_replies_on_hold", "note": "%s, %d waiting" % (pause.get("why"), len(box))}
    fly = s.get("inflight") or {}
    if fly and now - fly.get("at", 0) < INFLIGHT_GIVE_UP_HOURS * 3600:
        return None
    if fly:                                             # never answered: try it again later
        box.append({"story": fly["story"], "comment": fly.get("comment", "")})
        s.pop("inflight", None)
    if now - float(s.get("last_sent") or 0) < OUTBOX_GAP_MIN * 60:
        _save(P, s)
        return None
    item = box.pop(0)
    if not live:
        return {"action": "would_send_fb_reply", "note": item["story"]}
    from automations.online_presence import relay
    job = relay.enqueue(P.key, "social_post", {"do": "fb_reply", "story": item["story"],
                                               "comment": item["comment"]}, live=True)
    s.update(inflight=dict(item, job=job, at=now), last_sent=now, outbox=box)
    _save(P, s)
    return {"action": "fb_reply_sent_to_office", "note": "%s (%d more waiting)" % (item["story"], len(box))}


def queue_signin(P) -> str:
    from automations.online_presence import relay
    return relay.enqueue(P.key, "social_check", {"do": "fb_signin"}, live=True)


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
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--connect", metavar="OFFICE")
    g.add_argument("--signin", metavar="OFFICE",
                   help="Facebook opens on the office computer; the owner signs in once")
    a = ap.parse_args(argv)
    from dataclasses import replace
    from automations.online_presence import offices
    p = offices.get(a.connect or a.signin)
    if not p:
        print("✗ no office %r" % (a.connect or a.signin))
        return 1
    if a.signin:
        job = queue_signin(p)
        print("✓ Facebook will open on %s's computer within a few minutes (job %s) -- "
              "they sign in with the account that manages the page, then it closes itself." % (p.key, job[:8]))
        return 0
    res = connect(p)
    if res["ok"] and p.facebook_via != "eco":
        offices.save(replace(p, facebook_via="eco"))
    print(("✓ %s's computer can answer Facebook reviews for %s" % (p.key, res["page"])) if res["ok"]
          else "✗ not connected: %s" % res["why"])
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

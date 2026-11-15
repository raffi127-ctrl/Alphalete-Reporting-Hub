"""One pass over every office's online presence: reviews, then photos.

    python -m automations.online_presence.run                 # all offices, dry
    python -m automations.online_presence.run --office kash   # one office, dry
    python -m automations.online_presence.run --live          # posts for real,
                                                              # but ONLY for
                                                              # offices whose row
                                                              # says mode "live"

DRY TWICE OVER. A run posts only when BOTH the command says --live AND the
office's own row says "live". Either one missing = it reads everything and
reports what it would have done, and nothing reaches Slack, Google or Zoho.

ALPHALETE IS NOT HERE. Its reviews ride the brand_audit noon run and its
photos ride the social scanner, untouched.

One office failing never stops the next: each is its own try, and a failure
is printed with the office's key so the log says whose it was.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from typing import Dict, List

from automations.online_presence import offices


def run_office(p: offices.Presence, *, live: bool,
               answers: List[dict] | None = None) -> Dict[str, List[dict]]:
    """`answers` = this office's answered relay jobs (read once per pass for
    every office, by main). Posts, checks and DMs come from those first, so a
    photo posted since the last pass gets its 🚀 before anything new queues."""
    from automations.brand_audit import review_replies, social_inbox
    dry = not (live and p.is_live)
    out: Dict[str, List[dict]] = {"dry_run": dry}
    if p.social and p.post_via == "eco":
        from automations.brand_audit.social_inbox import _client
        from automations.online_presence import watch
        from automations.online_presence import eco_reviews
        review_rows, answers = eco_reviews.split(answers or [])
        acts = watch.collect(p, answers, _client(), dry=dry) if answers else []
        if review_rows:
            from automations.online_presence import eco_fb
            out["google reviews (office computer)"] = eco_reviews.collect(p, review_rows, _client(), dry=dry)
            out["facebook (office computer)"] = eco_fb.collect(p, review_rows, _client(), dry=dry)
        chk = watch.ensure_daily_check(p, live=not dry)
        out["office computer"] = acts + ([chk] if chk else [])
        # Weekly reels (reels_flow.py) are PARKED (Megan 2026-11-09: "we don't
        # need to worry about posting reels right now"). The code + tests stay;
        # turning them on = calling reels_flow.step here again, plus
        # imageio-ffmpeg on Lucy 3 and an agent release for video posting.
    # Monthly blog + quarterly press-release drafts (content.py) are PARKED
    # too (Megan 2026-11-09: "hold off on the blog and press releases for
    # right now"). Turning them on = calling content.step(p, client, live=...)
    # here.
    if p.reviews and getattr(p, "reviews_via", "lucy") == "eco":
        # The office's own computer reads + posts; Lucy 3 drafts and asks ✅.
        from automations.brand_audit.social_inbox import _client as _cl
        from automations.online_presence import eco_reviews, review_alerts
        if not (p.social and p.post_via == "eco"):      # answers not read above
            review_rows, _rest = eco_reviews.split(answers or [])
            if review_rows:
                from automations.online_presence import eco_fb
                out["google reviews (office computer)"] = eco_reviews.collect(p, review_rows, _cl(), dry=dry)
                out["facebook (office computer)"] = eco_fb.collect(p, review_rows, _cl(), dry=dry)
        rd = eco_reviews.ensure_read(p, live=not dry)
        if not eco_reviews.signed_in(p):
            out["reviews"] = [{"action": "waiting_on_google_signin",
                               "note": f"run `setup google-signin {p.key}` on the set-up call"}] + ([rd] if rd else [])
        else:
            revs = eco_reviews.reviews(p)
            if p.gbp_location:
                out["bad reviews"] = review_alerts.check(p, _cl(), live=not dry, reviews=revs)
            out["reviews"] = review_replies.process_reviews(
                dry_run=dry, profile=p, fetch=lambda: revs, post=eco_reviews.poster(p),
                can_post=True) + ([rd] if rd else [])
    elif p.reviews:
        # The ALERT first (seconds), then the reply drafts (Claude, slower):
        # a bad review is in front of the office before its draft is written.
        if p.gbp_location:
            from automations.brand_audit.social_inbox import _client as _cl
            from automations.online_presence import review_alerts
            out["bad reviews"] = review_alerts.check(p, _cl(), live=not dry)
        out["reviews"] = review_replies.process_reviews(dry_run=dry, profile=p)
    if p.reviews and getattr(p, "facebook_page_id", "") and getattr(p, "reviews_via", "lucy") == "eco":
        # the office's own computer reads + posts with a key for just its page
        try:
            from automations.brand_audit import fb_reviews
            from automations.online_presence import eco_fb
            rd = eco_fb.ensure_read(p, live=not dry)
            if not eco_fb.connected(p):
                out["facebook reviews"] = [{"action": "waiting_on_facebook_connect",
                                            "note": f"run `eco_fb --connect {p.key}` from Megan's Mac"}]
            else:
                out["facebook reviews"] = fb_reviews.process(
                    live=not dry, profile=p, reviews=eco_fb.reviews(p),
                    post=eco_fb.poster(p)) + ([rd] if rd else [])
        except Exception as e:                  # never let Facebook stop the pass
            out["facebook reviews"] = [{"action": "error", "note": str(e)[:200]}]
    elif p.reviews and getattr(p, "facebook_page_id", ""):
        try:
            from automations.brand_audit import fb_reviews
            out["facebook reviews"] = fb_reviews.process(live=not dry, profile=p)
        except Exception as e:                  # never let Facebook stop the pass
            out["facebook reviews"] = [{"action": "error", "note": str(e)[:200]}]
    if p.social:
        lock = p.path("social_inbox.lock")
        if not social_inbox.acquire_lock(lock):
            out["photos"] = [{"action": "skipped", "note": "another pass is running"}]
        else:
            try:
                out["photos"] = social_inbox.process_inbox(dry_run=dry, profile=p)
            finally:
                social_inbox.release_lock(lock)
    return out


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="online_presence.run")
    ap.add_argument("--office", default="", help="one office's ECO key")
    ap.add_argument("--live", action="store_true",
                    help="post for real, for offices whose row says live")
    a = ap.parse_args(argv)
    import time as _time
    started = _time.monotonic()
    # Seconds per piece of the pass (timing.py names the slowest one when a
    # pass runs long -- 11/14 a pass with no live offices took 7m 19s on
    # Lucy 3 and nothing said where).
    steps: Dict[str, float] = {}
    _last = [started]

    def lap(name: str) -> None:
        now = _time.monotonic()
        steps[name] = steps.get(name, 0.0) + (now - _last[0])
        _last[0] = now

    allrows = offices.load()
    if a.office:
        p = allrows.get(a.office.lower())
        if not p:
            print(f"✗ no online-presence office {a.office!r}")
            return 1
        todo = [p]
    else:
        todo = list(allrows.values())
    if not todo:
        print("No offices set up yet (python -m automations.online_presence.setup add ...)")
    lap("office list")

    # Rooms first: an office that said "create one for me" gets its channel
    # the next time this runs, whether or not it has an office row yet.
    try:
        from automations.online_presence import rooms
        for pg in rooms.ping_new(live=a.live):
            print(f"[sign-up] {pg['business']}: {pg['action']} in the alerts channel")
        for r in rooms.run(live=a.live):
            print(f"[room] {r.get('business')}: {r['action']} #{r.get('channel', '')}"
                  + (" — invite by hand: " + ", ".join(r["missed"]) if r.get("missed") else ""))
    except Exception as e:
        print(f"[room] couldn't check for rooms to make ({type(e).__name__}: {str(e)[:80]})")
    lap("sign-ups + rooms")

    # Can Lucy read Google reviews at all? One key covers Alphalete and every
    # office; a missing or dead key alerts the manager (key_watch, 11/10).
    if not a.office:
        try:
            from automations.online_presence import key_watch
            for x in key_watch.check(live=a.live):
                if x["action"] != "ok":
                    print(f"[google key] {x['action']} · {x.get('why') or x.get('kind') or ''}")
        except Exception as e:
            print(f"[google key] check failed ({type(e).__name__}: {str(e)[:80]})")
        lap("Google key check")

    # Alphalete's own bad Google reviews alert on the same 10 minutes (its
    # reply drafts still come from the noon brand_audit run, unchanged).
    if not a.office:
        try:
            from automations.brand_audit.social_inbox import _client as _cl
            from automations.online_presence import review_alerts
            for x in ([] if offices.moved_alphalete() else
                      review_alerts.check(offices.alphalete(), _cl(), live=a.live)):
                print(f"[alphalete] bad reviews: {x['action']} · {x.get('note') or x.get('error') or ''}")
        except Exception as e:
            print(f"[alphalete] bad-review check failed ({type(e).__name__}: {str(e)[:80]})")
        lap("Alphalete bad reviews")

    # Reddit / Indeed / Glassdoor mentions that reached Lucy's inbox
    # (email_alerts.py): live offices + Alphalete, once per pass.
    if not a.office:
        try:
            from automations.brand_audit.social_inbox import _client as _cl
            from automations.online_presence import email_alerts
            watch_list = ([] if offices.moved_alphalete() else [offices.alphalete()]) \
                + [p for p in todo if p.is_live]
            for x in email_alerts.check(watch_list, _cl(), live=a.live):
                print(f"[mentions] {x['action']} · {x.get('note') or ''}")
        except Exception as e:
            print(f"[mentions] inbox check failed ({type(e).__name__}: {str(e)[:80]})")
        lap("inbox mentions")

    # ONE read of the relay for every office (not one per office).
    answers: Dict[str, List[dict]] = {}
    if any((p.social and p.post_via == "eco") or getattr(p, "reviews_via", "") == "eco" for p in todo):
        try:
            from automations.online_presence import relay
            for r in relay.answered():
                answers.setdefault(str(r.get("office", "")).lower(), []).append(r)
        except Exception as e:
            print(f"relay read failed ({type(e).__name__}: {str(e)[:80]}) — "
                  "office answers wait for the next pass")
        lap("relay read")
    read: List[str] = []

    failed = 0
    for p in todo:
        # A LIVE pass is for LIVE offices only. A dry office's dry pass still
        # drafts captions and replies with Claude, which costs money and does
        # nothing every 10 minutes -- run those by hand with no --live.
        if a.live and not p.is_live:
            continue
        if p.replaces_alphalete:
            # the first pass after the switch carries Alphalete's memory over,
            # so nothing already answered or posted happens twice
            copied = offices.migrate_alphalete_state(p)
            if copied:
                print(f"[{p.key}] took over Alphalete: carried over {', '.join(copied)}")
        probs = p.problems()
        if probs:
            print(f"[{p.key}] skipped — {'; '.join(probs)}")
            continue
        try:
            mine = answers.get(p.key, [])
            res = run_office(p, live=a.live, answers=mine)
            if not res["dry_run"]:
                read += [r["job_id"] for r in mine]
        except Exception:
            failed += 1
            print(f"[{p.key}] FAILED\n{traceback.format_exc()}")
            lap(f"office {p.key}")
            continue
        tag = "DRY" if res.pop("dry_run") else "LIVE"
        for part, acts in res.items():
            for x in acts:
                what = (x.get("reply") or x.get("caption") or x.get("note")
                        or x.get("error") or "")
                print(f"[{p.key}] {tag} {part}: {x.get('action')} · {str(what)[:90]}")
        lap(f"office {p.key}")
    if read:
        from automations.online_presence import relay
        relay.mark_read(read)
        lap("relay mark-read")
    # How long the whole pass took (timing.py): logged every time, and a
    # once-a-day heads-up past 5 minutes -- the "does LucyECO Social need its
    # own Lucy?" number. Only the full scheduled pass counts.
    if not a.office:
        from automations.online_presence import timing
        took = _time.monotonic() - started
        timing.record("pass", took, offices=sum(1 for p in todo if p.is_live), live=a.live,
                      steps=steps)
        print(f"pass took {timing.fmt(took)}")
        for name, secs in sorted(steps.items(), key=lambda kv: -kv[1])[:5]:
            print(f"  {name}: {timing.fmt(secs)}")
    print("=== done ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

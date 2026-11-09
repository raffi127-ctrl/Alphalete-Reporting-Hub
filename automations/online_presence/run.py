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
        acts = watch.collect(p, answers or [], _client(), dry=dry) if answers else []
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
    if p.reviews:
        # The ALERT first (seconds), then the reply drafts (Claude, slower):
        # a bad review is in front of the office before its draft is written.
        if p.gbp_location:
            from automations.brand_audit.social_inbox import _client as _cl
            from automations.online_presence import review_alerts
            out["bad reviews"] = review_alerts.check(p, _cl(), live=not dry)
        out["reviews"] = review_replies.process_reviews(dry_run=dry, profile=p)
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

    # Alphalete's own bad Google reviews alert on the same 10 minutes (its
    # reply drafts still come from the noon brand_audit run, unchanged).
    if not a.office:
        try:
            from automations.brand_audit.social_inbox import _client as _cl
            from automations.online_presence import review_alerts
            for x in review_alerts.check(offices.alphalete(), _cl(), live=a.live):
                print(f"[alphalete] bad reviews: {x['action']} · {x.get('note') or x.get('error') or ''}")
        except Exception as e:
            print(f"[alphalete] bad-review check failed ({type(e).__name__}: {str(e)[:80]})")

    # ONE read of the relay for every office (not one per office).
    answers: Dict[str, List[dict]] = {}
    if any(p.social and p.post_via == "eco" for p in todo):
        try:
            from automations.online_presence import relay
            for r in relay.answered():
                answers.setdefault(str(r.get("office", "")).lower(), []).append(r)
        except Exception as e:
            print(f"relay read failed ({type(e).__name__}: {str(e)[:80]}) — "
                  "office answers wait for the next pass")
    read: List[str] = []

    failed = 0
    for p in todo:
        # A LIVE pass is for LIVE offices only. A dry office's dry pass still
        # drafts captions and replies with Claude, which costs money and does
        # nothing every 10 minutes -- run those by hand with no --live.
        if a.live and not p.is_live:
            continue
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
            continue
        tag = "DRY" if res.pop("dry_run") else "LIVE"
        for part, acts in res.items():
            for x in acts:
                what = (x.get("reply") or x.get("caption") or x.get("note")
                        or x.get("error") or "")
                print(f"[{p.key}] {tag} {part}: {x.get('action')} · {str(what)[:90]}")
    if read:
        from automations.online_presence import relay
        relay.mark_read(read)
    print("=== done ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

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


def run_office(p: offices.Presence, *, live: bool) -> Dict[str, List[dict]]:
    from automations.brand_audit import review_replies, social_inbox
    dry = not (live and p.is_live)
    out: Dict[str, List[dict]] = {"dry_run": dry}
    if p.reviews:
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
        print("=== done ===")
        return 0

    failed = 0
    for p in todo:
        probs = p.problems()
        if probs:
            print(f"[{p.key}] skipped — {'; '.join(probs)}")
            continue
        try:
            res = run_office(p, live=a.live)
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
    print("=== done ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

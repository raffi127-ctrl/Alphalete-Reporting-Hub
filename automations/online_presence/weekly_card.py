"""The weekly card for each office, Fridays at noon, in its Slack channel.

Megan 2026-11-08: "this review card we can just do once a week - friday at
noon". Since 2026-11-10 it is the SIMPLE card (simple_card.py, Megan: "redo
the card all together"): Google rating + new reviews, the top 5 Google
results for their name, posts, their info online, up to 3 things to do, 3
ways to rank higher on Google, and week-by-week charts.

What goes out, per office:
    the card picture                     (channel, the parent post)
      -> links + every new review and how it was answered   (thread)
      -> the PDF: every "why + how" spelled out, links that work   (thread)
Then this Friday's numbers are saved, so next Friday can say "vs last week"
(record() -- only a live post saves; a preview never becomes "last week").

INDEED + GLASSDOOR ARE NOT READ HERE: both block robots (Megan's rule:
Indeed is notify-only, and we don't get around robot checks).

Alphalete's own card goes to #alphaletesocialmedia on the same run.

LIVE OFFICES ONLY on a --live run; anything else is a dry run that renders
the card locally and posts nothing.

    python -m automations.online_presence.weekly_card                 # dry: every office
    python -m automations.online_presence.weekly_card --office kash   # dry: one
    python -m automations.online_presence.weekly_card --live          # Friday timer
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path
from typing import Dict, List

from automations.online_presence import offices

def company_for(p) -> "object":
    """The brand_audit Company for an office, built from its sign-up."""
    from automations.brand_audit.intake import Company
    from automations.online_presence.consistency import city_of
    s = p.social_links
    return Company(name=p.business_name, owner="", icd_name=p.key,
                   location=city_of(p.address) or p.address,
                   website=p.website, google_profile=p.google_link,
                   instagram=s.get("instagram", ""), facebook=s.get("facebook", ""),
                   linkedin=s.get("linkedin", ""), twitter=s.get("x", ""),
                   indeed=p.indeed_url, glassdoor=p.glassdoor_url)


OUT = Path(__file__).resolve().parents[2] / "output" / "online_presence"


def run_office(p, *, live: bool, now: dt.datetime | None = None) -> Dict:
    from automations.online_presence import simple_card as sc
    now = now or dt.datetime.now()
    card = sc.build(p, now=now)
    stem = f"weekly_card_{p.key}_{now:%Y%m%d}"
    files = sc.files(card, OUT / p.key, stem)
    out = {"office": p.key, "verdict": card["verdict"], "card": str(files["png"])}
    if not live:
        out["action"] = "would_post"
        return out
    from automations.brand_audit.social_inbox import _client
    cl = _client()
    # SUPER SIMPLE (Megan 2026-11-13: "way too clogged up ... we need it super
    # simple"): the picture + a one-line title, and ONE thing in the thread --
    # the PDF. Its links (review link, Slack, listing) are tappable inside it.
    head = f":bar_chart: *Your week online · {card['week_of']} – {card['until']}*"
    cl.files_upload_v2(channel=p.slack_channel, file=str(files["png"]),
                       filename=f"{p.business_name} weekly card.png",
                       title=f"{p.business_name} · your week online",
                       initial_comment=head)
    # The parent is the picture; everything else goes in its thread
    # (Raf's standing post shape: parent = title/image only).
    parent = _parent_ts(cl, p.slack_channel, head)
    if not parent:
        raise RuntimeError("card picture didn't show up in the channel")
    cl.files_upload_v2(channel=p.slack_channel, thread_ts=parent, file=str(files["pdf"]),
                       filename=f"{p.business_name} weekly card.pdf",
                       title="Full card (tap to open)",
                       initial_comment="Tap to open the full card: every step, with the links.")
    sc.record(p, card, now)
    out["action"] = "posted"
    return out


def _parent_ts(cl, channel: str, head: str) -> str:
    """The ts of the card we just posted (files_upload_v2 doesn't hand it back
    reliably), found by its header in the channel's newest messages."""
    import time
    for _ in range(6):
        for m in cl.conversations_history(channel=channel, limit=10).get("messages") or []:
            if head.split(" · ")[0] in (m.get("text") or "") and m.get("files"):
                return m["ts"]
        time.sleep(3)
    return ""


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="online_presence.weekly_card")
    ap.add_argument("--office", default="")
    ap.add_argument("--live", action="store_true", help="post to live offices' channels")
    a = ap.parse_args(argv)
    import time as _time
    started = _time.monotonic()
    # Alphalete gets the same card in #alphaletesocialmedia (Megan 2026-11-10),
    # first, so an office's trouble never holds it up.
    rows = {"alphalete": offices.alphalete(), **offices.load()}
    todo = [rows[a.office.lower()]] if a.office and a.office.lower() in rows else (
        [] if a.office else list(rows.values()))
    if a.office and not todo:
        print(f"✗ no online-presence office {a.office!r}")
        return 1
    failed = 0
    for p in todo:
        if a.live and not p.is_live:
            continue
        try:
            r = run_office(p, live=a.live and p.is_live)
            print(f"[{p.key}] {r['action']} · {r['verdict']} · {r['card']}")
        except Exception:
            failed += 1
            print(f"[{p.key}] FAILED\n{traceback.format_exc()}")
    if len(todo) <= 1 and not a.office:
        print("No ICD offices set up yet (Alphalete only).")
    if not a.office:
        from automations.online_presence import timing
        took = _time.monotonic() - started
        timing.record("weekly", took, offices=sum(1 for p in todo if p.is_live), live=a.live)
        print(f"weekly run took {timing.fmt(took)}")
    print("=== done ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

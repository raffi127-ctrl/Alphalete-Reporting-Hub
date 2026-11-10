"""The weekly Brand Health card for each office, Fridays at noon, in its room.

Megan 2026-11-08: "this review card we can just do once a week - friday at
noon". Same engine as Alphalete's card (brand_audit: Google reviews, search
results, Reddit, website, design review), pointed at the office's OWN
details from its sign-up. Posted to the office's room as the card image,
then one short message whose thread lists what doesn't match their sign-up
(consistency.py) and what to check by hand.

INDEED + GLASSDOOR ARE NOT READ HERE. Both block robots; for offices they
are "check by hand" lines in the thread, never scraped (Megan's rule: Indeed
is notify-only, and we don't get around robot checks).

LIVE OFFICES ONLY on a --live run; anything else is a dry run that renders
the card locally and posts nothing.

    python -m automations.online_presence.weekly_card                 # dry: every office
    python -m automations.online_presence.weekly_card --office kash   # dry: one
    python -m automations.online_presence.weekly_card --live          # Friday timer
"""
from __future__ import annotations

import argparse
import sys
import traceback
from typing import Dict, List

from automations.online_presence import offices

# What an office card reads (the Alphalete card's list, minus the Indeed /
# Glassdoor scrape and the Meta API, which only Alphalete has a token for).
OFFICE_COLLECTORS = ("google_reviews", "serp", "reddit", "website",
                     "social_public", "website_review")


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


def audit(company) -> tuple:
    """(scorecard, results) with only the office collectors."""
    from automations.brand_audit import score
    from automations.brand_audit import collectors as C
    from automations.brand_audit.collectors.base import CollectorResult
    import importlib
    results = {}
    for name in OFFICE_COLLECTORS:
        mod = importlib.import_module(f"automations.brand_audit.collectors.{name}")
        try:
            r = mod.collect(company)
        except Exception as e:
            r = CollectorResult.failed(getattr(mod, "SOURCE", name), str(e))
        results[r.source] = r.as_dict()
    return score.build_scorecard(results, company).as_dict(), results


def checks_message(p) -> tuple:
    """(short header, thread detail) for the sign-up match + by-hand list."""
    from automations.online_presence import consistency
    rows = consistency.checks(p)
    bad = [r for r in rows if r["ok"] is False]
    hand = [r for r in rows if r["ok"] is None]
    head = (f":white_check_mark: *Everything Lucy can check matches your sign-up*"
            if not bad else
            f":warning: *{len(bad)} thing{'s' if len(bad) != 1 else ''} "
            f"{'don' if len(bad) != 1 else 'doesn'}'t match your sign-up this week*")
    lines = [f"• *{r['site']}: {r['item']}*: should be `{r['expected']}`, "
             f"shows `{r['found']}`" for r in bad]
    if hand:
        lines += ["", "*Check by hand* (these sites block Lucy):"]
        lines += [f"• {r['site']}: {r['expected']} ({r['where']})" for r in hand]
    return head, "\n".join(lines) or "Nothing to fix."


def run_office(p, *, live: bool) -> Dict:
    from automations.brand_audit import alerts, report
    company = company_for(p)
    card, results = audit(company)
    path = report.save_report(company, card, results)
    out = {"office": p.key, "grade": card.get("overall_grade"),
           "score": card.get("overall_score"), "card": str(path)}
    if not live:
        out["action"] = "would_post"
        return out
    png = report.render_card_png(path)
    alerts.post_card_image(p.business_name, png, card, channel_id=p.slack_channel)
    from automations.brand_audit.social_inbox import _client
    cl = _client()
    head, detail = checks_message(p)
    r = cl.chat_postMessage(channel=p.slack_channel, text=head)
    cl.chat_postMessage(channel=p.slack_channel, thread_ts=r.get("ts"), text=detail)
    out["action"] = "posted"
    return out


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
    rows = offices.load()
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
            print(f"[{p.key}] {r['action']} · {r['grade']} ({r['score']}/100) · {r['card']}")
        except Exception:
            failed += 1
            print(f"[{p.key}] FAILED\n{traceback.format_exc()}")
    if not todo:
        print("No offices set up yet.")
    if not a.office:
        from automations.online_presence import timing
        took = _time.monotonic() - started
        timing.record("weekly", took, offices=sum(1 for p in todo if p.is_live), live=a.live)
        print(f"weekly run took {timing.fmt(took)}")
    print("=== done ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

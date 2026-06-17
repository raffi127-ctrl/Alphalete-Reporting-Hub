"""Brand Health audit orchestrator.

  intake (company links)  ->  collectors  ->  score  ->  Brand Health Card

Usage:
  python -m automations.brand_audit.run                 # default company (Alphalete)
  python -m automations.brand_audit.run --company "X"   # one company by name
  python -m automations.brand_audit.run --all           # every row in the sheet
  python -m automations.brand_audit.run --dry-run       # no external side effects

v1 is read-only: it writes the Brand Health Card to output/ (a safe local
deliverable). --dry-run additionally suppresses Phase-2 Slack alerts (not wired
yet). Prints '=== done ===' on success so the Hub recognizes completion.
"""
from __future__ import annotations

import argparse
import sys

# UTF-8 console safety (emoji in output) on both macOS and Windows.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from automations.brand_audit import intake, score, report, alerts, sheet_log
from automations.brand_audit.config import DEFAULT_COMPANY, DEFAULT_INTAKE_SHEET_ID
from automations.brand_audit.collectors import (
    google_reviews, serp, reddit, website, reputation, social_public,
    website_review, social_meta,
)

_COLLECTORS = [google_reviews, serp, reddit, website, reputation,
               social_public, website_review, social_meta]


def audit_company(company) -> tuple[dict, dict]:
    """Run every collector (each fails soft) and build the scorecard."""
    results = {}
    for mod in _COLLECTORS:
        try:
            r = mod.collect(company)
        except Exception as e:  # belt-and-suspenders; collectors fail soft already
            from automations.brand_audit.collectors.base import CollectorResult
            r = CollectorResult.failed(getattr(mod, "SOURCE", mod.__name__), str(e))
        results[r.source] = r.as_dict()
        status = "ok" if results[r.source]["ok"] else f"FAILED: {results[r.source]['error']}"
        print(f"  · {r.source}: {status}")
    card = score.build_scorecard(results, company)
    _record_review_snapshots(company, results)
    return card.as_dict(), results


def _record_review_snapshots(company, results) -> None:
    """Persist this run's review totals so 'new in last 7 days' can be computed
    next week. Local state only — safe to do every run."""
    from automations.brand_audit import review_history
    g = (results.get("google_reviews") or {}).get("metrics") or {}
    rep = (results.get("reputation") or {}).get("metrics") or {}
    review_history.record(company.name, "Google", g.get("review_count"))
    review_history.record(company.name, "Glassdoor", rep.get("glassdoor_review_count"))
    review_history.record(company.name, "Indeed", rep.get("indeed_review_count"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="brand_audit")
    p.add_argument("--company", default=None,
                   help="company name to audit (default: the preview company)")
    p.add_argument("--all", action="store_true",
                   help="audit every company row in the intake sheet")
    p.add_argument("--sheet-id", default=DEFAULT_INTAKE_SHEET_ID)
    p.add_argument("--dry-run", action="store_true",
                   help="no external side effects (suppresses Slack alerts + "
                        "sheet-log writes)")
    p.add_argument("--no-log", action="store_true",
                   help="skip writing the per-company log tab to the sheet")
    p.add_argument("--no-card", action="store_true",
                   help="skip posting the rendered card image to Slack")
    args = p.parse_args(argv)

    if args.all:
        companies = intake.read_companies(args.sheet_id)
    else:
        name = args.company or DEFAULT_COMPANY
        c = intake.find_company(name, args.sheet_id)
        if not c:
            print(f"!! company {name!r} not found in the intake sheet", file=sys.stderr)
            return 1
        companies = [c]

    if not companies:
        print("!! no companies to audit", file=sys.stderr)
        return 1

    for company in companies:
        print(f"== auditing {company.name} ==")
        card, results = audit_company(company)
        path = report.save_report(company, card, results)
        print(f"  overall: {card['overall_grade']} ({card['overall_score']}/100)")
        print(f"  card: {path}")
        if not args.dry_run and not args.no_card:
            try:
                png = report.render_card_png(path)
                cr = alerts.post_card_image(company.name, png, card)
                print("  card image posted to Slack" if cr.get("posted")
                      else f"  card image post: {cr}")
            except Exception as e:
                print(f"  !! card-to-Slack failed (non-fatal): {e}")
        neg = [f for f in card["flags"] if f["level"] == "negative"]
        if neg:
            try:
                a = alerts.send_alerts(company.name, card, dry_run=args.dry_run)
                if a.get("dry_run"):
                    print(f"  {len(neg)} negative finding(s) — would alert "
                          f"{a['would_post']} new to Slack (--dry-run)")
                elif a.get("posted"):
                    print(f"  alerted {a['count']} new finding(s) to Slack")
                else:
                    print(f"  {len(neg)} negative finding(s) — "
                          f"{a.get('reason', 'nothing new to alert')}")
            except Exception as e:
                print(f"  !! Slack alert failed (non-fatal): {e}")

        if not args.no_log:
            try:
                lg = sheet_log.write_log(args.sheet_id, company, card,
                                         dry_run=args.dry_run)
                if lg.get("dry_run"):
                    print(f"  log: would write {lg['would_write']} row(s) to "
                          f"tab '{lg['tab']}' (--dry-run)")
                else:
                    print(f"  log: tab '{lg['tab']}' — appended {lg['appended']} "
                          f"new, skipped {lg['skipped_existing']} existing")
            except Exception as e:
                print(f"  !! sheet-log write failed (non-fatal): {e}")

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

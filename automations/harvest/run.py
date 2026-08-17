"""Harvest-prime entrypoint — pull today's scheduled churn views ONCE over one
login into the dated cache, so cache-reading reports (HARVEST_MODE=on) can skip
their own scrapes.

    python -m automations.harvest.run                 # harvest today's needs
    python -m automations.harvest.run --date 2026-07-12
    python -m automations.harvest.run --dry-run       # list needs, pull nothing
    python -m automations.harvest.run --full-cluster  # all churn needs, not just today's scheduled

At cutover this runs FIRST in the batch (before the churn/daily-metrics reports).
It writes cache + a manifest; it NEVER writes a Sheet or posts Slack. Running it
is harmless even with HARVEST_MODE off — reports just ignore the cache.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time


def _now() -> dt.datetime:
    return dt.datetime.now()


def _deadline(hhmm: str) -> dt.datetime:
    """Today at HH:MM local. If that's already past, the loop won't run — the
    caller just gets the single pass it already did."""
    h, m = (int(x) for x in hhmm.split(":", 1))
    return _now().replace(hour=h, minute=m, second=0, microsecond=0)

from automations.harvest.needs import (scheduled_data_needs, CHURN_CLUSTER_NEEDS,
                                       all_known_needs)
from automations.harvest.harvester import harvest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest-run")
    ap.add_argument("--date", default=None, help="target date YYYY-MM-DD (default today)")
    ap.add_argument("--dry-run", action="store_true", help="list the needs, pull nothing")
    ap.add_argument("--full-cluster", action="store_true",
                    help="harvest ALL churn-cluster needs, not just today's scheduled")
    ap.add_argument("--all", action="store_true",
                    help="harvest EVERY known need (churn cluster + the "
                         "ledger-generated registry) — the 3am whole-org pass")
    ap.add_argument("--retention-days", type=int, default=None)
    ap.add_argument("--until", default=None, metavar="HH:MM",
                    help="keep re-probing DEFERRED needs until this local time "
                         "(e.g. 03:50, just before the 4am orchestrator). "
                         "Without it, one pass and deferred needs are left to "
                         "their reports' live scrape.")
    ap.add_argument("--retry-minutes", type=int, default=10,
                    help="minutes between circle-back passes (default 10)")
    args = ap.parse_args(argv)

    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    if args.all:
        needs = all_known_needs()
    elif args.full_cluster:
        needs = CHURN_CLUSTER_NEEDS
    else:
        needs = scheduled_data_needs(target)

    # Fold in the order-log ALLREPS need (shared by the 8 office-metrics reports)
    # so the prime warms it once too. Shadow import — order_log pulls the browser
    # stack, so ONLY the prime (never needs.py, never the live report path)
    # references it. Best-effort: a miss here just means those reports live-scrape.
    try:
        from automations.harvest.needs_order_log import order_log_needs
        from automations.harvest.needs import dedupe_by_cache_key
        needs = dedupe_by_cache_key(list(needs) + order_log_needs(target))
    except Exception as e:  # noqa: BLE001 — never let the add break the prime
        print(f"(order-log need skipped: {type(e).__name__}: {e})")

    scope = ("ALL known needs" if args.all
             else "full-cluster" if args.full_cluster else "scheduled today")
    print(f"=== harvest-prime {target.isoformat()} — {len(needs)} need(s) "
          f"({scope}) ===")
    if args.dry_run:
        for n in needs:
            print(f"  · {n.label or n.view_url}")
        print("(dry-run — nothing pulled)")
        return 0

    result = harvest(target, needs, retention_days=args.retention_days)
    ok = sum(1 for e in result.entries if e.error is None)
    print(f"=== primed {ok}/{len(result.entries)} ok, "
          f"{len(result.deferred)} deferred, {len(result.pruned)} pruned ===")

    # Circle back on DEFERRED needs (Megan 2026-08-17). At 3am Tableau is often
    # still publishing, so the readiness probe defers views that aren't in yet.
    # A deferred need is NOT harvested, which means its report live-scrapes at
    # 4am — correct, but it spends the Tableau access we were trying to save.
    # So keep re-probing just the deferred ones until --until, then stop and let
    # the reports fall back. Mirrors the orchestrator's own circle-back.
    if args.until and result.deferred:
        deadline = _deadline(args.until)
        pending = list(result.deferred)
        while pending and _now() < deadline:
            time.sleep(args.retry_minutes * 60)
            if _now() >= deadline:
                break
            print(f"--- circle-back: re-probing {len(pending)} deferred need(s) "
                  f"at {_now():%H:%M} (until {args.until}) ---")
            again = harvest(target, pending, retention_days=args.retention_days)
            newly_ok = sum(1 for e in again.entries if e.error is None)
            ok += newly_ok
            pending = list(again.deferred)
        if pending:
            print(f"=== {len(pending)} need(s) never became ready by {args.until} "
                  f"— their reports will live-scrape ===")
            for n in pending:
                print(f"  · {n.label or n.view_url}")

    # Non-zero only if NOTHING harvested (a total failure the orchestrator should
    # see); partial success is fine — cache-reading reports fall back to live for
    # any missing view.
    return 0 if ok > 0 or not result.entries else 1


if __name__ == "__main__":
    sys.exit(main())

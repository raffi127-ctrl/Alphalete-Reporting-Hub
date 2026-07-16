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

from automations.harvest.needs import scheduled_data_needs, CHURN_CLUSTER_NEEDS
from automations.harvest.harvester import harvest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest-run")
    ap.add_argument("--date", default=None, help="target date YYYY-MM-DD (default today)")
    ap.add_argument("--dry-run", action="store_true", help="list the needs, pull nothing")
    ap.add_argument("--full-cluster", action="store_true",
                    help="harvest ALL churn-cluster needs, not just today's scheduled")
    ap.add_argument("--retention-days", type=int, default=None)
    args = ap.parse_args(argv)

    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    needs = CHURN_CLUSTER_NEEDS if args.full_cluster else scheduled_data_needs(target)

    print(f"=== harvest-prime {target.isoformat()} — {len(needs)} need(s) "
          f"({'full-cluster' if args.full_cluster else 'scheduled today'}) ===")
    if args.dry_run:
        for n in needs:
            print(f"  · {n.label or n.view_url}")
        print("(dry-run — nothing pulled)")
        return 0

    result = harvest(target, needs, retention_days=args.retention_days)
    ok = sum(1 for e in result.entries if e.error is None)
    print(f"=== primed {ok}/{len(result.entries)} ok, "
          f"{len(result.deferred)} deferred, {len(result.pruned)} pruned ===")
    # Non-zero only if NOTHING harvested (a total failure the orchestrator should
    # see); partial success is fine — cache-reading reports fall back to live for
    # any missing view.
    return 0 if ok > 0 or not result.entries else 1


if __name__ == "__main__":
    sys.exit(main())

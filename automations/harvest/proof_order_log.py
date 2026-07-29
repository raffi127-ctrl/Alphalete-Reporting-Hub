"""Proof for the order-log ALLREPS harvest-once (SHADOW). Requires LIVE Tableau —
run on a machine with the warm ownerville/Tableau session (the mini / Lucy 2),
NOT the laptop.

Because all 8 office-metrics reports pull the IDENTICAL raw ALLREPS "A.Order Log"
crosstab and only differ in a Python-side owner filter, correctness reduces to a
single check: the HARVESTED raw crosstab must be byte-identical to a fresh LIVE
pull. If it is, every owner's filtered slice is identical too, so the one cached
pull can safely replace all 8 scrapes.

    python -m automations.harvest.proof_order_log        # harvest once + live pull + diff

Exit 0 iff byte-identical. This writes ONLY to the cache + a temp file; it never
touches a Sheet or posts Slack, and it does NOT flip HARVEST_MODE — it just
proves the bytes match before any canary flip.
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path


def main(argv=None) -> int:
    from automations.harvest.needs_order_log import order_log_needs
    from automations.harvest.harvester import harvest
    from automations.harvest.loader import load_harvest

    today = dt.date.today()
    need = order_log_needs(today)[0]
    print(f"=== order-log ALLREPS harvest proof {today.isoformat()} ===")
    print(f"  view: {need.view_url}")
    print(f"  sheet: {need.crosstab_sheet!r}")

    # 1) Harvest it once into the dated cache.
    result = harvest(today, [need])
    if not result.entries or result.entries[0].error is not None:
        err = result.entries[0].error if result.entries else "no entry"
        print(f"HARVEST FAILED: {err}")
        return 2
    cached = load_harvest(need, today)          # hard-fails if stale/checksum-bad
    cached_bytes = Path(cached).read_bytes()
    print(f"  harvested → {Path(cached).name} ({len(cached_bytes):,} bytes)")

    # 2) Fresh LIVE pull of the SAME url + sheet.
    from automations.shared.tableau_patchright import download_crosstab_patchright
    with tempfile.TemporaryDirectory() as td:
        live = Path(td) / "order_log_allreps_live.csv"
        download_crosstab_patchright(need.view_url, need.crosstab_sheet, live,
                                     verbose=True)
        live_bytes = Path(live).read_bytes()
    print(f"  live pull → {len(live_bytes):,} bytes")

    # 3) Diff byte-for-byte.
    if cached_bytes == live_bytes:
        print("VERDICT: IDENTICAL ✓ — the cached ALLREPS pull matches a live pull "
              "byte-for-byte; safe to serve all 8 office-metrics reports from cache.")
        return 0
    print(f"VERDICT: MISMATCH ✗ — cached {len(cached_bytes):,}B vs live "
          f"{len(live_bytes):,}B. Do NOT flip HARVEST_MODE for order_log until "
          "this is understood (a live pull captured different bytes — e.g. the "
          "extract refreshed between the two pulls).")
    return 1


if __name__ == "__main__":
    sys.exit(main())

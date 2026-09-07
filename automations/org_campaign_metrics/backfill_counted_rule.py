"""One-shot (2026-09-07): re-stamp the org Campaign Log's b2b SALES-COUNT
history under the tracker-parity counting rule (COUNTED_PRODUCTS — Carlos:
tablets/voice/video/upgrades are not sales).

Weeks WE 1/04 .. WE 9/06, every computed b2b manager, from the CACHED
backfill exports in output/org_campaign_metrics/ (b2b_backfill_*.csv);
the 8/31-9/06 week is fetched fresh on first run (needs the Tableau
session) and cached under the same naming so reruns are offline.

Re-stamped slots (order-log-derived counts only): Active Headcount, Total
Apps, Sales per Rep, Rank, the eight product-mix rows, VoIP Line Count.
Deliberately untouched: CRU/ABP/BYOD % history (eight weeks of it carries
the B2BATTSalesMetrics view's authoritative numbers), activation/churn,
nationals, manual TEAM rows, goals. The current week belongs to the daily
stamper — run `run --only b2b --write` after this for WE 9/13.

    python -m automations.org_campaign_metrics.backfill_counted_rule          # dry
    python -m automations.org_campaign_metrics.backfill_counted_rule --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

from automations.org_campaign_metrics import layout as L
from automations.org_campaign_metrics import pull_b2b as P
from automations.org_campaign_metrics import sheet as CL

OUT = Path(__file__).resolve().parents[2] / "output" / "org_campaign_metrics"

FIRST_MONDAY = dt.date(2025, 12, 29)          # WE 2026-01-04
LAST_MONDAY = dt.date(2026, 8, 31)            # WE 2026-09-06

RESTAMP_LABELS = [
    "Active Headcount on Tableau", "Total Apps", "Sales per Rep",
    "Rank on the Tracker", "New Internet Sales", "CRU Internet Sales",
    "Wireless Sales (excl. BYOD)", "BYOD Sales", "CRU BYOD Sales",
    "IRU BYOD Sales", "AIR/AWB Sales", "VoIP Line Count",
]


def _cached_files():
    """[(start, end, path)] for every cached export, widest coverage."""
    out = []
    for p in sorted(OUT.glob("b2b_backfill_*.csv")):
        m = re.match(r"b2b_backfill_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv",
                     p.name)
        if m:
            out.append((dt.date.fromisoformat(m.group(1)),
                        dt.date.fromisoformat(m.group(2)), p))
    return out


def _file_for_week(files, monday, sunday):
    for a, b, p in files:
        if a <= monday and sunday <= b:
            return p
    return None


def _fetch_missing_week(monday, sunday, log):
    """Pull one Mon-Sun window into the cache (Tableau session needed once)."""
    dest = OUT / ("b2b_backfill_%s_%s.csv" % (monday, sunday))
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    from automations.att_order_log.run import _fetch_csv
    from automations.shared.tableau_patchright import tableau_session
    log("fetching missing week %s..%s" % (monday, sunday))
    with tableau_session(verbose=False) as page:
        body = _fetch_csv(page, P.ORDERLOG_CSV % (monday, sunday), log=log)
    dest.write_bytes(body)
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    log = print

    managers = P._managers()
    for mgr in [m for m in managers if L.MANAGER_CAMPAIGN.get(m) != "b2b_att"]:
        managers.pop(mgr)
    wanted = set(managers.values())
    by_export = {v: k for k, v in managers.items()}
    slots = L.slots_by_label("b2b_att")
    restamp = {lab: slots[lab] for lab in RESTAMP_LABELS if lab in slots}

    files = _cached_files()
    values = []
    monday = FIRST_MONDAY
    while monday <= LAST_MONDAY:
        sunday = monday + dt.timedelta(days=6)
        path = _file_for_week(files, monday, sunday)
        if path is None:
            path = _fetch_missing_week(monday, sunday, log)
        per = P.orderlog_all_owner_slots(path, monday, sunday, wanted, log)
        n = 0
        for exp, named in per.items():
            mgr = by_export[exp]
            for lab, v in named.items():
                if lab in restamp:
                    values.append((mgr, sunday.isoformat(), restamp[lab], v))
                    n += 1
        log("WE %s  %-28s %2d owners, %3d tuples"
            % (sunday, path.name, len(per), n))
        monday += dt.timedelta(days=7)

    log("-- total: %d tuples across %d managers" % (len(values), len(managers)))
    if not a.write:
        for row in values[:40]:
            log("   %s" % (row,))
        log("   … dry run (pass --write to stamp)")
    from automations.funnel_board.auth import session as sheets_session
    S = sheets_session(verbose=False)
    CL.upsert_values(S, values, dry_run=not a.write, log=log)
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

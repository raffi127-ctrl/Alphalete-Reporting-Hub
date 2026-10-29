"""READ-ONLY: do these owners' reps actually log knocks in OwnerVille?

Eve 2026-10-29: Jairo's, Drew's and Omar's Lucy ECO relay their knocks grid
empty almost every day -- is that their OwnerVille (nobody dispositions), or
the ECO read? This answers it from OUR side: impersonate each office on a
Lucy, read the last week's Disposition grid under BOTH campaigns (RES AT&T 3,
NDS 1), and count reps and knocks per day.

Omar was a rep under Salik Mallick until 10/26, so Salik's office is read too,
and any of Omar's SELLING reps (from his ECO sales relay) who knock under
Salik are named -- that is where his crew's knocks would be hiding.

Prints only; no Sheet, no Slack, no text.

    python -m automations.owner_knocks_hourly.probe_ov
    python -m automations.owner_knocks_hourly.probe_ov --days 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List

OFFICES = [
    ("Jairo", "Jairo J Ruiz Busquet"),
    ("Drew", "Precision management Drew Tepper"),
    ("Omar", "Omar Mohamad"),
    ("Salik (Omar's old office)", "Salik Mallick"),
]
CAMPAIGNS = [("RES AT&T", "3"), ("NDS", "1")]


def _days(n: int) -> List[dt.date]:
    out, d = [], dt.date.today()
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() != 6:        # no Sunday knocking
            out.append(d)
    return sorted(out)


def _knocks(rows: List[Dict]) -> int:
    from automations.icd_alerts import knocks_map as KM
    return sum(KM._int(r.get("Total Knocks")) for r in rows)


def _omar_sellers(days: List[dt.date]) -> set:
    try:
        from automations.icd_sales_board import relay_read as R
        relay = R.read_all().get("omar") or {}
        return {" ".join(n.split()).lower()
                for d in days for n in (relay.get(d) or {})}
    except Exception as e:  # noqa: BLE001
        print("(Omar's sales relay unreadable: %s)" % e)
        return set()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=6)
    args = ap.parse_args(argv)
    from automations.rashad_metrics.knocks_pull import pull_offices_days

    days = _days(args.days)
    jobs, labels = [], []
    for label, name in OFFICES:
        for cname, cid in CAMPAIGNS:
            jobs.append((name, days, cid))
            labels.append((label, name, cname))
    print("days: %s .. %s" % (days[0], days[-1]))
    pulled = pull_offices_days(jobs, verbose=False, priority="normal")
    sellers = _omar_sellers(days)
    for (label, name, cname), (_n, by_day, err) in zip(labels, pulled):
        print("\n=== %s (%s) — campaign %s ===" % (label, name, cname))
        if err is not None:
            print("  PULL FAILED: %s: %s" % (type(err).__name__, str(err)[:300]))
            continue
        for d in days:
            rows = (by_day or {}).get(d) or []
            reps = [r.get("Rep") for r in rows if r.get("Rep")]
            line = "  %s %s: %d rep(s), %d knocks" % (
                d.strftime("%a"), d, len(reps), _knocks(rows))
            if reps:
                line += "  e.g. %s" % ", ".join(reps[:4])
            print(line)
        if label.startswith("Salik") and sellers:
            hit = sorted({r.get("Rep") for d in days
                          for r in ((by_day or {}).get(d) or [])
                          if " ".join(str(r.get("Rep") or "").split()).lower()
                          in sellers})
            print("  Omar's selling reps knocking HERE: %s"
                  % (", ".join(hit) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

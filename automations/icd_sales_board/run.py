"""CLI for the per-ICD campaign/metric map.

  python -m automations.icd_sales_board.run --matrix        # the whole table
  python -m automations.icd_sales_board.run --icd "Isaiah Revelle"
  python -m automations.icd_sales_board.run --campaigns     # campaign -> source
  python -m automations.icd_sales_board.run --check         # derived vs hand-kept
  python -m automations.icd_sales_board.run --refresh       # re-read the board

--check is the one that matters over time. office_metrics.offices keeps a
hand-written SECTION_OVERRIDES row per wireless-only office; this derives the
same list from what the ICD actually sells. When the two disagree, one of them
is wrong — and it should be a loud question, not a silent blank board.
"""
from __future__ import annotations

import argparse
import sys

from automations.icd_sales_board import campaigns as C
from automations.icd_sales_board import profiles as P

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _matrix() -> None:
    profs = P.load()
    print(f"{len(profs)} ICDs on the ORG Sales Board\n")
    w = f"{'ICD':<22}{'CAMPAIGNS':<30}{'SELLS':<26}{'METRICS':<9}{'FEED TODAY'}"
    print(w)
    print("-" * len(w))
    for n, p in profs.items():
        print(f"{n[:21]:<22}{','.join(p.campaigns)[:29]:<30}"
              f"{','.join(p.families)[:25]:<26}"
              f"{len(p.metrics):>2}/{len(C.METRICS):<6}"
              f"{p.channel_name or '—'}")


def _icd(name: str) -> None:
    profs = P.load()
    hits = [n for n in profs if name.lower() in n.lower()]
    if not hits:
        raise SystemExit(f"no ICD matching {name!r}. try --matrix")
    for n in hits:
        p = profs[n]
        print(f"\n=== {n} ===")
        print(f"  sells      : {', '.join(p.families) or '—'}")
        print(f"  feed today : {p.channel_name or 'none'}")
        print("\n  CAMPAIGNS")
        for k in p.campaigns:
            c = C.CAMPAIGNS[k]
            print(f"    • {c.label}  (board section '{c.section}')")
            if c.url:
                print(f"        {c.workbook} → {c.view}"
                      + (f" → {c.worksheet}" if c.worksheet else ""))
                print(f"        {c.url}")
            if c.filters:
                print(f"        filters: {c.filters}")
            if not c.is_tableau:
                print("        NOT TABLEAU — see notes")
        print("\n  METRICS THAT APPLY")
        for s in p.metrics:
            m = C.METRIC_BY_SLUG[s]
            print(f"    ✓ {m.label}")
            print(f"        {m.source}")
        if p.na_metrics:
            print("\n  N/A (do not render — they'd be blank)")
            for s in p.na_metrics:
                m = C.METRIC_BY_SLUG[s]
                print(f"    ✗ {m.label}  — needs {'/'.join(m.needs)}")


def _campaigns() -> None:
    for c in C.CAMPAIGNS.values():
        print(f"\n=== {c.label}   [board section: {c.section}]")
        print(f"  sells    : {', '.join(c.families)}")
        if c.is_tableau:
            print(f"  workbook : {c.workbook}")
            print(f"  view     : {c.view}"
                  + (f"   worksheet: {c.worksheet}" if c.worksheet else ""))
            print(f"  ICD col  : {c.owner_col}")
            print(f"  url      : {c.url}")
        else:
            print("  source   : NOT TABLEAU")
        if c.filters:
            print(f"  filters  : {c.filters}")
        if c.notes:
            print(f"  notes    : {c.notes}")


def _check() -> int:
    """Diff the DERIVED metric list against the hand-maintained overrides."""
    try:
        from automations.office_metrics import offices as _off
    except Exception as e:
        print(f"cannot import office_metrics.offices: {e}")
        return 0
    profs = P.load()
    by_key = {}
    for n, p in profs.items():
        if p.office_key:
            by_key[p.office_key] = (n, p)

    problems = 0
    print("DERIVED (from what the ICD sells) vs SECTION_OVERRIDES (hand-kept)\n")
    for key, slugs in (_off.SECTION_OVERRIDES or {}).items():
        row = by_key.get(key)
        if not row:
            print(f"  {key}: override exists but the ICD isn't matched on the "
                  f"board — name mismatch? (check the ICD Aliases sheet)")
            problems += 1
            continue
        name, p = row
        derived, kept = set(p.metrics), set(slugs)
        # the runner bundles NI+WL churn into one 'churn' slug
        if "churn" in kept:
            kept = (kept - {"churn"}) | {"churn_wl"} | (
                {"churn_ni"} if "churn_ni" in derived else set())
        only_derived, only_kept = derived - kept, kept - derived
        if not (only_derived or only_kept):
            print(f"  ✓ {key} ({name}) — agree, {len(derived)} metrics")
            continue
        problems += 1
        print(f"  ⚠ {key} ({name})")
        for s in sorted(only_derived):
            print(f"      derived-only : {s}  (sells {'/'.join(p.families)})")
        for s in sorted(only_kept):
            print(f"      override-only: {s}")
    print(f"\n{problems} disagreement(s)." if problems else "\nall agree.")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="per-ICD campaign + metric map")
    ap.add_argument("--matrix", action="store_true")
    ap.add_argument("--icd", metavar="NAME")
    ap.add_argument("--campaigns", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="re-read the live ORG board (read-only) + rewrite JSON")
    a = ap.parse_args(argv)

    if a.refresh:
        n = P.refresh_from_board()
        print(f"refreshed {len(n)} ICDs from the ORG Sales Board")
    if a.campaigns:
        _campaigns()
    if a.icd:
        _icd(a.icd)
    if a.check:
        return 0 if _check() == 0 else 1
    if a.matrix or not any([a.refresh, a.campaigns, a.icd, a.check]):
        _matrix()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Country Campaign Board — daily fill + Tuesday rollover.

  python -m automations.program_daily_summary.run --dry-run
  python -m automations.program_daily_summary.run --enable-rollover
  python -m automations.program_daily_summary.run --no-tableau      # Credico only
  python -m automations.program_daily_summary.run --today 2026-11-24 --dry-run

Each run: gather COUNTRY per-day totals for every campaign (this week AND last
week, so a Tuesday roll freezes the closing week with its final Sunday), then
board.run (roll if due, then fill), then board.verify — a campaign with nothing
for yesterday exits 1 so the orchestrator flags it (Country Sales Board rule).

Sources:
  Fios / Frontier  credico_pdf  — mail PDFs, land ~9:30am CT (sales thru yesterday)
  ATT Fiber        Tableau D2D1-PAGERV4 'Sales By ICD (ATT) (V2)' + '(LW2)',
                   summed over ALL owners (Country Sales Board's own pull)
  ATT NDS / B2B    same workbooks/worksheets as the ORG Sales Board, BASE view
                   (country), NDS = WIRELESS like the board
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console
    pass

from automations.program_daily_summary import board, credico_pdf
from automations.program_daily_summary import layout as L

OUT = Path(__file__).resolve().parents[2] / "output" / "program_daily_summary"


def _sum_owners(parsed) -> dict:
    """{owner: {'Total': {date: n}}} -> {date: country total}."""
    out = {}
    for m in parsed.values():
        for days in m.values():
            for d, n in days.items():
                out[d] = out.get(d, 0) + int(n or 0)
    return out


def _country_specs():
    """NDS + B2B = the SAME workbooks/worksheets the ORG Sales Board reads
    (Eve 2026-11-20), but the BASE view instead of the board's saved custom
    view — those are scoped to our org/captainship ('LuissCaptainship',
    'Thisweekandlast'), the base view carries every owner in the country."""
    import dataclasses
    from automations.org_sales_board import section_pull as sp
    nds = dataclasses.replace(
        sp.NDS_SPEC,
        view_url=sp._BASE + "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep",
        total_label="", include_products=("WIRELESS",),   # = the board's metric
        out_name="country_campaign_nds.csv")
    b2b = dataclasses.replace(
        sp.B2B_SPEC,
        view_url=sp._BASE + "ATTTRACKER-B2B/D2D1-PAGERV3",
        out_name="country_campaign_b2b.csv")
    return {"ATT NDS": nds, "B2B": b2b}


def tableau_days(today: dt.date, logfn=print) -> dict:
    """{campaign: {date: n}} for the AT&T campaigns. Fiber reads this week +
    last week; NDS/B2B read the reporting week only (see below)."""
    import dataclasses
    from automations.shared.tableau_patchright import tableau_session
    from automations.country_sales_board import pull as fiber
    from automations.org_sales_board import section_pull as sp
    got = {}
    with tableau_session(verbose=False) as page:
        days = {}
        for lw in (True, False):
            try:
                days.update(_sum_owners(fiber.pull_icd_days(
                    page, OUT, last_week=lw, logfn=logfn)))
            except fiber.NoDataYet as e:
                logfn(f"  ATT Fiber {'LW' if lw else 'this week'}: {e}")
        got["ATT Fiber"] = days
        for camp, spec in _country_specs().items():
            days = {}
            # ONE pull, pinned to the REPORTING week (Tuesday-rolling): on a
            # Monday that is the closing week, so Sunday lands before Tuesday's
            # roll freezes it. A last-week pin on these BASE views renders the
            # worksheet empty (Tableau drops it from the Crosstab dialog —
            # verified on Lucy 1 2026-11-20), so there is no second pull.
            for back in (0,):
                when = today - dt.timedelta(days=back)
                s = dataclasses.replace(
                    spec, out_name=spec.out_name.replace(".csv", f"_{back}.csv"))
                try:
                    path = sp.pull_section_byday(s, OUT, page, logfn=logfn,
                                                 today=when)
                    parsed = sp.parse_byday(s, path, when)
                except Exception as e:  # noqa: BLE001 — one campaign never sinks the rest
                    logfn(f"  {camp} ({'LW' if back else 'this week'}) "
                          f"FAILED: {type(e).__name__}: {str(e)[:200]}")
                    continue
                owners = len(parsed)
                d = _sum_owners(parsed)
                logfn(f"  {camp} {'LW' if back else 'this week'}: {owners} "
                      f"owners, " + ", ".join(f"{k:%a %m/%d}={v}"
                                               for k, v in sorted(d.items())))
                days.update(d)
            if days:
                got[camp] = days
    for camp, d in got.items():
        logfn(f"  {camp}: " + ", ".join(f"{k:%m/%d}={v}" for k, v in sorted(d.items())))
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--enable-rollover", action="store_true")
    ap.add_argument("--no-tableau", action="store_true",
                    help="skip the AT&T pulls (no Tableau session here)")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing")
    ap.add_argument("--backfill-last-week", action="store_true",
                    help="also add LAST week to the history for every campaign "
                         "whose full week came back and isn't stored yet")
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()

    data = {}
    with tempfile.TemporaryDirectory() as tmp:
        for prog, days in credico_pdf.country_days(tmp).items():
            if days:
                data[prog] = days
            else:
                print(f"  {prog}: no scorecard PDF in the last days")
    if not args.no_tableau:
        OUT.mkdir(parents=True, exist_ok=True)
        data.update(tableau_days(today))

    monday = board.run(data, today=today, dry_run=args.dry_run,
                       enable_rollover=args.enable_rollover)
    if args.backfill_last_week:
        board.backfill_week(monday - dt.timedelta(days=7), data,
                            dry_run=args.dry_run)
    if args.dry_run or args.no_verify:
        return 0
    expected = [c for c in L.CAMPAIGNS
                if c in data or not args.no_tableau]
    missing = [c for c in board.verify(board._tab(), monday, today)
               if c in expected]
    if missing:
        print(f"VERIFY FAILED: nothing for yesterday on the board for {missing}")
        return 1
    print("verify OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

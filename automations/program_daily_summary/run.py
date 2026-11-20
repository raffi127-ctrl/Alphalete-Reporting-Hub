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
  ATT NDS / B2B    pending — program_daily_summary_probe names the worksheets
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


def tableau_days(logfn=print) -> dict:
    """{campaign: {date: n}} for the AT&T campaigns, this week + last week."""
    from automations.shared.tableau_patchright import tableau_session
    from automations.country_sales_board import pull as fiber
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
        # ATT NDS / B2B: added once the probe names their worksheets.
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--enable-rollover", action="store_true")
    ap.add_argument("--no-tableau", action="store_true",
                    help="skip the AT&T pulls (no Tableau session here)")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing")
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
        data.update(tableau_days())

    monday = board.run(data, today=today, dry_run=args.dry_run,
                       enable_rollover=args.enable_rollover)
    if args.dry_run or args.no_verify:
        return 0
    expected = [c for c in L.CAMPAIGNS
                if c in data or not args.no_tableau]
    missing = [c for c in board.verify(board._tab(), monday, today)
               if c in expected and c in ("Fios", "Frontier", "ATT Fiber")]
    if missing:
        print(f"VERIFY FAILED: nothing for yesterday on the board for {missing}")
        return 1
    print("verify OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""DD Boxes driver — fills the Due-Diligence-style rep boxes on the ICD tabs.

Auto-detects the boxes, so adding one to another tab is a template-side change
with no code update. Runs as a last step of the OPT phase, next to
production_breakdown and team_breakdowns.

    # preview, writes nothing (uses today's product crosstab)
    python -m automations.dd_boxes.run --dry-run

    # one tab only
    python -m automations.dd_boxes.run --dry-run --only "Starr Rodenhurst"

    # for real
    python -m automations.dd_boxes.run
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.recruiting_report import fill as rfill
from automations.recruiting_report import opt_phase
from . import fill as dbfill
from .pull import Sources, most_recent_sunday

# Non-ICD tabs — same list the team breakdowns use.
from automations.team_breakdowns.run import NON_ICD_TAB_TITLES

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "dd_boxes"


def run_dd_boxes(we: dt.date = None, dry_run: bool = False, only: str = None,
                 page=None, skip_download: bool = False, verbose: bool = False,
                 backfill: int = 0, logfn=print) -> dict:
    we = we or most_recent_sunday()
    product = Path(opt_phase.PRODUCT_SALES_PATH)
    if not product.exists():
        logfn(f"DD boxes: no product crosstab at {product} — skip")
        return {"filled": 0, "status": "NO_CROSSTAB"}

    logfn(f"DD boxes: WE {we}; product crosstab {product.name}")
    src = Sources(product, OUT_DIR)
    if skip_download:
        src.use_cached(OUT_DIR)
        logfn(f"  --skip-download: reusing {sorted(src.paths)}")
    else:
        src.fetch(page=page, verbose=verbose)
    for g in src.gaps:
        logfn(f"  ! {g}")

    # --backfill: also fill PAST week columns that are still empty. A box added
    # mid-quarter starts with holes the weekly run would never revisit.
    past = []
    if backfill:
        past = [we - dt.timedelta(days=7 * i) for i in range(1, backfill + 1)]
        logfn(f"  backfill: {past[-1]} .. {past[0]} ({len(past)} weeks)")
        if not skip_download:
            src.fetch_weeks(past, page=page, verbose=verbose)
        else:
            src.fetch_weeks([], page=page)
            for sun in past:
                f = OUT_DIR / f"product_{sun.isoformat()}.csv"
                if f.exists() and f.stat().st_size:
                    src._week_csv[sun] = f
        logfn(f"  backfill crosstabs on hand: {len(src._week_csv)}")

    roster = src.roster()
    logfn(f"  roster: {len(roster)} reps across every source")

    sh = rfill.open_sheet()
    tabs = [w.title for w in sh.worksheets()
            if w.title not in NON_ICD_TAB_TITLES and not w.title.startswith("_")]
    if only:
        tabs = [t for t in tabs if t.lower() == only.lower()]
        if not tabs:
            logfn(f"  no tab named {only!r}")
            return {"filled": 0}

    filled, cells, notes_all = 0, 0, []
    for tab in tabs:
        try:
            ws = rfill._retry(sh.worksheet, tab)
            res = dbfill.fill_tab(ws, we, src, roster, dry_run=dry_run,
                                  backfill=past)
        except Exception as e:      # noqa: BLE001 — one bad tab must not kill the rest
            logfn(f"  [ERR] {tab}: {type(e).__name__}: {e}")
            continue
        if res["status"] != "OK":
            continue
        filled += 1
        cells += res["cells"]
        logfn(f"  [{'DRY' if dry_run else 'OK'}] {tab}: {res['boxes']} box(es), "
              f"{res['cells']} cells")
        for d in res["detail"]:
            logfn(f"        {d}")
        for n in res["notes"]:
            logfn(f"        ! {n}")
            notes_all.append(n)

    logfn(f"DD boxes: {filled} tab(s), {cells} cells"
          f"{' (dry run — nothing written)' if dry_run else ''}")
    return {"filled": filled, "cells": cells, "notes": notes_all,
            "gaps": src.gaps, "week": we.isoformat()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fill the DD-style rep boxes.")
    ap.add_argument("--dry-run", action="store_true", help="write nothing")
    ap.add_argument("--only", help="a single tab title")
    ap.add_argument("--week", help="WE Sunday, YYYY-MM-DD (default: most recent)")
    ap.add_argument("--skip-download", action="store_true",
                    help="reuse the crosstabs already in output/dd_boxes")
    ap.add_argument("--backfill", type=int, default=0, metavar="N",
                    help="also fill the N previous weeks wherever the cell is "
                         "still empty (one extra Tableau pull per week)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    we = dt.date.fromisoformat(args.week) if args.week else None
    res = run_dd_boxes(we=we, dry_run=args.dry_run, only=args.only,
                       skip_download=args.skip_download, verbose=args.verbose,
                       backfill=args.backfill)
    return 0 if res.get("filled") is not None else 1


if __name__ == "__main__":
    sys.exit(main())

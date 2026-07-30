"""Due Diligence CLI.

Preview one rep:
    python -m automations.due_diligence.run --rep "Miguel Camarena"

Poll the request channel once (preview — prints replies, no post, no write):
    python -m automations.due_diligence.run --once

Go live (post replies to the channel + fill the Sheet):
    python -m automations.due_diligence.run --once --live --write

Loop locally:
    python -m automations.due_diligence.run --loop 60 --live --write
"""
from __future__ import annotations

import argparse
import sys

from . import config as C
from . import format_slack
from . import fill as dd_fill
from .pull import gather_rep_dd


def _one_rep(rep: str, icd: str, *, write: bool, verbose: bool) -> int:
    dd = gather_rep_dd(rep, icd=icd, verbose=verbose)
    print(format_slack.render(dd))
    print(f"\n--- Sheet block (preview) --- tab: {dd_fill.target_tab_name(dd) or '(no ICD given)'}")
    res = dd_fill.write_rep_block(dd, dry_run=not write)
    if res.get("dry_run"):
        for row in res["rows"]:
            print("  " + " | ".join(str(c) for c in row))
        print("  (preview — nothing written; pass --write to log to the ICD tab)")
    elif res.get("wrote"):
        print(f"  wrote {res['rows_written']} rows to '{res['tab']}' {res['range']}")
    else:
        print(f"  NOT written: {res.get('error')}")
    return 0 if dd.found else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Due Diligence per-rep report")
    ap.add_argument("--rep", help="pull one rep and print (preview)")
    ap.add_argument("--icd", default="", help="the rep's ICD/owner (routes the tab)")
    ap.add_argument("--once", action="store_true",
                    help="poll the request channel once")
    ap.add_argument("--loop", type=int, metavar="SECONDS",
                    help="poll the channel forever every N seconds (local testing)")
    ap.add_argument("--live", action="store_true",
                    help="actually POST replies to Slack (default: print only)")
    ap.add_argument("--write", action="store_true",
                    help="actually WRITE the DD tab (default: preview only)")
    ap.add_argument("--harvest", action="store_true",
                    help="nightly: pull the shared crosstabs into today's cache "
                         "so /dd is instant")
    ap.add_argument("--first-sale-probe", action="store_true",
                    help="how far back the order history reaches (a few pulls)")
    ap.add_argument("--first-sale-backfill", action="store_true",
                    help="one-time: walk all history in monthly chunks and build "
                         "the rep -> first-sale-date map (resumable)")
    ap.add_argument("--first-sale-start", default="",
                    help="YYYY-MM-DD floor for --first-sale-backfill")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.first_sale_probe:
        import json
        from . import first_sale as fs
        print(json.dumps(fs.probe(verbose=args.verbose), indent=2, default=str))
        return 0

    if args.first_sale_backfill:
        import datetime as _dt
        from . import first_sale as fs
        start = _dt.date.fromisoformat(args.first_sale_start) if args.first_sale_start else None
        m = fs.backfill(start=start, verbose=args.verbose)
        if not args.write:
            print(f"  {len(m):,} rep(s) mapped — preview only, pass --write to "
                  f"save them to the '{fs.SHEET_TAB}' tab")
            return 0
        n = fs.save_map(m)
        print(f"  wrote {n:,} rep(s) to the '{fs.SHEET_TAB}' tab")
        return 0

    if args.harvest:
        from .pull import harvest_dd
        out = harvest_dd(verbose=args.verbose)
        print(f"harvest -> {out['dir']} complete={out['complete']}"
              + (f" gaps={out['gaps']}" if out.get("gaps") else ""))
        return 0 if out["complete"] else 1

    if args.rep:
        return _one_rep(args.rep, args.icd, write=args.write, verbose=args.verbose)

    from . import watch
    if args.loop:
        watch.watch_loop(args.loop, post=args.live, write_sheet=args.write,
                         verbose=args.verbose)
        return 0
    if args.once:
        out = watch.poll_once(post=args.live, write_sheet=args.write,
                              verbose=args.verbose)
        print(f"handled {out.get('handled', 0)} request(s)")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

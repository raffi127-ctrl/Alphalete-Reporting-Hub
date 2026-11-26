"""Captainship Penetration - daily ongoing penetration box per fiber captainship.

Raf's Loom 11/26 + Eve: every day, each fiber captainship gets today's ONGOING
(cumulative) fiber lead penetration per owner - captain's own office left out -
written as a new column on its tab (same treatment as the activation / churn
boxes), and the captainship email shows the last 7 days.

    python -m automations.captainship_penetration.run              # all captains
    python -m automations.captainship_penetration.run --only wayne --dry-run
    python -m automations.captainship_penetration.run --csv crosstab.csv

One Tableau download serves every captain. Nothing is written if the crosstab
looks filtered (fewer than MIN_OWNERS owners) or a captain can't be matched -
that captain fails loudly, the rest still fill.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.captainship_penetration import core, fill

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/FiberLeadPerformance?:iid=1")
WORKSHEET = "Office New Fiber Lead Penetration By Zip"

TITLES = {k: f"{v} - Captainship Penetration"
          for k, v in core.CAPTAIN_OWNER.items()}


def _download() -> str:
    from automations.shared.tableau_patchright import download_crosstab_patchright
    with tempfile.TemporaryDirectory(prefix="cap_pen_") as tmp:
        p = download_crosstab_patchright(VIEW_URL, WORKSHEET,
                                         Path(tmp) / "by_zip.csv")
        return core.decode(Path(p).read_bytes())


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                               line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="captainship_penetration")
    ap.add_argument("--only", default=None,
                    help="Comma-separated captain keys "
                         f"({', '.join(core.CAPTAIN_OWNER)}). Default: all.")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    ap.add_argument("--csv", default=None, help="Use this crosstab file "
                    "instead of downloading from Tableau.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read + print, write nothing.")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    keys = ([k.strip() for k in args.only.split(",")] if args.only
            else list(core.CAPTAIN_OWNER))
    bad = [k for k in keys if k not in core.CAPTAIN_OWNER]
    if bad:
        print(f"unknown captain(s): {bad}")
        return 2
    print(f"=== Captainship Penetration — {today} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")

    text = (core.decode(Path(args.csv).read_bytes()) if args.csv
            else _download())
    if not args.csv:
        keep = Path("output") / "captainship_penetration" / f"crosstab_{today}.csv"
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_text(text, encoding="utf-8")
        print(f"  crosstab saved: {keep}")
    owners = core.parse_owners(text)
    print(f"  crosstab: {len(owners)} owners")
    if len(owners) < core.MIN_OWNERS:
        print(f"  !! only {len(owners)} owner(s) — a Tableau filter is stuck; "
              f"nothing written")
        return 1

    failed = []
    for k in keys:
        try:
            data = core.captainship(k, owners)
            print(f"\n--- {k}: {data['email']} → {len(data['owners'])} owners "
                  f"(minus {core.CAPTAIN_OWNER[k]}), avg {data['avg']}")
            ws, created = fill.ensure_tab(k, TITLES[k], dry_run=args.dry_run)
            if ws is None:          # dry-run on a tab that doesn't exist yet
                print(f"  (dry-run) owners: {data['owners']}")
                continue
            fill.write_day(ws, today, data, dry_run=args.dry_run)
            if not args.dry_run:
                fill.style(ws, k)
        except Exception as e:  # noqa: BLE001 — one captain must not stop the rest
            failed.append(k)
            print(f"  ✗ {k}: {type(e).__name__}: {e}")
    print(f"\n=== done: {len(keys) - len(failed)}/{len(keys)} ok"
          f"{' — FAILED: ' + ', '.join(failed) if failed else ''} ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Run the Carlos PP backfill scoped to ONLY week-ending 5/31, on the mini.

output/pp_backfill.py isn't a package module (can't `python -m` it), so this
thin wrapper importlib-loads it, narrows its PLAN to just (5/31, dropdown), and
runs it — download + DRY-RUN preview by default (no Sheet write), or --write to
fill once 5/31 is confirmed. Scoping to 5/31 is deliberate: the PLAN's 6/7 entry
pins to the dashboard's "Last Week" default, which has since moved off 6/7, so a
full re-run would mis-pull that column.

    lucy rerun carlos_pp_531                    # download + preview (safe)
    (then flip base_args to --write --skip-download to fill from the cached pull)

The verdict lands in `lucy status`: whether 5/31 was selectable + rows pulled.
Temporary — remove once 5/31 is filled (or re-confirmed still blocked).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WE = dt.date(2026, 5, 31)


def _load_pp_backfill():
    path = REPO / "output" / "pp_backfill.py"
    spec = importlib.util.spec_from_file_location("pp_backfill", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # runs top-level imports + PLAN, NOT __main__
    return mod


def main() -> int:
    write = "--write" in sys.argv
    skip_dl = "--skip-download" in sys.argv
    mod = _load_pp_backfill()
    # Narrow to ONLY 5/31 so we never touch the (now-stale) 6/7 "Last Week" entry.
    mod.PLAN = [(WE, True)]
    mod.WEEKS = [w for w, _ in mod.PLAN]
    try:
        if not skip_dl:
            mod.download_all()
        csv531 = mod.csv_for(WE)
        n = (sum(1 for _ in open(csv531, encoding="utf-16")) - 1) if csv531.exists() else 0
        mod.apply_all(write=write)
    except Exception as e:  # noqa: BLE001 — report failure as the verdict
        print(f"PP531 VERDICT: ❌ 5/31 pull FAILED (likely still not selectable "
              f"in the Time Frame dropdown) — {type(e).__name__}: {str(e)[:130]}")
        return 1
    print(f"PP531 VERDICT: ✓ 5/31 {'WROTE to Sheet' if write else 'previewed (dry-run)'} "
          f"— {n} rep row(s) pulled from the 5/31 view")
    return 0


if __name__ == "__main__":
    sys.exit(main())

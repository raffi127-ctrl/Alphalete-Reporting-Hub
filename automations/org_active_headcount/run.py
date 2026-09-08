"""Active Headcount Alphalete Org Board — the weekly run.

ORDER MATTERS: roll first, then fill. The roll freezes the week that just closed
out of `C` and into `F`; the fill then writes the new week into the `C` it just
emptied. Filling first would overwrite the week the roll was about to save.

WHEN IT RUNS. Mondays, after `alphalete_org_focus` (the six OPT pulls) — every
number this report writes is one of theirs, so running after them means the
crosstabs are already on disk and `--skip-download` costs nothing and opens no
browser. It does NOT ride the ORG Sales Board's Tuesday rollover: this tab keeps
its own week columns and rolls them itself.

IT WRITES THE LIVE TAB, BUT ONLY WITH --apply. The build ran sandbox-first
and went to production on 2026-09-07; the default target is now the real tab
and `--sandbox` is the opt-in for trying a change first. DRY-RUN is still the
default, so a bare run prints its plan and touches nothing.

ONE DEAD CAMPAIGN DOES NOT COST THE OTHER SIX THEIR WEEK. A pull that fails is
reported and its box is left untouched — not zeroed — and the run still writes
everything it did get. It exits 0 with a warning rather than failing the card,
because a blank box for one campaign is a smaller problem than six stale ones
[[feedback_dead-source-pings-not-fails-the-card]].

    python -m automations.org_active_headcount.run                    # dry-run
    python -m automations.org_active_headcount.run --skip-download    # reuse cached crosstabs
    python -m automations.org_active_headcount.run --apply            # writes the live tab
    python -m automations.org_active_headcount.run --apply --sandbox  # a copy instead
    python -m automations.org_active_headcount.run --only "B2B" --only BOX
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback

from automations.org_active_headcount import fill, pull, rollover, sort
from automations.org_active_headcount import sources as src

REPORT_ID = "org_active_headcount"

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass


def run(*, apply_changes: bool = False, live_tab: bool = True,
        skip_download: bool = False, only=None, today: dt.date | None = None,
        skip_roll: bool = False, logfn=print) -> dict:
    mode = "APPLY" if apply_changes else "DRY-RUN"
    tab = "LIVE tab" if live_tab else "SANDBOX tab"
    logfn(f"Active Headcount Org Board - {tab} - {mode}")

    rolled = {"rolls": 0}
    if not skip_roll:
        logfn("\n== rollover ==")
        rolled = rollover.run(apply_changes=apply_changes, live_tab=live_tab,
                              today=today, logfn=logfn)

    logfn("\n== pull ==")
    counts, errors = pull.collect(skip_download=skip_download, only=only,
                                  logfn=logfn)

    logfn("\n== fill ==")
    filled = fill.run(counts=counts, apply_changes=apply_changes,
                      live_tab=live_tab, logfn=logfn)

    # Order LAST: the boxes rank on the number the fill just wrote, so the sort
    # has to run after it. Eve, 2026-09-07 — descending by This Week, with each
    # ICD's history travelling with them.
    logfn("\n== sort ==")
    sort.run(apply_changes=apply_changes, live_tab=live_tab, logfn=logfn)

    logfn("\n== summary ==")
    for c in src.CAMPAIGNS:
        if only and c.box not in only:
            continue
        if c.box in errors:
            logfn(f"  {c.box:18s} SKIPPED - {errors[c.box]}")
        else:
            logfn(f"  {c.box:18s} {len(counts.get(c.box, {}))} ICD(s) in source")
    if errors:
        logfn(f"\nWARNING: {len(errors)} campaign(s) had no data and were left "
              f"untouched (not zeroed): {', '.join(errors)}")
    return {"rolls": rolled.get("rolls", 0), "errors": errors, **filled}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write to the Sheet")
    ap.add_argument("--sandbox", action="store_true",
                    help="target the sandbox copy instead of the live tab")
    ap.add_argument("--skip-download", action="store_true",
                    help="re-parse the crosstabs already on disk (no browser)")
    ap.add_argument("--only", action="append",
                    help="fill only this campaign box (repeatable)")
    ap.add_argument("--skip-roll", action="store_true",
                    help="don't roll the week, just fill C")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD")
    a = ap.parse_args()
    today = dt.datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else None
    try:
        res = run(apply_changes=a.apply, live_tab=not a.sandbox,
                  skip_download=a.skip_download, only=a.only, today=today,
                  skip_roll=a.skip_roll)
    except Exception:                                              # noqa: BLE001
        traceback.print_exc()
        return 1
    return 0 if res["planned"] or not res["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

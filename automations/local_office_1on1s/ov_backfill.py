#!/usr/bin/env python3
"""Backfill Raf's office knock weeks from OwnerVille into the shared cache.

    python -m automations.local_office_1on1s.ov_backfill --weeks 9
    python -m automations.local_office_1on1s.ov_backfill --saturday 2026-08-01

MUST RUN ON A MACHINE THAT HOLDS AN OWNERVILLE SESSION — the mini or a Lucy
box, via `lucy`. On a laptop `.ownerville_storage_state.json` only ages (it was
15 days stale on Megan's Mac, 2026-09-28) and tableau_patchright says so in as
many words: "reseeding it by hand is not the fix: run browser reports through
`lucy` on the mini instead." [[feedback_machines_never_depend_on_each_other]]

WHY IT EXISTS. The Local Office 1on1s knocking block has 13 rows. The sales
board answers 9 of them, but only from ~WE 9.6 — 'Sales Board WE 8.2' / '8.16'
/ '8.30' carry no TK and no Talk-To's columns at all — and it can never answer
the four that are TIMES (Mon-Fri AVG First/Last Knock, Saturday First/Last),
because the board records counts. OwnerVille has every one, per rep per day.
Megan, 2026-09-28: "yes, do the ov pulls to get 100% correct data."

READ-ONLY AND IDEMPOTENT. It writes nothing but the week cache: no Sheet, no
Slack, no email. A week already cached at the current schema is skipped, so
re-running costs nothing. (The one cache file on Megan's Mac was schema 5
against the code's 7 — an old-schema entry is a miss, by design, and re-pulls.)

COST. `pull_office_week` is six single-day Disposition pulls plus six Time
Tracker calls per week, deliberately: the ranged view's First/Last Knock are
the window's first and most recent timestamps, not averages, so only a per-day
loop yields a true daily average. Budget ~12 round trips per week.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

REPORT_ID = "local_1on1s_knock_backfill"


def last_completed_saturday(today: dt.date) -> dt.date:
    """The most recent Saturday that has already ended."""
    return today - dt.timedelta(days=(today.weekday() - 5) % 7 or 7)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=9,
                    help="how many completed weeks back to pull")
    ap.add_argument("--saturday", action="append", dest="sats",
                    help="pull one specific week-ending Saturday (repeatable)")
    ap.add_argument("--force", action="store_true",
                    help="re-pull even when the week is already cached")
    a = ap.parse_args(argv)

    from automations.focus_office_att.aliases import load_aliases
    from automations.shared import knock_week_cache as KC
    from automations.shared.tableau_patchright import ownerville_session
    from automations.weekly_knock_dispositions import offices as OFF, pull as P
    from automations.weekly_knock_dispositions.run import PROFILE_DIR

    if a.sats:
        sats = [dt.date.fromisoformat(s) for s in a.sats]
    else:
        last = last_completed_saturday(dt.date.today())
        sats = [last - dt.timedelta(weeks=i) for i in range(a.weeks - 1, -1, -1)]

    aliases = load_aliases()
    office = OFF.RAF["name"]

    todo = []
    for sat in sats:
        if not a.force and KC.get(office, sat, aliases=aliases):
            print(f"  WE {sat:%-m/%-d}: already cached — skipped", flush=True)
            continue
        todo.append(sat)
    if not todo:
        print("nothing to pull — every week is cached", flush=True)
        return 0

    print(f"pulling {len(todo)} week(s) for {office}: "
          f"{', '.join(f'{s:%-m/%-d}' for s in todo)}", flush=True)

    ok, failed = [], []
    with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
        for sat in todo:
            monday = sat - dt.timedelta(days=5)
            try:
                rows, cols = P.pull_office_week(page, OFF.RAF, aliases,
                                                monday, sat, verbose=True)
            except Exception as e:                      # one week must not kill the rest
                print(f"  WE {sat:%-m/%-d}: FAILED — {type(e).__name__}: {e}",
                      flush=True)
                failed.append(sat)
                continue
            if not rows:
                # An empty week is usually a failed pull, not an empty week —
                # caching it would freeze the hole in. knock_week_cache.put
                # refuses an empty result for the same reason.
                print(f"  WE {sat:%-m/%-d}: EMPTY — not cached", flush=True)
                failed.append(sat)
                continue
            KC.put(office, sat, rows, cols, aliases=aliases)
            print(f"  WE {sat:%-m/%-d}: {len(rows)} reps cached", flush=True)
            ok.append(sat)

    print(f"\ncached {len(ok)}/{len(todo)} week(s)"
          + (f"; FAILED: {', '.join(f'{s:%-m/%-d}' for s in failed)}" if failed else ""),
          flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

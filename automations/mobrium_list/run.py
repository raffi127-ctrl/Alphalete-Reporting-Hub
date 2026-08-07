"""Mobrium List — weekly upkeep. Fridays, 10:00 Central.

Keeps the 'Mobrium List' tab of 'All in One Local Office - Raf' current:

  1. REMOVE the reps who are gone. Terminated per the 'Terminated Reps' tab in
     the same workbook and per this week's SALES BOARD. Two vetoes: a tracker
     note of FFP keeps them (Eve's rule), and so does a live OwnerVille roster
     entry, which means they were rehired.
  2. ADD the week's new starts from the board's 'New Starts/Raf' box, with
     their Email and Phone read out of OwnerVille's Sales Reps page (p=20).
     The board's own email column is used only for people OwnerVille has never
     heard of, and only when the address plausibly belongs to them — that
     column drifts out of step with its names. See board.py.

New people are INSERTED in first-name order, not appended: the tab is sorted
and an append would break it visibly.

Dated in CENTRAL time, not the machine clock — this is a Texas office and the
mini and Eve's box are in different zones.
[[project_central-time-for-texas-reports]]

A new 'Sales Board WE <m>.<d>' tab is made by hand every MONDAY; the week is
picked by date, so a Friday run always reads the current one.

    python -m automations.mobrium_list.run                 # preview, writes nothing
    python -m automations.mobrium_list.run --sandbox        # for real, on a copy of the tab
    python -m automations.mobrium_list.run --fresh-sandbox  # re-copy the tab first
    python -m automations.mobrium_list.run --real --i-mean-it   # the real tab
    python -m automations.mobrium_list.run --date 2026-08-07    # run as of a past date

PREVIEW IS THE DEFAULT and both flags are needed to touch the real tab, because
this is the only module in the repo that DELETES rows somebody maintains by
hand. There is no undo — the run writes the before-state to output/ first.

Exit 0 = ran (whether or not anything changed). Exit 1 = a source or the write
failed, i.e. the list may be stale.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from automations.mobrium_list import board as mboard
from automations.mobrium_list import ownerville as ov
from automations.mobrium_list import plan as mplan
from automations.mobrium_list import sheet as msheet
from automations.mobrium_list import terminated as mterm

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                               # noqa: BLE001
    pass

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:                                               # noqa: BLE001
    CENTRAL = None

OUT_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "mobrium_list"


def today_central() -> dt.date:
    return (dt.datetime.now(CENTRAL) if CENTRAL else dt.datetime.now()).date()


def _snapshot(entries, tab: str, today: dt.date) -> Path:
    """Write the tab's current contents to output/ before changing anything.

    Deleting a row is the one thing here with no undo, so the before-state is
    always on disk — including on a preview run, where it costs nothing and
    means a later 'what did it look like?' is answerable.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"before-{today.isoformat()}-{tab.replace(' ', '_')}.json"
    path.write_text(json.dumps(
        [{"row": e.row, "first": e.first, "last": e.last,
          "email": e.email, "phone": e.phone} for e in entries],
        indent=2), encoding="utf-8")
    return path


def _report(plan: mplan.Plan, logfn=print) -> None:
    logfn("")
    logfn(f"REMOVING {len(plan.removals)}:")
    for r in plan.removals or ():
        logfn(f"   − {r.entry.full:<28} {r.why}")
    if not plan.removals:
        logfn("   (nobody)")

    if plan.kept:
        logfn("")
        logfn(f"KEEPING {len(plan.kept)} the sources call terminated:")
        for k in plan.kept:
            logfn(f"   = {k.entry.full:<28} {k.why}")

    logfn("")
    logfn(f"ADDING {len(plan.additions)}:")
    for a in plan.additions or ():
        logfn(f"   + {a.full:<28} {a.email or '(no email)':<34} "
              f"{a.phone or '(no phone)':<16} [{a.source}]")
    if not plan.additions:
        logfn("   (nobody)")

    incomplete = [a for a in plan.additions if not a.complete]
    if incomplete:
        logfn("")
        logfn(f"⚠ {len(incomplete)} added without full contact details — "
              f"OwnerVille has no record and the board's own value couldn't be "
              f"trusted to them:")
        for a in incomplete:
            missing = " + ".join(
                m for m, v in (("email", a.email), ("phone", a.phone)) if not v)
            logfn(f"     {a.full:<28} missing {missing}  "
                  f"(box row {a.new_start.row} of {a.new_start.tab!r})")

    if plan.skipped:
        logfn("")
        logfn(f"skipped {len(plan.skipped)} from the box:")
        for s in plan.skipped:
            logfn(f"     {s.new_start.name:<28} {s.why}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", action="store_true",
                    help="write to the REAL 'Mobrium List' tab (needs "
                         "--i-mean-it as well)")
    ap.add_argument("--i-mean-it", dest="i_mean_it", action="store_true",
                    help="confirm --real. Rows get DELETED; there is no undo "
                         "beyond the snapshot in output/mobrium_list/")
    ap.add_argument("--sandbox", action="store_true",
                    help="write to a DUPLICATE of the tab instead of the real one")
    ap.add_argument("--fresh-sandbox", dest="fresh_sandbox", action="store_true",
                    help="re-copy the sandbox tab from the real one first")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="run as if today were this date (backfill / testing)")
    ap.add_argument("--tab", default=None,
                    help="read a specific sales-board week tab, e.g. '8.9'")
    ap.add_argument("--headed", action="store_true",
                    help="run the OwnerVille browser visibly (debugging)")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else today_central()
    print(f"Mobrium List — {today.isoformat()} "
          f"(week ending {mboard.tboard.week_sunday(today).isoformat()})")

    if args.real and not args.i_mean_it:
        print("❌ --real deletes rows from the live tab. Add --i-mean-it if "
              "that's what you want, or use --sandbox.")
        return 1

    # 1 — the list as it stands.
    target_tab = msheet.TAB
    if args.sandbox and not args.real:
        from automations.mobrium_list import sandbox
        try:
            target_tab = sandbox.ensure(refresh=args.fresh_sandbox)
        except Exception as e:                                  # noqa: BLE001
            print(f"❌ couldn't prepare the sandbox tab: {type(e).__name__}: {e}")
            return 1
    try:
        entries, ws = msheet.read(tab=target_tab)
    except Exception as e:                                      # noqa: BLE001
        print(f"❌ couldn't read {target_tab!r}: {type(e).__name__}: {e}")
        return 1
    print(f"  {target_tab!r}: {len(entries)} people")
    snap = _snapshot(entries, target_tab, today)

    # 2 — who's gone, and who's new.
    try:
        term = mterm.load(today)
    except Exception as e:                                      # noqa: BLE001
        print(f"❌ couldn't read the terminations: {type(e).__name__}: {e}")
        return 1
    try:
        new_starts, board_tab = mboard.scan(today, tab=args.tab)
    except Exception as e:                                      # noqa: BLE001
        print(f"❌ couldn't read the SALES BOARD: {type(e).__name__}: {e}")
        return 1

    # 3 — contact details. This is the only step that needs a browser session.
    try:
        directory = ov.load(headless=not args.headed)
    except Exception as e:                                      # noqa: BLE001
        # Without OwnerVille there are no phone numbers, and removals would run
        # without the rehire veto — so we stop rather than write half the job.
        print(f"❌ couldn't read OwnerVille: {type(e).__name__}: {e}")
        return 1
    print(f"  ownerville: {len(directory)} rep record(s)")

    # 4 — decide.
    plan = mplan.build(entries, new_starts, term, directory, today)
    if plan.unsorted_tab:
        print(f"  ⚠ {target_tab!r} isn't in first-name order — appending the "
              f"new people at the bottom instead of inserting them, so nothing "
              f"gets re-sorted underneath you")
    _report(plan)

    additions = mplan.place(entries, plan)

    # 5 — write.
    dry = not (args.real or args.sandbox)
    print("")
    if dry:
        print(f"  PREVIEW — nothing written. Re-run with --sandbox (a copy of "
              f"the tab) or --real --i-mean-it (the live tab).")
    else:
        print(f"  target: {target_tab!r}"
              f"{' — the REAL tab' if args.real else ''}")
    if not plan.removals and not additions:
        print("  nothing to change.")
        print(f"  before-state: {snap}")
        print(f"  {msheet.tab_url(ws)}")
        return 0
    try:
        msheet.apply(ws, removals=[r.entry for r in plan.removals],
                     additions=additions, dry_run=dry)
    except Exception as e:                                      # noqa: BLE001
        print(f"❌ the write failed partway: {type(e).__name__}: {e}")
        print(f"   the tab's before-state is in {snap} — check the tab before "
              f"re-running, some rows may already be gone")
        return 1

    print(f"  before-state: {snap}")
    print(f"  {msheet.tab_url(ws)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

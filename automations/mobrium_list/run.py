"""Mobrium List — weekly upkeep. Fridays, 10:00 Central.

Keeps the 'Mobrium List' tab of 'All in One Local Office - Raf' current:

  1. REMOVE the reps who are gone. Terminated per the 'Terminated Reps' tab in
     the same workbook and per the last three weeks of the SALES BOARD — three,
     because a T typed after Friday's run is invisible to a weekly reader that
     only looks at the current week. Two vetoes: a tracker note of FFP keeps
     them (Eve's rule), and so does a REHIRE — which now has to be stated by an
     OwnerVille start date after the termination or by this week's board, not
     merely by an OwnerVille account nobody retired (see plan.py).
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

A --real run that exits 0 also writes output/manifests/mobrium_list.json. That
file is the PROOF of delivery shared/delivery_check looks for: without it a
clean re-run can't close its own failure ticket ("ran clean, but nothing can
confirm it DELIVERED" — 2026-09-11, closed by hand).
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

# The schedule_config key — the first spelling delivery_check.manifest_ids tries.
REPORT_ID = "mobrium_list"

# The people removals can't reach — see _alert_near.
NEAR_INCIDENT_KEY = "mobrium-near-miss"
NEAR_TITLE = "Mobrium List — people who may be gone, but whose name doesn't match"


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


def _record_delivery(note: str, *, real: bool,
                     run_ts: dt.datetime | None = None) -> None:
    """Write today's run manifest — only for the REAL tab.

    A preview or a sandbox run delivered nothing to anybody, so it must not
    leave proof that says otherwise. Only called on the exit-0 paths: a failure
    already exits 1 and the orchestrator alerts on that, so a failed manifest
    here would only ping the channel twice. Never raises — the list is already
    written by the time this runs."""
    if not real:
        return
    try:
        from automations.shared import run_manifest
        run_manifest.write_manifest(REPORT_ID, succeeded=["mobrium-list"],
                                    note=note, run_ts=run_ts)
        print(f"  manifest: {note}")
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠ couldn't write the run manifest ({type(e).__name__}: {e}) "
              f"— the list is updated, but a failure ticket won't close itself")


def near_body(plan: mplan.Plan) -> list:
    """The Slack body — English, the whole team reads that channel."""
    body = [f"• {n.entry.full} — terminated as {n.why}" for n in plan.near]
    body += [f"• {f.entry.full} — the sales board marked T and contradicted "
             f"itself ({f.why})" for f in plan.flagged]
    body.append("")
    body.append("Removals go on an EXACT name, so these stay on the Mobrium "
                "List. If it's the same person, delete the row (or fix the "
                "spelling on either tab). Nothing here gets removed on its own.")
    return body


def _alert_near(plan: mplan.Plan, *, real: bool, dry_run: bool = False) -> None:
    """Say in Slack who the run could NOT remove, every Friday it happens.

    A name that is one part away from a termination (plan.near) or a board T
    that contradicts itself (plan.flagged) is never removed — deleting the
    wrong row is the failure this module avoids. Until 2026-09-11 they were
    only printed in the run log, which nobody reads, so they stayed on the
    list for good (Charley Perez / Thais Fernández Salazar, removed by hand
    that day). Eve chose the alert over an automatic removal.

    Thread-per-problem: a clean Friday closes the open thread. Real runs only
    — a preview or sandbox didn't touch the list. Never raises."""
    if not real:
        return
    try:
        if plan.near or plan.flagged:
            from automations.day_orchestrator import notify
            notify.post_alert(NEAR_TITLE, near_body(plan), tag="mobrium_list",
                              incident=NEAR_INCIDENT_KEY, label="Mobrium List",
                              dry_run=dry_run)
            print(f"  posted {len(plan.near) + len(plan.flagged)} name(s) "
                  f"to Slack for a human to decide")
        else:
            from automations.shared import incident_thread
            incident_thread.resolve_if_open(
                NEAR_INCIDENT_KEY,
                what="*Mobrium List* has no near-miss names left",
                dry_run=dry_run)
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠ couldn't post the near-miss names ({type(e).__name__}: "
              f"{e}) — they're in this log above")


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

    if plan.flagged:
        logfn("")
        logfn(f"⚠ {len(plan.flagged)} on the list the BOARD marked T and then "
              f"contradicted itself about — nothing filed them, so nothing "
              f"removes them. Tell me which it is and I'll do it next run:")
        for f in plan.flagged:
            logfn(f"   ? {f.entry.full:<28} {f.why}")

    if plan.near:
        logfn("")
        logfn(f"⚠ {len(plan.near)} on the list whose name ALMOST matches a "
              f"termination — removals go on an exact name, so these stay put "
              f"until the spelling agrees:")
        for n in plan.near:
            logfn(f"   ? {n.entry.full:<28} {n.why}")

    if plan.fills:
        logfn("")
        logfn(f"FILLING {len(plan.fills)} blank cell(s) on rows already there:")
        for f in plan.fills:
            logfn(f"   ~ {f.entry.full:<28} {f.what}: "
                  f"{f.email or ''} {f.phone or ''}".rstrip())

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


def _sort(ws, tab: str, dry: bool) -> None:
    """Re-read the tab and put it back in (first, last) order.

    Re-reading rather than reusing the entries from the top of the run is the
    point: by now rows have been deleted and inserted, so the row numbers we
    started with are stale. Best-effort — a tab that is correct but out of
    order is not worth failing a run that already wrote everything it owed.
    """
    try:
        after, _ws = msheet.read(tab=tab)
        msheet.sort_rows(ws, after, dry_run=dry, logfn=lambda m: print(f"{m}"))
    except Exception as e:                                      # noqa: BLE001
        print(f"  ⚠ couldn't re-sort {tab!r}: {type(e).__name__}: {e} — the "
              f"rows are right, the order isn't")


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
    _alert_near(plan, real=args.real and args.i_mean_it)

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
    if not plan.removals and not additions and not plan.fills:
        print("  nothing to change.")
        _sort(ws, target_tab, dry)
        print(f"  before-state: {snap}")
        print(f"  {msheet.tab_url(ws)}")
        _record_delivery("nothing to change — the list was already current",
                         real=args.real and not dry)
        return 0
    try:
        msheet.apply(ws, removals=[r.entry for r in plan.removals],
                     additions=additions,
                     fills=[(f.entry.row, f.email, f.phone) for f in plan.fills],
                     dry_run=dry)
    except Exception as e:                                      # noqa: BLE001
        print(f"❌ the write failed partway: {type(e).__name__}: {e}")
        print(f"   the tab's before-state is in {snap} — check the tab before "
              f"re-running, some rows may already be gone")
        return 1

    # The tab has to read alphabetically on both levels whatever happened above
    # — an append-fallback, or a row somebody typed in during the week.
    _sort(ws, target_tab, dry)

    print(f"  before-state: {snap}")
    print(f"  {msheet.tab_url(ws)}")
    _record_delivery(f"{len(plan.removals)} removed, {len(additions)} added, "
                     f"{len(plan.fills)} blank cell(s) filled",
                     real=args.real and not dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())

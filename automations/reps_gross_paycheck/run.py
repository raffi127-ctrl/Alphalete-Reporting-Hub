#!/usr/bin/env python3
"""Reps Gross Paycheck records — Thursday-morning fill of the per-rep tabs.

WHAT IT DOES
Every rep has a tab in the Rep Records workbook with a 'Gross Paycheck' row
across week-ending columns. This puts the right number in this week's column.

  * The money is 'Got Paid' from 'Raf PNL 2026', ONE WEEK BEHIND the column it
    lands in — what a rep collects on Thursday is what settled the week before.
    Run it Thu 8/6 and the WE 8/9 column gets the PNL's WE 8/2 figure.
  * A rep with no money that week gets '-', never a blank, so "checked, nothing
    to pay" can't be mistaken for "nobody ran the report".
  * New reps get a tab. The signal is 'Field Status' = 2nd Wk on the newest
    sales board.
  * Terminated reps lose theirs, on TWO signals: a filled 'Termination Date'
    on the sales board (NOT 'Field Status', which never says 'Terminated'), or
    a row in the PNL workbook's 'Terminated Reps' log for someone who is also
    absent from the newest board. Neither source is complete on its own — see
    plan.gone. Their cells are left alone and the tab is snapshotted to CSV
    before it goes.

  python -m automations.reps_gross_paycheck.run                 # preview, no writes
  python -m automations.reps_gross_paycheck.run --real --i-mean-it
  python -m automations.reps_gross_paycheck.run --backfill      # 6/28 -> this week
  python -m automations.reps_gross_paycheck.run --sheet-id ID   # a sandbox copy
  python -m automations.reps_gross_paycheck.run --keep-terminated
  python -m automations.reps_gross_paycheck.run --all-missing-tabs

PREVIEW BY DEFAULT. Nothing is written without --real --i-mean-it (or a
--sheet-id pointing at a duplicate workbook, where writes are free). Deleting
terminated tabs additionally needs --delete-terminated: it's the one step that
can't be undone from the sheet, and the preview lists exactly which tabs would
go so it can be read before it's allowed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from zoneinfo import ZoneInfo

from automations.recruiting_report.fill import open_by_key, _retry
from automations.reps_gross_paycheck import (alert, names, pnl as pnl_mod,
                                             plan as plan_mod, records,
                                             sales_board, tabs as tabs_mod,
                                             terminated_log as term_mod,
                                             week as wk)

CENTRAL = ZoneInfo("America/Chicago")   # [[project_central-time-for-texas-reports]]

# The share of this week's cells that must carry a real number for the run to
# be believed. Below it, the PNL almost certainly hasn't been filled in for the
# source week yet — and writing that out would put '-' in everybody's cell,
# which the next run then SKIPS as already filled, freezing a whole week of
# paychecks as dashes. The real 8/6 week ran 75% (18 of 24), so 25% is a floor
# a genuinely thin week still clears.
MIN_REAL_SHARE = 0.25
# ...but only once there are enough cells for the share to mean anything. A
# re-run leaves almost everything 'already filled', so the handful still
# planned can easily be all dashes — 0 of 1 is not evidence the PNL is empty,
# and refusing on it blocks a run that had nothing left to do anyway.
MIN_SAMPLE = 10


def _fmt(v) -> str:
    return v if isinstance(v, str) else f"${v:,.0f}"


def _print_plan(plan, verbose: bool) -> None:
    print(f"\n--- plan for WE {wk.md(plan.target)} "
          f"(weeks {', '.join(wk.md(s) for s in plan.sundays)}) ---")
    by_tab = {}
    for w in plan.writes:
        by_tab.setdefault(w.tab, []).append(w)
    for tab in sorted(by_tab):
        cells = " ".join(f"{wk.md(w.sunday)}={_fmt(w.value)}"
                         for w in sorted(by_tab[tab], key=lambda x: x.sunday))
        print(f"  {tab:34} {cells}")
        if verbose:
            for w in sorted(by_tab[tab], key=lambda x: x.sunday):
                print(f"       {w.a1:>5} <- {w.source}")

    if plan.extensions:
        print(f"\n  week columns to add ({len(plan.extensions)} tab(s)):")
        for e in plan.extensions:
            print(f"    {e.tab.title:34} +{len(e.new_weeks)} "
                  f"({', '.join(wk.md(d) for d in e.new_weeks)})"
                  f"{f' [{e.inserts} inserted]' if e.inserts else ''}")
    if plan.creates:
        print(f"\n  tabs to CREATE ({len(plan.creates)}):")
        for c in plan.creates:
            print(f"    {c.name:34} weeks from {wk.md(c.first_week)} — {c.reason}")
    if plan.deletes:
        print(f"\n  tabs to DELETE ({len(plan.deletes)}) — terminated reps:")
        for d in plan.deletes:
            print(f"    {d.tab:34} {d.reason}")
    for n in plan.notes:
        print(f"  · {n}")
    for w in plan.warnings:
        print(f"  ⚠ {w}")
    print(f"\n  {len(plan.writes)} cell(s): {plan.dashes} '-' + "
          f"{len(plan.writes) - plan.dashes} amounts | "
          f"{plan.already_filled} already filled (left alone)")


def _unmatched_report(plan, board, pnl, index, target: dt.date) -> None:
    """Reps on the board with no PNL row at all — every one of them is filling
    '-' right now.

    Split by HOW LONG they've been here, because the two cases need different
    people. A rep who started in the last few weeks simply hasn't been added to
    the PNL yet: nothing to fix here, it resolves itself. A rep who's been
    around for months and still has no PNL row is either spelled differently
    (an aliases.json row) or genuinely paid outside the PNL — and that one
    won't fix itself, so it's worth someone's eye.
    """
    NEW = dt.timedelta(days=42)          # ~6 weeks
    fresh, stale = [], []
    for tab_key, tab in sorted(index.items()):
        if tab_key in pnl.people or tab_key not in board:
            continue
        rep = board[tab_key]
        line = f"    {tab.title}"
        if rep.start and target - rep.start <= NEW:
            fresh.append(line + f" — started {wk.md(rep.start)}")
        else:
            near = names.suggest(tab.title, pnl.people)
            stale.append(line + (f" — started "
                                 f"{wk.md(rep.start) if rep.start else '?'}"
                                 f", closest PNL name: {near or 'none'}"))
    if fresh:
        print(f"\n  {len(fresh)} rep(s) not in the PNL YET — new starts, they "
              f"fill '-' until Raf adds them (nothing to do):")
        print("\n".join(fresh))
    if stale:
        print(f"\n  {len(stale)} rep(s) on the board for a while with NO PNL "
              f"row — a spelling drift, or paid outside the PNL:")
        print("\n".join(stale))
        print("    if it's a spelling drift: python -c \"from "
              "automations.reps_gross_paycheck import names; "
              "names.save_alias('<tab name>', '<PNL name>')\"")


def main() -> int:
    ap = argparse.ArgumentParser(description="Reps Gross Paycheck records")
    ap.add_argument("--real", action="store_true",
                    help="write the production Rep Records workbook.")
    ap.add_argument("--i-mean-it", action="store_true",
                    help="required alongside --real.")
    ap.add_argument("--sheet-id", metavar="ID",
                    help="target a duplicated workbook instead (sandbox; "
                         "writes allowed without --i-mean-it).")
    ap.add_argument("--backfill", action="store_true",
                    help=f"fill every week from {wk.md(wk.BACKFILL_FROM)} "
                         "through this one, not just this one.")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="backfill floor (implies --backfill).")
    ap.add_argument("--overwrite", action="store_true",
                    help="rewrite cells that already carry something. Off by "
                         "default: a filled cell is somebody's typing.")
    ap.add_argument("--all-missing-tabs", action="store_true",
                    help="create a tab for every rep on the NEWEST sales board "
                         "who hasn't got one, not just this week's 2nd Wk "
                         "reps. For catching up; the weekly run doesn't need it.")
    ap.add_argument("--no-create", action="store_true",
                    help="don't create any tabs.")
    ap.add_argument("--delete-terminated", action="store_true",
                    help="actually delete terminated reps' tabs (snapshots "
                         "each to output/ first). Without it they're listed "
                         "and left in place.")
    ap.add_argument("--keep-terminated", action="store_true",
                    help="don't even list terminated tabs for deletion.")
    ap.add_argument("--no-alert", action="store_true",
                    help="print the Slack post instead of sending it.")
    ap.add_argument("--allow-empty-week", action="store_true",
                    help="write even when almost nothing in the PNL's source "
                         "week carries money (normally that means the PNL "
                         "isn't filled in yet, and the run refuses).")
    ap.add_argument("--today", metavar="YYYY-MM-DD", help="override today.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print the full source path behind every number.")
    args = ap.parse_args()

    if args.real and not args.i_mean_it:
        print("refusing to write the real Rep Records workbook without "
              "--i-mean-it. Preview it first (no flags), or point --sheet-id "
              "at a duplicate.")
        return 2

    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.datetime.now(CENTRAL).date())
    target = wk.target_sunday(today)
    since = (dt.date.fromisoformat(args.since) if args.since
             else wk.BACKFILL_FROM if args.backfill else target)
    sundays = wk.sundays_between(since, target)

    target_id = args.sheet_id or records.SHEET_ID
    writing = bool(args.sheet_id) or (args.real and args.i_mean_it)
    where = ("SANDBOX " + args.sheet_id if args.sheet_id
             else "PRODUCTION" if writing else "PRODUCTION (read-only)")
    print(f"=== Reps Gross Paycheck — {where} — today={today} — "
          f"filling WE {wk.md(target)} from PNL WE "
          f"{wk.md(wk.source_sunday(target))} ===")

    # ---- read all three workbooks ----
    tsh = open_by_key(target_id)
    tab_models = records.load_tabs(tsh)
    print(f"  rep tabs: {len(tab_models)}")

    board = sales_board.load(open_by_key(sales_board.SHEET_ID))
    print(f"  sales board reps: {len(board)} "
          f"({sum(1 for r in board.values() if r.terminated)} terminated)")

    pnl_book = open_by_key(pnl_mod.SHEET_ID)
    pnl = pnl_mod.load(pnl_book)
    print(f"  PNL people: {len(pnl.people)} across {len(pnl.weeks)} weeks")

    # Second opinion on who's gone. Lives in the same workbook as the PNL, so
    # it costs one extra read, and it catches the reps whose board row never
    # got a Termination Date.
    term_log = term_mod.load(pnl_book)
    print(f"  'Terminated Reps' log: {len(term_log)} people")
    for key, person in pnl.people.items():
        for sunday, vals in person.conflicts.items():
            if sunday in {wk.source_sunday(s) for s in sundays}:
                print(f"  ⚠ PNL: {person.raw} has conflicting 'Got Paid' for "
                      f"WE {wk.md(sunday)} on rows {person.rows}: {vals} — "
                      f"using {person.paid[sunday]}")

    prototype = tabs_mod.pick_prototype(tab_models)
    if prototype:
        print(f"  new-tab prototype: {prototype.title!r} "
              f"({len(prototype.weeks)} week columns)")

    plan = plan_mod.build(
        tabs=tab_models, board=board, pnl=pnl, sundays=sundays, target=target,
        term_log=term_log,
        create_new=not args.no_create,
        delete_terminated=not args.keep_terminated,
        overwrite=args.overwrite,
        only_week2=not args.all_missing_tabs,
        prototype=prototype)

    _print_plan(plan, args.verbose)
    index, _dupes = records.index_by_key(tab_models)
    _unmatched_report(plan, board, pnl, index, target)

    cells, real = plan.week_split(target)
    thin = cells >= MIN_SAMPLE and (real / cells) < MIN_REAL_SHARE
    if thin:
        print(f"\n  ⚠ only {real} of {cells} cell(s) for WE {wk.md(target)} "
              f"carry a number — 'Got Paid' for WE "
              f"{wk.md(wk.source_sunday(target))} looks like it hasn't been "
              f"filled in yet.")

    if not writing:
        if thin:
            alert.notify(target, wk.source_sunday(target), cells, real,
                         dry_run=True)
        print("\n=== preview only — nothing written. Add --real --i-mean-it "
              "(or --sheet-id <duplicate>) to apply. ===")
        return 0

    if thin and not args.allow_empty_week:
        # Refuse rather than write. A '-' now is indistinguishable from a real
        # zero next week, and the no-overwrite rule means nothing would ever
        # correct it. Fail loudly so the orchestrator raises it, and tell
        # #claudecorrections-and-requests, @-mentioning Evelyn — she's the
        # one who can get the week into the PNL.
        alert.notify(target, wk.source_sunday(target), cells, real,
                     dry_run=args.no_alert)
        print("=== REFUSING TO WRITE — re-run once the PNL has that week, or "
              "pass --allow-empty-week if the week really was that quiet. ===")
        return 1

    return apply(tsh, plan, prototype, sundays, pnl, board, term_log,
                 delete_terminated=args.delete_terminated, today=today)


def apply(spreadsheet, plan, prototype, sundays, pnl, board, term_log, *,
          delete_terminated: bool, today: dt.date) -> int:
    """Grow, create, write, then (only if allowed) delete."""
    value_writes = []

    # 1. grow the week runs that are short — structure before values, so the
    #    cells the values target exist by the time they're written.
    structure = []
    for ext in plan.extensions:
        structure += records.extension_requests(ext)
        value_writes += records.extension_header_values(ext)

    # 2. clone the prototype for new reps.
    created = []
    if plan.creates:
        if prototype is None:
            print("  ⚠ no prototype tab to clone — skipping tab creation")
        else:
            existing = len(spreadsheet.worksheets())
            structure += tabs_mod.duplicate_requests(
                prototype, [c.name for c in plan.creates], existing)
            created = [c.name for c in plan.creates]

    if structure:
        _retry(spreadsheet.batch_update, {"requests": structure})
        print(f"  applied {len(structure)} structure change(s)")

    for c in plan.creates:
        if c.name in created:
            value_writes += tabs_mod.seed_values(prototype, c.name, c.first_week)

    # 3. the numbers.
    for w in plan.writes:
        value_writes.append({"range": f"'{w.tab}'!{w.a1}", "values": [[w.value]]})

    if value_writes:
        _retry(spreadsheet.values_batch_update,
               {"valueInputOption": "USER_ENTERED", "data": value_writes})
        print(f"  wrote {len(value_writes)} range(s)")

    # 4. brand-new tabs still need their own weeks filled — they had no columns
    #    when the plan was built. Re-read just those and fill them.
    if created:
        fresh = [t for t in records.load_tabs(spreadsheet) if t.title in set(created)]
        follow = plan_mod.build(
            tabs=fresh, board=board, pnl=pnl, sundays=sundays,
            target=plan.target, term_log=term_log,
            create_new=False, delete_terminated=False,
            prototype=prototype)
        if follow.writes:
            _retry(spreadsheet.values_batch_update, {
                "valueInputOption": "USER_ENTERED",
                "data": [{"range": f"'{w.tab}'!{w.a1}", "values": [[w.value]]}
                         for w in follow.writes]})
            print(f"  filled {len(follow.writes)} cell(s) on {len(created)} new tab(s)")

    # 5. deletions last, and only when explicitly allowed.
    if plan.deletes and not delete_terminated:
        print(f"\n  ⏸ {len(plan.deletes)} terminated tab(s) NOT deleted — "
              "re-run with --delete-terminated once the list above looks right.")
    elif plan.deletes:
        saved = tabs_mod.snapshot(spreadsheet, plan.deletes,
                                  stamp=today.isoformat())
        print(f"  snapshotted {len(saved)} tab(s) to {tabs_mod.SNAPSHOT_DIR}")
        ids = list(dict.fromkeys(d.sheet_id for d in plan.deletes))
        _retry(spreadsheet.batch_update,
               {"requests": tabs_mod.delete_requests(ids)})
        print(f"  deleted {len(ids)} terminated tab(s)")

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

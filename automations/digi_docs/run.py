"""Digi Docs — send this week's new starts their OwnerVille document bundle.

    # who WOULD be sent to, and who wouldn't and why. Touches nothing.
    python -m automations.digi_docs.run

    # the two phases, separately (see PHASES below)
    python -m automations.digi_docs.run --add-only --live
    python -m automations.digi_docs.run --send-only --live

DRY RUN IS THE DEFAULT. Nothing reaches OwnerVille or the Sheet without
--live, because step 8 of this flow mails somebody a nine-document contract
bundle and cannot be undone.

PHASES (workflows/digi-docs-onboarding-quizzes.md has the full click-path).
Batched on purpose, rather than a whole add-then-send cycle per person:
  1. read this week's D2D OBCL tab, every chart, and drop who isn't starting
  2. --add-only : add every eligible rep who isn't in OwnerVille yet. Mails
     nobody, ticks nothing, safe to re-run.
  3. --send-only: generate each bundle, then tint the Digi Docs CELL. Never the
     name, never the checkbox -- a person hand-marks that.
"""
from __future__ import annotations

import argparse
import sys

from automations.digi_docs import config, roster


def _open_tab(tab_name: str = ""):
    from automations.recruiting_report.fill import open_by_key
    wb = open_by_key(config.SHEET_ID)
    ws = _bir_current_tab(wb, tab_name)
    return ws, ws.get_all_values()


def _bir_current_tab(wb, tab_name: str):
    from automations.blueink_docs import roster as _bir
    return _bir.current_tab(wb, tab_name)


def preview(tab_name: str = "") -> int:
    ws, values = _open_tab(tab_name)
    cands = roster.candidates(values, ws.title)
    send = roster.to_send(cands)
    done = roster.done_by_hand(cands)
    skipped = [c for c in cands if not c.eligible]

    print(f"\nTab: {ws.title}   ({len(cands)} people on it, all charts)")
    print(f"Bundle: {config.BUNDLE_TYPE} / {config.BUNDLE}")
    print(f"Machine: {config.MACHINE}\n")

    print(f"WOULD SEND ({len(send)}):")
    for c in send:
        col = f"col {c.digi_col}" if c.digi_col else "NO Digi Docs COLUMN"
        now = f" (cell now: {c.digi_val!r})" if c.digi_val else ""
        print(f"  • {c.name:28} row {c.row:>3}  {col}{now}")

    print(f"\nALREADY MARKED DONE BY HAND ({len(done)}):")
    for c in done:
        print(f"  ✓ {c.name:28} row {c.row:>3}")

    # Correct skips are printed here but NOT posted to Slack -- they'd bury the
    # names that need acting on. Same rule as blueink_docs.
    print(f"\nNOT STARTING ({len(skipped)}):")
    for c in skipped:
        print(f"  · {c.name:28} row {c.row:>3}  {c.skip_reason}")

    gap = roster.missing_column(cands)
    if gap:
        # Paperwork beats a marking: this is a loud warning, not a blocker.
        print(f"\n⚠ {len(gap)} eligible people have no "
              f"'{config.COL_DIGI_DOCS}' column on their chart — they would "
              f"still be SENT, just not marked:")
        for c in gap:
            print(f"    {c.name} (row {c.row})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="automations.digi_docs.run")
    ap.add_argument("--live", action="store_true",
                    help="actually act. Without it, nothing is touched.")
    ap.add_argument("--add-only", action="store_true",
                    help="phase 2 only: add missing reps to OwnerVille")
    ap.add_argument("--send-only", action="store_true",
                    help="phase 3 only: generate bundles + tint the cell")
    ap.add_argument("--both", action="store_true",
                    help="phase 2 then phase 3 — what the Monday run does. "
                         "Add everyone missing FIRST, then send, because a "
                         "rep who isn't in OwnerVille yet has nothing to "
                         "generate against.")
    ap.add_argument("--tab", default="",
                    help="a specific D2D OBCL tab (default: the newest)")
    ap.add_argument("--today", action="store_true",
                    help="only the people whose CHART is dated for today. What "
                         "both scheduled passes use — the report fires on the "
                         "date written above a chart, not on a fixed weekday.")
    ap.add_argument("--due-now", action="store_true",
                    help="send only the people whose start time is within the "
                         "next %d minutes. What the day's tick passes; without "
                         "it --send-only still means the whole cohort at once."
                         % config.SEND_LEAD_MINUTES)
    ap.add_argument("--only", default="",
                    help="work ONE person by name, not the whole cohort. For "
                         "verifying a phase against the live site without "
                         "putting 30 people through an unproven click-path.")
    ap.add_argument("--employee-id", default="",
                    help="the OwnerVille employee id to add, when two people "
                         "share a name and the dropdown shows both as the same "
                         "string. Only valid with --only.")
    args = ap.parse_args(argv)

    if not (args.add_only or args.send_only or args.both):
        return preview(args.tab)
    return _phases(args)


def _flag_terminated(people) -> None:
    """Advisory only — surface anyone on the shared terminated list BEFORE we
    mail them a contract, and never let the check itself take a run down.

    Same call and same shape as blueink_docs, which sends the other packet to
    this same cohort. The eligibility block-list already drops anyone with a
    Final Status, so this is the second net: it catches somebody terminated
    centrally whose OBCL row nobody has updated yet.
    """
    if not people:
        return
    try:
        from automations.shared import terminated_icds as ti
        _, flag = ti.alert_terminated([p.name for p in people],
                                      report_label="Digi Docs")
        if flag:
            print(f"\n{flag}")
    except Exception:                                       # noqa: BLE001
        pass


def _not_live_yet() -> str:
    """The reason this may not send yet, or "" once the date has passed.

    Downgrades a --live run to a dry one rather than failing it: the run still
    reads the tab, still says exactly who it WOULD have sent to, and still
    exits 0. A hard failure here would light the Hub card red every day until
    Monday and teach everyone to ignore it.
    """
    import datetime as _dt
    on = getattr(config, "GO_LIVE_ON", "")
    if not on:
        return ""
    try:
        go = _dt.date.fromisoformat(on)
    except ValueError:
        return ""
    today = _dt.date.today()
    if today >= go:
        return ""
    days = (go - today).days
    return (f"Digi Docs is not live until {go:%A %-d %B} "
            f"({days} day{'' if days == 1 else 's'} away) — "
            f"config.GO_LIVE_ON")


def did_work_marker_path() -> str:
    """Touched when a run actually DID something. The wrapper reads it to
    decide whether this firing is worth a row on the Hub."""
    return "output/logs/.digi-docs-did-work"


def _mark_did_work(did: bool) -> None:
    """The send pass is a tick: on a start day it fires every five minutes from
    6am to 8pm, and the great majority of those find nobody due yet. Publishing
    a Hub row for each would put ~168 rows against this one card in a day and
    green its two-pass pill within the first ten minutes, which makes the card
    say nothing at all. So the wrapper only publishes when this marker says the
    run added somebody, sent somebody, or has something to report."""
    import os
    path = did_work_marker_path()
    try:
        if did:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write("1")
        elif os.path.exists(path):
            os.remove(path)
    except Exception:                                       # noqa: BLE001
        pass


def quiet_marker_path() -> str:
    """The file the wrapper checks before starting Python at all."""
    import datetime as _dt
    return f"output/logs/.digi-docs-quiet-{_dt.date.today().isoformat()}"


def _mark_quiet_day(quiet: bool) -> None:
    """Leave (or clear) the note that says there was no work a moment ago.

    Touched fresh each time so the wrapper's age check restarts: the marker
    means "no chart was dated today as of this timestamp", never "no work
    today". A chart added at 10am has to be found, and the alternative — a
    latch set at 6am — means nobody gets their documents and the first anyone
    hears of it is the next morning.
    """
    import os
    path = quiet_marker_path()
    try:
        if quiet:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write("no chart dated today\n")
        elif os.path.exists(path):
            os.remove(path)
    except Exception:                                       # noqa: BLE001
        pass    # a missing marker only costs the next tick a sheet read


def _refuse(refused, line, dry):
    """Record a failure AND alert on it immediately.

    Megan 2026-08-26: "if anything fails it needs to alert right away." Holding
    these until the end of the pass was fine when this was one 7:45 batch; it
    is not now that a send goes 30 minutes before that person starts, because
    the delay eats the window somebody has to fix it in.
    """
    refused.append(line)
    print(f"  ⛔ {line}")
    try:
        from automations.digi_docs import slack_post
        slack_post.alert_failure(line, dry_run=dry)
    except Exception:                                       # noqa: BLE001
        pass   # an alert that fails must never take the run down with it


def _phases(args) -> int:
    """Add every rep, then send every bundle — batched, never a full cycle per
    person. The two phases live on different pages, so interleaving pays the
    expensive transition once per rep instead of once; the Show All filter is
    flipped once at the top; and if the send phase dies halfway, everyone still
    EXISTS in OwnerVille rather than the roster being half-added."""
    from automations.digi_docs import ownerville as ov

    do_add = args.add_only or args.both
    do_send = args.send_only or args.both
    ws, values = _open_tab(args.tab)
    cands = roster.candidates(values, ws.title)
    send = roster.to_send(cands)
    if args.only:
        want = args.only.strip().lower()
        send = [c for c in send if want in c.name.lower()]
        if len(send) != 1:
            print(f"⛔ --only {args.only!r} matched {len(send)} people "
                  f"({[c.name for c in send][:4]}) — expected exactly one. "
                  "Refusing: a scoped run that silently widens is the whole "
                  "thing --only exists to prevent.")
            return 1
        print(f"--only {send[0].name}")
    if getattr(args, "employee_id", "") and not args.only:
        print("⛔ --employee-id answers WHICH of two same-named people to add, "
              "so it only means anything for one person. Use it with --only.")
        return 1
    _flag_terminated(send)
    dry = not args.live
    if not dry:
        blocked = _not_live_yet()
        if blocked:
            print(f"\n⛔ {blocked}")
            print("   Running as a DRY RUN instead — nothing will be sent.")
            dry = True
    if not dry:
        from automations.digi_docs import slack_post as _sp
        _sp.clear_reported()
        _mark_did_work(False)

    # WHICH DAY IS THIS CHART FOR? Not "is it Monday" — that was only ever true
    # by coincidence, because the charts happen to be dated for Mondays (Megan
    # 2026-08-26). A chart dated for a Wednesday sends on that Wednesday with
    # nothing rescheduled. A chart with no readable date sends nobody.
    if args.today or args.due_now:
        before = len(send)
        send = roster.starting_today(send)
        print(f"charts dated today: {len(send)} of {before} on the tab")
        if not send:
            print("no chart is dated for today — nothing to do")
            _mark_quiet_day(True)
            return 0
        _mark_quiet_day(False)

    # The ADD pass takes everyone starting today, due or not: somebody starting
    # at 1pm still has to exist in OwnerVille by the time their 12:30 send comes
    # round, and adding them early costs nothing because it mails nobody.
    add_list = list(send)
    no_time = []
    if args.due_now and do_send:
        send, not_yet, no_time = roster.due_now(send)
        print(f"due now: {len(send)} · not yet: {len(not_yet)} · "
              f"no readable start time: {len(no_time)}")
        for c in not_yet:
            at = roster.send_due_at(c)
            # %-I is Mac-only; this has to run on Windows too.
            when = f"{(at.hour % 12) or 12}:{at.minute:02d}" if at else "?"
            print(f"  · {c.name}: starts {c.start_time}, sends at {when}")

    print(f"\n{ws.title}: {len(send)} to work "
          f"({'DRY RUN' if dry else 'LIVE'})\n")

    added, done, refused = [], [], []
    # Somebody whose start time we cannot read is NEVER sent on a guess, and
    # never silently dropped either -- they go in refused, so the channel names
    # them and a person can put a time in the cell.
    #
    # THIS HAS TO COME BEFORE THE EARLY RETURN BELOW. It did not, and the first
    # --due-now probe (2026-08-26) showed why: when nobody else was due the run
    # returned before recording these, so a person with a blank Start Time was
    # dropped in silence on every tick — the exact failure this report spent the
    # afternoon eliminating everywhere else.
    # A MISSING COLUMN IS ONE PROBLEM, NOT THIRTY. On 2026-08-26 the header on
    # Raf's tab was renamed from "Start Time" to "Trainer" while the 1:00 values
    # stayed underneath, and every person on it came back "no readable Start
    # Time ('')" — thirty identical lines that read like thirty blank cells
    # somebody had to chase, when the fix was one header. Say which it is.
    no_col = [c for c in no_time if not c.start_col]
    blank = [c for c in no_time if c.start_col]
    if no_col:
        _refuse(refused,
                f"the {config.COL_START_TIME!r} column is not on this tab — "
                f"{len(no_col)} people cannot be scheduled until it is back",
                dry)
    for c in blank:
        _refuse(refused, f"{c.name}: no readable Start Time "
                         f"({c.start_time!r})", dry)

    # NOTHING DUE -> DON'T OPEN A BROWSER. The send tick fires through the
    # whole day, and most of those firings have nobody due yet. Opening
    # OwnerVille to discover that would be a session churned every few minutes
    # on the same machine the headshots tick is already driving — the exact
    # collision separate profiles only half-protect against. The Sheet read
    # above is enough to know there is no work.
    if args.due_now and do_send and not send and not do_add:
        print("nobody is due yet — not opening OwnerVille")
        return _write_back(args, ws, send, added, done, refused,
                           tinted_dry=dry, do_send=do_send, fatal="")
    # `fatal` is what makes the WORST case the loudest one. Everything below
    # already survives one rep failing, but a session that won't open, or a
    # browser that dies mid-batch, threw straight past the Slack post — so the
    # run where NOBODY got their documents was the one run that told nobody.
    # Only the Hub card went red. Catch it, and fall through to the write-back
    # so the channel still hears about it.
    fatal = ""
    try:
        _work(ov, page_ctx=ov.session(headless=not dry), do_add=do_add,
              do_send=do_send, send=send, add_list=add_list, dry=dry,
              added=added, done=done, refused=refused, args_ns=args)
    except Exception as e:                          # noqa: BLE001
        fatal = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
        print(f"\n⛔ the run stopped before it finished — {fatal}")

    return _write_back(args, ws, send, added, done, refused, tinted_dry=dry,
                       do_send=do_send, fatal=fatal)


def _work(ov, *, page_ctx, do_add, do_send, send, add_list, dry,
          added, done, refused, args_ns=None):
    """The two phases. Split out only so the caller can wrap the whole thing
    in one try/except without burying the loops inside it.

    `add_list` is the whole cohort and `send` is only who is DUE — they are
    different lists now that each person's bundle goes 30 minutes before
    their own start time. Adding early is free (it mails nobody) and adding
    late is not: somebody starting at 1pm has to exist in OwnerVille before
    their 12:30 send comes round."""
    with page_ctx as page:
        if do_add:
            print("PHASE: add reps")
            for c in add_list:
                try:
                    outcome = ov.add_sales_rep(
                        page, c.name, dry_run=dry,
                        employee_id=getattr(args_ns, "employee_id", "") or None)
                    if outcome in ("added", "dry"):
                        added.append(c.name)
                except ov.Refused as e:
                    _refuse(refused, str(e), dry)

        if do_send:
            print("\nPHASE: send bundles")
            # NO top-level Show All flip. The first probe on Lucy 3 died here
            # (2026-08-25): the filter lives on View Progress, and at this point
            # the session is still on whatever page it opened, so there was
            # nothing to click. find_rep already widens to Show All per search
            # when a rep isn't in the default 3-week window -- which is the
            # proven path and the one a just-added rep needs anyway.
            for c in send:
                tab = None
                try:
                    modal, matched = ov.open_set_status(page, c.name)
                    state = ov.docs_row_state(modal)
                    if state != ov.config.DOCS_NEEDED_STATE:
                        shown = state or "unreadable"
                        done_states = getattr(ov.config, "DOCS_DONE_STATES",
                                              ("COMPLETED",))
                        if shown in done_states:
                            # Finished. Nothing owed, nothing to say.
                            print(f"  · {c.name}: skipped — Onboarding "
                                  f"Documents is {shown}")
                        else:
                            # NOT silent. Any other state — PENDING above all —
                            # used to make a person invisible: no send, no
                            # retry, no alert, on every run forever. A cohort
                            # sat in PENDING all morning while each run walked
                            # past them without a word.
                            _refuse(refused,
                                    f"{c.name}: NOT SENT and not finished — "
                                    f"Onboarding Documents is {shown}, which "
                                    f"this report does not act on. Nothing "
                                    f"will pick this person up on its own; "
                                    f"check them in OwnerVille.", dry)
                        continue
                    tab = ov.open_docs_portal(page, modal)
                    ov.generate_bundle(tab, c.name, dry_run=dry)
                    if not dry and not ov.confirm_generated(tab, c.name):
                        _refuse(refused, f"{c.name}: no success banner", dry)
                        continue
                    # THE SEND ALREADY HAPPENED (2026-08-31). generate_bundle
                    # is the send — OwnerVille mails the packet on that click —
                    # and confirm_generated above saw the success banner. So a
                    # failure from here on is NOT a failed send, and reporting
                    # it as one is what made 2026-08-31 look like twelve people
                    # got nothing when all twelve had their documents. Record
                    # them as sent, tint the cell, and raise the attestation
                    # separately for what it is: a compliance step still owed.
                    try:
                        ticked = ov.tick_attestations(page, modal, dry_run=dry)
                    except Exception as e:              # noqa: BLE001
                        # STILL TINTED (Megan 2026-08-31: "no cells are turned
                        # green for those the digi doc bundle sent to"). The
                        # success banner above is confirmation the bundle
                        # generated, and generating IS the send — so the cell
                        # has to say sent. Ticking the attestation boxes is a
                        # separate obligation that failed, and it is raised as
                        # its own alert rather than by withholding the tint,
                        # because a blank cell reads as "never sent" and sends
                        # somebody looking for a bundle that already went.
                        #
                        # The reason to distrust the banner earlier was the
                        # WRONG CAMPAIGN: reps were being added under
                        # Water/Primo, so bundles generated against the wrong
                        # campaign's list. That is fixed at the source now.
                        ticked = []
                        _refuse(refused,
                                f"{c.name}: bundle SENT (success banner "
                                f"confirmed) — but the attestation boxes were "
                                f"not ticked ({type(e).__name__}: "
                                f"{str(e).splitlines()[0][:70]}). Tick them in "
                                f"OwnerVille; this person does NOT need a "
                                f"re-send.", dry)
                    done.append((c.name, matched, ticked))
                except ov.Refused as e:
                    _refuse(refused, str(e), dry)
                except Exception as e:              # noqa: BLE001
                    # ONE rep's page must not end the batch. Run 5 (2026-08-25)
                    # died on rep 3 of 30 inside a scroll-into-view, taking the
                    # other 27 with it -- and the phase split exists precisely
                    # so a stall costs one person, not the cohort. Anything
                    # unexpected is recorded against that rep and the run goes
                    # on; the summary still exits non-zero.
                    _refuse(refused, f"{c.name}: {type(e).__name__}: "
                                     f"{str(e).splitlines()[0][:120]}", dry)
                finally:
                    # Close the portal tab on EVERY path. It only ever closed
                    # on the success path, so a batch of 30 left a tab open per
                    # refusal.
                    if tab is not None:
                        try:
                            tab.close()
                        except Exception:           # noqa: BLE001
                            pass

def _write_back(args, ws, send, added, done, refused, *, tinted_dry,
                do_send, fatal):
    """Tint the Digi Docs CELL for whoever actually got their bundle, then say
    so in Slack. Never the name, never the checkbox.

    SEND PHASE ONLY. Both of these ran unconditionally, so `--add-only --live`
    -- a phase that deliberately mails nobody and ticks nothing -- would still
    have posted "*0* new starts sent digi docs" into #rafs-office-recruiting-11280 off an empty
    `done`. Adding reps is not a send and must not announce itself as one.
    """
    dry = tinted_dry
    if not dry:
        _mark_did_work(bool(added or done or refused or fatal))
    tinted = 0
    if do_send:
        from automations.digi_docs import mark, slack_post
        sent_names = {n for n, _m, _t in done}
        tinted = mark.tint(ws, [c for c in send if c.name in sent_names],
                           dry_run=dry)
        slack_post.post(len(done), refused, done, fatal=fatal, dry_run=dry)
    else:
        print("\n(add phase — no tint, no Slack: nothing was sent)")

    print(f"\nadded {len(added)} · sent {len(done)} · tinted {tinted} · "
          f"refused {len(refused)}")
    for r in refused:
        print(f"  ⛔ {r}")
    # The audit trail the Slack post points at. Per rep, by name, with what was
    # ticked: the drug-test box asserts a completed review to AT&T, so who we
    # said it about has to be recoverable even though Slack only shows a count.
    for name, matched, ticked in done:
        as_ = f" (as {matched})" if matched and matched != name else ""
        print(f"  ✓ {name}{as_}: ticked {', '.join(ticked)}")
    return 0 if not (refused or fatal) else 1


if __name__ == "__main__":
    raise SystemExit(main())

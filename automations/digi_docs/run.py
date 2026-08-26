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
    ap.add_argument("--only", default="",
                    help="work ONE person by name, not the whole cohort. For "
                         "verifying a phase against the live site without "
                         "putting 30 people through an unproven click-path.")
    args = ap.parse_args(argv)

    if not (args.add_only or args.send_only or args.both):
        return preview(args.tab)
    return _phases(args)


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
    dry = not args.live
    print(f"\n{ws.title}: {len(send)} to work "
          f"({'DRY RUN' if dry else 'LIVE'})\n")

    added, done, refused = [], [], []
    with ov.session(headless=not dry) as page:
        if do_add:
            print("PHASE: add reps")
            for c in send:
                try:
                    outcome = ov.add_sales_rep(page, c.name, dry_run=dry)
                    if outcome in ("added", "dry"):
                        added.append(c.name)
                except ov.Refused as e:
                    refused.append(str(e))
                    print(f"  ⛔ {e}")

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
                        print(f"  · {c.name}: skipped — Onboarding Documents "
                              f"is {state or 'unreadable'}, not "
                              f"{ov.config.DOCS_NEEDED_STATE}")
                        continue
                    tab = ov.open_docs_portal(page, modal)
                    ov.generate_bundle(tab, c.name, dry_run=dry)
                    if not dry and not ov.confirm_generated(tab, c.name):
                        refused.append(f"{c.name}: no success banner")
                        continue
                    ticked = ov.tick_attestations(page, modal, dry_run=dry)
                    done.append((c.name, matched, ticked))
                except ov.Refused as e:
                    refused.append(str(e))
                    print(f"  ⛔ {e}")
                except Exception as e:              # noqa: BLE001
                    # ONE rep's page must not end the batch. Run 5 (2026-08-25)
                    # died on rep 3 of 30 inside a scroll-into-view, taking the
                    # other 27 with it -- and the phase split exists precisely
                    # so a stall costs one person, not the cohort. Anything
                    # unexpected is recorded against that rep and the run goes
                    # on; the summary still exits non-zero.
                    refused.append(f"{c.name}: {type(e).__name__}: "
                                   f"{str(e).splitlines()[0][:120]}")
                    print(f"  ⛔ {c.name}: {type(e).__name__} — "
                          f"{str(e).splitlines()[0][:120]}")
                finally:
                    # Close the portal tab on EVERY path. It only ever closed
                    # on the success path, so a batch of 30 left a tab open per
                    # refusal.
                    if tab is not None:
                        try:
                            tab.close()
                        except Exception:           # noqa: BLE001
                            pass

    # Write-back: tint the Digi Docs CELL for whoever actually got their
    # bundle. Never the name, never the checkbox.
    #
    # SEND PHASE ONLY. Both of these ran unconditionally, so `--add-only
    # --live` -- a phase that deliberately mails nobody and ticks nothing --
    # would still have posted "*0* new starts sent digi docs" into #11280 off
    # an empty `done`. Adding reps is not a send and must not announce itself
    # as one.
    tinted = 0
    if do_send:
        from automations.digi_docs import mark, slack_post
        sent_names = {n for n, _m, _t in done}
        tinted = mark.tint(ws, [c for c in send if c.name in sent_names],
                           dry_run=dry)
        slack_post.post(len(done), refused, done, dry_run=dry)
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
    return 0 if not refused else 1


if __name__ == "__main__":
    raise SystemExit(main())

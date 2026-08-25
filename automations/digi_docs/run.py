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
    ap.add_argument("--tab", default="",
                    help="a specific D2D OBCL tab (default: the newest)")
    args = ap.parse_args(argv)

    if not args.add_only and not args.send_only:
        return preview(args.tab)
    return _phases(args)


def _phases(args) -> int:
    """Add every rep, then send every bundle — batched, never a full cycle per
    person. The two phases live on different pages, so interleaving pays the
    expensive transition once per rep instead of once; the Show All filter is
    flipped once at the top; and if the send phase dies halfway, everyone still
    EXISTS in OwnerVille rather than the roster being half-added."""
    from automations.digi_docs import ownerville as ov

    ws, values = _open_tab(args.tab)
    cands = roster.candidates(values, ws.title)
    send = roster.to_send(cands)
    dry = not args.live
    print(f"\n{ws.title}: {len(send)} to work "
          f"({'DRY RUN' if dry else 'LIVE'})\n")

    added, done, refused = [], [], []
    with ov.session(headless=not dry) as page:
        if args.add_only or not args.send_only:
            print("PHASE: add reps")
            for c in send:
                try:
                    outcome = ov.add_sales_rep(page, c.name, dry_run=dry)
                    if outcome in ("added", "dry"):
                        added.append(c.name)
                except ov.Refused as e:
                    refused.append(str(e))
                    print(f"  ⛔ {e}")

        if args.send_only:
            print("\nPHASE: send bundles")
            ov._show_all(page)          # once, at the top — not per rep
            for c in send:
                try:
                    modal, matched = ov.open_set_status(page, c.name)
                    if not ov.docs_still_owed(modal):
                        print(f"  · {c.name}: already has documents")
                        continue
                    tab = ov.open_docs_portal(page, modal)
                    ov.generate_bundle(tab, c.name, dry_run=dry)
                    if not dry and not ov.confirm_generated(tab, c.name):
                        refused.append(f"{c.name}: no success banner")
                        continue
                    tab.close()
                    ticked = ov.tick_attestations(page, modal, dry_run=dry)
                    done.append((c.name, matched, ticked))
                except ov.Refused as e:
                    refused.append(str(e))
                    print(f"  ⛔ {e}")

    # Write-back: tint the Digi Docs CELL for whoever actually got their
    # bundle. Never the name, never the checkbox.
    from automations.digi_docs import mark, slack_post
    sent_names = {n for n, _m, _t in done}
    tinted = mark.tint(ws, [c for c in send if c.name in sent_names],
                       dry_run=dry)
    slack_post.post(len(done), refused, done, dry_run=dry)

    print(f"\nadded {len(added)} · sent {len(done)} · tinted {tinted} · "
          f"refused {len(refused)}")
    for r in refused:
        print(f"  ⛔ {r}")
    # Attestations are logged per rep on purpose: the drug-test box asserts a
    # completed review, and an assertion nobody can audit later is worse than
    # one nobody made.
    for name, matched, ticked in done:
        as_ = f" (as {matched})" if matched and matched != name else ""
        print(f"  ✓ {name}{as_}: attested {len(ticked)}")
    return 0 if not refused else 1


if __name__ == "__main__":
    raise SystemExit(main())

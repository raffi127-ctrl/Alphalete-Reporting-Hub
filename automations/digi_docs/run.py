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

    if not args.live:
        return preview(args.tab)

    print("The OwnerVille phases are not built yet — the click-path is in "
          "workflows/digi-docs-onboarding-quizzes.md.\n"
          "Run without --live for the roster preview.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

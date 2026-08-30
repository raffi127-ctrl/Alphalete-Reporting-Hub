"""Pull the Captainship Reports' knock boards ONCE, ahead of the build.

WHY THIS IS ITS OWN STEP (Eve, 2026-08-24). The knock sections
(knock_dispo_images) are the expensive half of the drafts by an order of
magnitude: one ownerville session, every ICD in every captainship impersonated,
scraped and un-impersonated in single file. That LOOP cannot be parallelised
WITHIN a session, because each impersonation replaces the last. Measured
2026-08-24: ~2h, twice that morning, while the rest of the day queued behind it.

NOT an account-wide limit (corrected by Megan 2026-08-24; this docstring said
"impersonation is per-account server state" until 2026-08-25 and that was
wrong). Impersonation is scoped to the ColdFusion SESSION — _exit_impersonation
returns "the server's session" to master mode, and _find_owner_and_impersonate
gets a fresh per-session rqst — and each Lucy logs into ownerville itself
(mini_control._CRED_FILES pushes ownerville-creds.json, never the storage_state
cookies). Two machines CAN impersonate on the same account at the same time,
which is what makes running this capture on Lucy 3 while Lucy 1 works ownerville
safe. This step moved to Lucy 3 on 2026-08-25 for exactly that reason.

Splitting it changes what that 2h blocks, not how long it takes:

  * `captainship_drafts` becomes a MINUTES-long job again — it finds this
    step's images through the manifest and opens no session at all. So
    rebuilding the twelve drafts after fixing a churn tab, or the 07:15
    review-link agent building them because the morning chain didn't, no
    longer costs two hours.
  * The long pull sits in the 4am wave where a long job belongs, instead of
    landing in `lucy rerun` — the same queue Eve uses for anything urgent
    (2026-08-24: a hand-queued rebuild held the ATT Focus rerun for hours).

Captures ONLY — writes no Sheet, mails nobody, posts nothing. Re-running it is
free after the first success of the day: the manifest short-circuits it, same
as it does for the build.

    python -m automations.captainship_drafts.knocks_capture
    python -m automations.captainship_drafts.knocks_capture --date 2026-08-24
    python -m automations.captainship_drafts.knocks_capture --only rafael
    python -m automations.captainship_drafts.knocks_capture --only rafael --fresh

--fresh is the "the board itself changed" switch: without it a second run the
same day short-circuits on the manifest and hands back the morning's PNGs, so a
layout change looks like it did nothing. It is the section-only twin of run.py's
--fresh-knocks — reach for this one when only the knock boards are wanted and
the rest of the captain's email should not be rebuilt at all.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.captainship_drafts import config
from automations.captainship_drafts import knock_dispo_images as KD

# The kinds this step owns. A captain with neither runs nothing here.
KNOCK_KINDS = ("daily_knocks", "knock_dispo")


def captains_for(today: dt.date, only: str | None = None,
                 only_section: str | None = None):
    """The captains whose sections TODAY include a knock board, in config
    order. Resolved through Captain.sections_on so the Sun+Mon gate on the
    weekly section is honoured here exactly as the build honours it — this
    step must never pull a section the emails won't show."""
    out = []
    for captain in config.CAPTAINS:
        if only and captain.key != only:
            continue
        kinds = {k for _h, k in captain.sections_on(today)}
        wants = tuple(k for k in KNOCK_KINDS if k in kinds)
        if only_section:
            keep = "knock_dispo" if only_section == "weekly" else "daily_knocks"
            wants = tuple(k for k in wants if k == keep)
        if wants:
            out.append((captain, wants))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="Run date (YYYY-MM-DD). Default: today. "
                                   "The boards cover the day before, same "
                                   "anchor the drafts use.")
    ap.add_argument("--only", help="One captain key (e.g. rafael).")
    ap.add_argument("--section", choices=("weekly", "daily"), default=None,
                    help="Capture only ONE of the two knock sections. "
                         "Default: whichever the day calls for (Sun/Mon = "
                         "both). Use 'weekly' when only the Mon-Sat "
                         "disposition boards changed: the completed week is "
                         "frozen and shared/knock_week_cache almost always "
                         "has it, so --section weekly --fresh re-RENDERS "
                         "without pulling ownerville at all, while the daily "
                         "half is never cached (it moves intraday) and would "
                         "impersonate every ICD again for boards nobody "
                         "asked to change.")
    ap.add_argument("--fresh", action="store_true",
                    help="Re-pull instead of reusing today's capture. The "
                         "manifest keys on the DATE, so after a board's "
                         "LAYOUT changed this is the only way a same-day "
                         "re-capture shows the new board — same switch "
                         "run.py spells --fresh-knocks. Costs the full "
                         "impersonation loop again, so use it when the "
                         "boards themselves changed, not to retry a bad "
                         "office.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    targets = captains_for(today, args.only, args.section)
    if not targets:
        print(f"no captain has a knock section on {today} — nothing to pull")
        print("=== done ===")
        return 0

    print(f"capturing knock boards for {len(targets)} captain(s) into "
          f"{config.RENDER_DIR}")
    failures = 0
    for captain, wants in targets:
        errors: dict = {}
        try:
            got = KD.capture_sections(
                captain, today, config.RENDER_DIR,
                want_daily="daily_knocks" in wants,
                want_weekly="knock_dispo" in wants,
                reuse=not args.fresh,
                errors=errors)
        except Exception as e:  # noqa: BLE001 — one captain ≠ the step
            failures += 1
            print(f"  ✗ {captain.key}: {type(e).__name__}: {str(e)[:200]}")
            continue
        # Per-owner failures are NOT step failures: they are already carried
        # into the email as that owner's note (the errors map rides the
        # manifest), and holding the whole step for one office would cost the
        # other eleven captains their boards.
        boards = sum(1 for k in wants for _lab, p in got.get(k, []) if p)
        blanks = sum(1 for k in wants for _lab, p in got.get(k, []) if not p)
        print(f"  ✓ {captain.key}: {boards} board(s)"
              + (f", {blanks} without data/failed" if blanks else ""))

    if failures:
        print(f"\n✗ {failures} captain(s) failed to capture — the build will "
              f"pull those itself")
        return 1
    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

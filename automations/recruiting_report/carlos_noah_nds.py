"""Noah Dubale's OPT block on the Carlos 1on1s sheet — filled from the NDS/ATT
views, not the B2B ones.

WHY THIS EXISTS (Eve 2026-08-17)
--------------------------------
Noah Dubale (office 23356, Oracle Acquisitions) sits on the *Carlos 1on1s -
Focus Report* roster, but he SELLS NDS. Carlos's own OPT engine
(`opt_phase_carlos`) pulls all six of its views out of `ATTTRACKER-B2B`, so
Noah simply has no source there: his recruiting half fills perfectly (AppStream
sees him) while his whole OPT block comes back empty — churn `No Data In
Tableau` x5, Total Apps 0, Personal Production `-`, headcount blank.

The first read of this was "he moved to B2B, the sources just haven't caught up,
it'll fill itself once Smart Circle moves him". Carlos corrected that on
2026-08-17: **he is still selling NDS and is staying NDS.** So nothing was ever
going to arrive on the B2B side, and waiting was the wrong plan.

The fix is not new code — it's pointing the EXISTING NDS engine at his one tab.
That engine is `automations.alphalete_org_report.opt_nds` (the one that fills the
Org's ten '<rep> - NDS' tabs), NOT `opt_phase`. opt_phase is RAF's pipeline and
its views are scoped to Raf's 'AUTOMATION PULL ICD', which the NDS reps are not
in — that is precisely why opt_nds exists, and its docstring says so. Checked
2026-08-17: Noah appears in NONE of opt_phase's 18 crosstabs but DOES appear in
opt_nds's, with all 17 of his reps. Both engines write by column-B label (never
hardcoded rows), so Carlos's shifted tab layout is fine either way.
opt_nds took two new flags for this: `--sheet-id` (fill a different
spreadsheet) and `--tab` (a tab that isn't named '<rep> - NDS').

DO NOT fold this into carlos_opt_all's step list: that wrapper is the B2B
report, and every other ICD on it is genuinely B2B. This is one NDS exception
riding on a B2B report, and keeping it a separate, separately-runnable step is
what makes that visible.

Usage:
  python -m automations.recruiting_report.carlos_noah_nds --dry-run
  python -m automations.recruiting_report.carlos_noah_nds --week 2026-08-16

Via the mini queue (needs a Tableau session, so it can't run from a laptop
without one):
  lucy rerun carlos_noah_nds --dry-run     # safe probe: writes nothing
  lucy rerun carlos_noah_nds
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# ✓ / ✗ are safe on the Windows console (cp1252 default). Same guard as run.py /
# daily_focus.py / opt_phase_carlos.py. Without it the --week guard below blew up
# with UnicodeEncodeError while printing its own refusal — on Windows, which is
# exactly where you run this by hand to check something.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# The tab on the Carlos 1on1s sheet. Must match the sheet tab EXACTLY — it is
# also his `sheet_tab` in office-mapping-carlos.json, where his office (23356)
# and as_owner live. If the tab is ever renamed, change it in BOTH places.
NOAH_TAB = "Noah Dubale"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fill Noah Dubale's OPT block on Carlos 1on1s from the "
                    "NDS/ATT views (he sells NDS, not B2B).")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD. "
                                   "Default: most recent Sunday.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Download + report what WOULD be written; no Sheet "
                         "writes. Run this first.")
    args = ap.parse_args()

    # CAPTAINSHIP is what points the shared recruiting_report modules at
    # Carlos's spreadsheet + office-mapping-carlos.json. opt_phase has no
    # --captainship flag, and schedule_config has no way to set env, so it goes
    # on the subprocess env here.
    # WHICH ENGINE — this was wrong on the first pass and it matters.
    # It ran `opt_phase --only "Noah Dubale"`, on the reasoning that opt_phase
    # is "the ATT/NDS OPT phase". opt_phase is RAF's pipeline, and its views are
    # scoped to Raf's 'AUTOMATION PULL ICD' view, which the NDS reps are not in
    # — opt_nds's own docstring says exactly that, and it's why opt_nds exists.
    # Checked 2026-08-17 against the caches of that morning's run: Noah Dubale
    # appears in NONE of opt_phase's 18 crosstabs (ICD Summary ATT + INT,
    # Metrics, Churn, Program Summary, Personal Production, wireless, fiber,
    # every captains sheet) and DOES appear in opt_nds's
    # opt_nds_personal_production.csv — all 17 of his reps, real sales.
    # So opt_phase would have written NOTHING and exited 0.
    #
    # opt_nds fills the Org's ten '<rep> - NDS' tabs; --sheet-id + --tab point
    # that same engine at his one plain-named tab on Carlos's sheet.
    # ORDER MATTERS. fill.SPREADSHEET_ID is resolved AT IMPORT TIME from
    # os.environ["CAPTAINSHIP"] (fill.py:60,119), so a dict that only reaches
    # the SUBPROCESS cannot affect it. Setting it on the subprocess env alone
    # left _fill.SPREADSHEET_ID on the DEFAULT captainship ("Raf" ->
    # 1w_KWAml…), so opt_nds went looking for Noah's tab on the wrong
    # spreadsheet and the first real dry-run came back
    # "✗ tab not found: Noah Dubale" (2026-08-17) — a wrong-sheet bug wearing a
    # missing-tab costume. Set it on THIS process, before the import.
    os.environ["CAPTAINSHIP"] = "Carlos"
    env = {**os.environ}
    from automations.recruiting_report import fill as _fill   # CAPTAINSHIP-aware
    cmd = [sys.executable, "-u", "-m", "automations.alphalete_org_report.opt_nds",
           "--sheet-id", _fill.SPREADSHEET_ID, "--tab", NOAH_TAB]
    if args.dry_run:
        cmd.append("--dry-run")
    # --week is deliberately NOT forwarded as an arbitrary date. opt_nds's
    # --backfill pins SARA to ITS OWN computed target week
    # (_current_target_week_end) and skips the no-date-control dashboards; it
    # cannot be aimed at any Sunday you like. Accepting --week 2026-07-05 and
    # quietly filling a different week would be the same lie as the stale
    # cancel.csv. So: allow it only when it names the current target week,
    # otherwise refuse and say where past weeks actually come from.
    if args.week:
        from automations.alphalete_org_report.opt_nds import (
            _current_target_week_end as _tw)
        target = _tw().isoformat()
        if args.week != target:
            print(f"✗ --week {args.week} is not the current target week "
                  f"({target}), and opt_nds cannot pin an arbitrary week: its "
                  f"NDS dashboards have no date control.\n"
                  f"   For an OLDER week, only the week-pinnable sale rows can "
                  f"be recovered — use\n"
                  f"     output/att_backfill_sales_2026-08-17.py --tab "
                  f"{NOAH_TAB!r}\n"
                  f"   Churn / activation / ranking / national averages come "
                  f"from rolling windows and do not exist for a past week.",
                  flush=True)
            return 2
        cmd.append("--backfill")

    print(f"=== Noah Dubale — NDS OPT onto Carlos 1on1s "
          f"({'DRY RUN' if args.dry_run else 'LIVE'}) ===", flush=True)
    print(f"    tab={NOAH_TAB!r}  week={args.week or 'most recent Sunday'}",
          flush=True)
    rc = subprocess.run(cmd, env=env).returncode

    if rc != 0:
        print(f"\n✗ exit {rc} — see the log above.", flush=True)
        return rc
    # A clean exit does NOT prove his numbers arrived: the engine writes what
    # the views gave it, and an ICD missing from the crosstabs yields a
    # "successful" run with an empty tab — the exact failure mode that made his
    # block look broken on the B2B side. So say it out loud rather than let a
    # green exit imply data landed.
    print("\n✓ done. CHECK THE TAB: a clean exit only means the run finished, "
          "not that Noah's numbers landed. He WAS in the NDS crosstabs as of "
          "2026-08-17 (17 reps, real sales), so blank OPT rows now mean "
          "something changed on the source side — NOT that he's the wrong "
          "campaign. That question is settled.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

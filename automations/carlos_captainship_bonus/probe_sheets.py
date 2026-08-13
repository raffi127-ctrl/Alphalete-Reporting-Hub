"""List the worksheets the Carlos bonus source view currently offers.

READ-ONLY: opens the view's Download -> Crosstab dialog, reads the worksheet
thumbnail names, and prints them. Downloads nothing, writes no Sheet.

Why this exists: when ATTTRACKER-B2B was restructured on 2026-08-13 the old
`CaptainsTeam` sheet vanished and every worksheet on the replacement view had
been renamed, so the pull failed on the FIRST worksheet and its error only
named that one. Reading the failure through `lucy logtail` doesn't help either
— the result cell caps at ~470 chars and the dialog's name list is one long
line, so it always came back truncated.

Hence: ONE NAME PER LINE, each prefixed `XTAB:` so a narrow logtail grep
returns the whole list inside the cap:

    lucy rerun probe_carlos_bonus_sheets --machine "Lucy 2"
    lucy logtail <that log> XTAB 15

Re-run this after any republish of the workbook before re-mapping
tableau_pull.SHEETS. [[project_carlos-captainship-bonus-view-dead]]
"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    from automations.carlos_captainship_bonus import tableau_pull as T
    from automations.recruiting_report.opt_phase import list_crosstab_sheets

    url = (argv or sys.argv[1:] or [T.VIEW])[0]
    print(f"probing crosstab worksheets on:\n  {url}", flush=True)
    names = list_crosstab_sheets(url, verbose=False)
    print(f"dialog offers {len(names)} worksheet(s):", flush=True)
    for n in names:
        print(f"XTAB: {n}", flush=True)

    # Which of the ones this report needs are still present, by exact name?
    print("", flush=True)
    for key, want in sorted(T.SHEETS.items()):
        print(f"NEED: {key:<8} {want!r} -> "
              f"{'PRESENT' if want in names else 'MISSING'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

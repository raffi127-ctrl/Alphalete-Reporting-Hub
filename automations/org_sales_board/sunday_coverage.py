"""Diagnostic: does each ORG Sales Board source crosstab actually contain last
Sunday's data at pull time? Answers the 2026-07-13 question — the board undercounts
by exactly last Sunday, and the VAs have that Sunday, so either (a) the source's
extract lags the live data (Sunday genuinely not in the crosstab) or (b) the pull
drops it. This pulls each CROSSTAB source fresh and prints, per source: the date
range it returned + how many owner-rows have the reporting-Sunday. Short output on
purpose so the mini_control result cell doesn't truncate.

Run:  python -m automations.org_sales_board.sunday_coverage
"""
from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

from automations.org_sales_board import section_pull as sp
from automations.org_sales_board import week as wk


def main() -> int:
    today = dt.date.today()
    mon, sun = wk.reporting_monday(today), wk.reporting_sunday(today)
    print(f"SUNDAY-COVERAGE {today} :: reporting week {mon.isoformat()}..{sun.isoformat()} "
          f"(target Sunday={sun.isoformat()})", flush=True)
    try:
        from automations.shared.tableau_patchright import download_crosstab_patchright
    except Exception as e:  # noqa: BLE001
        print(f"cannot import tableau helper: {e}", flush=True)
        return 1
    for key, spec in sp.SPECS.items():
        try:
            out = Path(tempfile.gettempdir()) / f"suncheck_{key}.csv"
            download_crosstab_patchright(spec.view_url, spec.crosstab_sheet, out, verbose=False)
            parsed = sp.parse_byday(spec, out, today)   # {owner:{metric:{date:int}}}
            dates = sorted({d for m in parsed.values() for md in m.values() for d in md})
            sun_rows = sum(1 for m in parsed.values() for md in m.values() if sun in md)
            rng = f"{dates[0].isoformat()}..{dates[-1].isoformat()}" if dates else "(none)"
            verdict = "HAS Sunday" if sun_rows else "NO Sunday"
            print(f"  {key:5}: {rng}  ->  {verdict} ({sun_rows} owner-rows on {sun.isoformat()})",
                  flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {key:5}: ERROR {str(e).splitlines()[0][:90]}", flush=True)
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

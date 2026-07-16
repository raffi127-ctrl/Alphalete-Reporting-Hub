"""Diagnostic: does each ORG Sales Board source crosstab actually contain last
Sunday's data when pulled EXACTLY the way the board pulls it (week-pinned)?

The 2026-07-13 question: the board undercounts by exactly last Sunday, and the VAs
have that Sunday — so either (a) the source's extract lags (Sunday genuinely not in
it) or (b) the pinned pull drops it. This uses the board's OWN pull_section_byday
(same week-pin) + parse, and prints per source: the date range returned + whether
the reporting-Sunday has data. Short output so the mini_control cell doesn't truncate.

Run:  python -m automations.org_sales_board.sunday_coverage
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import tempfile

from automations.org_sales_board import section_pull as sp
from automations.org_sales_board import week as wk


def _quiet(*_a, **_k):
    pass


def main() -> int:
    today = dt.date.today()
    mon, sun = wk.reporting_monday(today), wk.reporting_sunday(today)
    print(f"SUNDAY-COVERAGE {today} :: pinned to WE {sun.isoformat()} "
          f"(reporting week {mon.isoformat()}..{sun.isoformat()})", flush=True)
    out_dir = Path(tempfile.gettempdir()) / "suncov"
    try:
        from automations.shared.tableau_patchright import tableau_session
    except Exception as e:  # noqa: BLE001
        print(f"cannot import tableau_session: {e}", flush=True)
        return 1
    summary = {}
    with tableau_session() as page:
        for key, spec in sp.SPECS.items():
            try:
                path = sp.pull_section_byday(spec, out_dir, page, logfn=_quiet, today=today)
                parsed = sp.parse_byday(spec, path, today)   # {owner:{metric:{date:int}}}
                dates = sorted({d for m in parsed.values() for md in m.values() for d in md})
                sun_rows = sum(1 for m in parsed.values() for md in m.values() if sun in md)
                rng = f"{dates[0].isoformat()}..{dates[-1].isoformat()}" if dates else "(none)"
                maxd = dates[-1].isoformat() if dates else "-"
                verdict = "HAS Sunday" if sun_rows else "NO Sunday"
                print(f"  {key:5}: {rng}  ->  {verdict} ({sun_rows} rows on {sun.isoformat()})",
                      flush=True)
                summary[key] = f"{'Y' if sun_rows else 'N'}(max {maxd})"
            except Exception as e:  # noqa: BLE001
                print(f"  {key:5}: ERROR {str(e).splitlines()[0][:90]}", flush=True)
                summary[key] = "ERR"
    # One compact line LAST so it survives the mini_control cell truncation (tail-kept).
    print("SUMMARY " + "  ".join(f"{k}={v}" for k, v in summary.items())
          + f"  (Sunday={sun.isoformat()}; Y=has it, N=pin ignored/missing)", flush=True)
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

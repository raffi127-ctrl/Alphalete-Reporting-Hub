"""One-shot RECOVERY: re-stamp the frozen LAST WEEK block's date headers.

Corrects the 'Sat 12/30' bug — where the frozen LAST WEEK section header + every
per-day 'Total Apps' column header rendered as the 12/30/1899 date serial instead
of last week's real dates. That happened because the freeze snapshot copied the
top block's live =TODAY() date formulas, which resolved to empty/0 in the frozen
copy and rendered through a date format.

This is STAMP-ONLY and POSITIONAL (the frozen day-header cells are EMPTY after
the freeze — they render as 'Sat 12/30' — so there's nothing to content-match).
For each tab it:
  1. finds the 'LAST WEEK' label row (col B) — the day headers + banner are on
     that SAME row,
  2. discovers the column->weekday map by reading ROW 1 (the correct current-week
     date row): each 'Ddd m/d' cell gives (column -> weekday); no hardcoded cols,
  3. writes the frozen week's date for each weekday (monday + weekday_index,
     'Ddd m/d') into the SAME column on the LAST WEEK row + recomputes the banner,
  4. strips that row's numberFormat -> TEXT so a string label can't render as a
     12/30/1899 serial.

It does NOT re-scrape ownerville, does NOT re-freeze, does NOT touch rep names,
production numbers, or any other cell — only the frozen date row's labels/format.
So it is safe to run any day, repeatedly (idempotent), without disturbing data.

`--monday` is the Monday of the week CURRENTLY frozen in the LAST WEEK block (the
week whose dates should appear there). For the live sheet showing a current week of
Mon 6/22, the frozen week is Mon 6/15.

Preview ONE tab first (Marcellus-first, per the rollout rule):
    .venv/bin/python -m automations.focus_office_att.fix_frozen_dates \
        --monday 2026-06-15 --only "Marcellus Butler"

Then all tabs:
    .venv/bin/python -m automations.focus_office_att.fix_frozen_dates \
        --monday 2026-06-15
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.daily import (
    DEST_SPREADSHEET_ID, set_frozen_week_dates,
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Re-stamp the frozen LAST WEEK date headers (stamp-only).")
    ap.add_argument("--monday", required=True, metavar="YYYY-MM-DD",
                    help="Monday of the week CURRENTLY frozen in the LAST WEEK "
                         "block (the dates that should show there).")
    ap.add_argument("--only", default="", metavar="TAB",
                    help="Scope to ONE owner tab (Marcellus-first preview).")
    args = ap.parse_args()

    try:
        monday = dt.date.fromisoformat(args.monday)
    except ValueError:
        print(f"Bad --monday {args.monday!r}; expected YYYY-MM-DD", file=sys.stderr)
        return 2
    if monday.weekday() != 0:
        print(f"--monday {monday} is a {monday.strftime('%A')}, not a Monday.",
              file=sys.stderr)
        return 2
    only = args.only.strip() or None

    sunday = monday + dt.timedelta(days=6)
    scope = f'"{only}"' if only else "ALL owner tabs"
    print(f"Re-stamping frozen LAST WEEK dates → week {monday}..{sunday} → {scope}")

    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    n = set_frozen_week_dates(sh, monday, only=only, logfn=print)
    print(f"Done — stamped frozen-week dates on {n} tab(s).")
    if only:
        print(f'Verify "{only}": LAST WEEK header + each per-day header read '
              f"Mon {monday.month}/{monday.day} … Sun {sunday.month}/{sunday.day}. "
              f"Then re-run WITHOUT --only for all tabs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

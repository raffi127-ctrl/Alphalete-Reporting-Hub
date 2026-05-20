"""Run only set_day_column_collapsed on the Daily Rep Breakdown sheet,
without touching anything else. Use this to preview the column-group
collapse fix without re-running the whole scrape pipeline.

Run:
    .venv/bin/python -m automations.focus_office_att._test_collapse
"""
from __future__ import annotations

import datetime as dt

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.daily import (
    DEST_SPREADSHEET_ID, set_day_column_collapsed,
)


def main() -> None:
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    today = dt.date.today()
    print(f"Today: {today.isoformat()} (dow={today.weekday()})")
    n = set_day_column_collapsed(sh, today)
    print(f"Updated collapse state on {n} tab(s).")


if __name__ == "__main__":
    main()

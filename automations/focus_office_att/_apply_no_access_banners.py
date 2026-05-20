"""Run only mark_no_access_tabs on the Daily Rep Breakdown sheet —
stamps the no-access banner using the current focus_office_scrape_results.json.

Run:
    .venv/bin/python -m automations.focus_office_att._apply_no_access_banners
"""
from __future__ import annotations

import json

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.daily import (
    DEST_SPREADSHEET_ID, SCRAPE_RESULTS, NON_OWNER_TABS, mark_no_access_tabs,
)


def main() -> None:
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    pending_results: dict = {}
    if SCRAPE_RESULTS.exists():
        data = json.loads(SCRAPE_RESULTS.read_text())
        pending_results = {o: s for o, s in data.get("results", {}).items()
                           if s != "ok" and o not in NON_OWNER_TABS}
    if pending_results:
        print("Pending tabs from scrape_results.json:")
        for owner, status in sorted(pending_results.items()):
            print(f"  {owner}: {status}")
    else:
        print("Pending tabs from scrape_results.json: (none)")
    counts = mark_no_access_tabs(sh, pending_results)
    print(f"Banner marked on {counts['marked']} tab(s), "
          f"cleared on {counts['cleared']} tab(s).")


if __name__ == "__main__":
    main()

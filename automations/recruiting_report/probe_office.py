"""READ-ONLY: why does one AppStream office come back empty for the Focus fill?

Built 2026-11-09 for Nigel Marshall's second office (23515): the Focus refill
wrote his main box (20034) and then spent ~1-2 min on 23515 and wrote nothing,
twice, with no log line at all. This logs into AppStream exactly like the fill
(appstream_direct_session, the rcaptain profile) and, for each office id, says
what each step saw:

  1. what the office switcher's dropdown lists for that id
  2. whether the login's own office list has it (_office_in_account)
  3. whether the switch lands (fetch_office._switch_office, confirm_denial)
  4. the page URL / title after the switch
  5. what the Retention Report returns for the week (the fill's own scrape)

Nothing is written anywhere -- no Sheet, no Slack, no manifest.

  python -m automations.recruiting_report.probe_office 20034 23515 \
      --week-start 2026-11-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time


def _dropdown_rows(page, office_id: str) -> list:
    page.locator("#searchMC").fill("")
    page.locator("#searchMC").type(office_id, delay=30)
    rows = []
    for _ in range(16):
        page.wait_for_timeout(500)
        items = page.locator(".ui-autocomplete li, .ui-menu li").all()
        rows = []
        for it in items:
            try:
                rows.append(it.inner_text().strip())
            except Exception:  # noqa: BLE001 -- detached mid-read
                continue
        if rows:
            break
    page.locator("#searchMC").fill("")
    return rows


def probe(page, office_id: str, week_start: dt.date) -> dict:
    from automations.recruiting_report import fetch_office as F
    out: dict = {"office": office_id}
    t0 = time.time()

    def step(name, fn):
        s = time.time()
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001 -- the error IS the finding
            out[name] = "ERROR %s: %s" % (type(e).__name__, str(e).splitlines()[0][:300])
        out[name + "_secs"] = round(time.time() - s, 1)
        print("  %-22s %s (%.1fs)" % (name, out[name], out[name + "_secs"]), flush=True)

    F._dismiss_overlays(page)
    step("dropdown_rows", lambda: _dropdown_rows(page, office_id))
    step("in_account_list", lambda: F._office_in_account(page, office_id))
    step("switch_landed", lambda: F._switch_office(page, office_id, "", confirm_denial=True))
    step("after_switch", lambda: {"url": page.url[:160], "title": page.title()[:120]})
    step("retention_report", lambda: (F._ensure_on_retention_report(page) or "on report"))
    step("week_set", lambda: (F._set_week_and_submit(page, week_start) or "submitted"))
    step("tables_on_page", lambda: page.evaluate("document.querySelectorAll('table').length"))
    step("metrics", lambda: F._scrape_metrics(page))
    out["total_secs"] = round(time.time() - t0, 1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("offices", nargs="+", help="AppStream office ids")
    ap.add_argument("--week-start", required=True,
                    help="AppStream week (Sunday) to read, YYYY-MM-DD")
    a = ap.parse_args(argv)
    week = dt.date.fromisoformat(a.week_start)

    from automations.shared.tableau_patchright import appstream_direct_session
    results = []
    with appstream_direct_session(verbose=True) as page:
        for oid in a.offices:
            print("\n=== office %s · week %s ===" % (oid, week), flush=True)
            results.append(probe(page, oid, week))
    print("\nPROBE RESULT " + json.dumps(results, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

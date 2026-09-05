"""ONE-TIME probe (Carlos 2026-09-05): Justin Wood (office 22192) Retention
Details report with the Hide/Show Admin Breakdown ON, last 6 AppStream Sun-Sat
weeks. Read-only on AppStream; the ONLY thing it writes is the raw scrape JSON,
base64/plain-chunked into the control sheet tab "JW Breakdown Raw" for the
laptop to decode and shape into Carlos's one-off comparison spreadsheet.

Does NOT touch the Daily Focus Report or any live report tab. Manual-only:
`lucy rerun jw_admin_breakdown`. Delete the module + its schedule_config entry
once the one-off is delivered.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fetch_office as fo
from automations.recruiting_report import fill as _fill
from automations.recruiter_retention.run import _admin_on, _rqst
from automations.shared.tableau_patchright import appstream_direct_session

OFFICE_ID, OWNER = "22192", "Justin Wood"
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
OUT_TAB = "JW Breakdown Raw"
CHUNK = 45000


def _load_week(page, sunday):
    rqst = _rqst(page)
    url = f"https://applicantstream.com/index.cfm?rqst={rqst}&p=701"
    last_err = None
    for attempt in range(3):
        try:
            page.goto(url, wait_until="commit", timeout=40000)
            page.wait_for_selector("#weekStart", timeout=20000)
            last_err = None
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  [retry] week {sunday}: {e.__class__.__name__} "
                  f"(attempt {attempt + 1}/3)", flush=True)
            page.wait_for_timeout(2000)
    if last_err is not None:
        raise last_err
    _admin_on(page)
    try:
        fo._set_week_and_submit(page, sunday)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] week set: {e}", flush=True)
    page.wait_for_timeout(1500)
    if not page.evaluate("() => !!document.querySelector('tr.adminRow')"):
        _admin_on(page)
        try:
            with page.expect_navigation(timeout=12000, wait_until="load"):
                page.evaluate(
                    """() => { const b=[...document.querySelectorAll('input[type=submit],button,a')]
                        .find(e=>/get report/i.test(e.innerText||e.value||'')); if(b)b.click(); }""")
        except Exception:
            pass
        page.wait_for_timeout(1500)


def _parse_full(page):
    """Every row of the biggest table on the page: section rows (office-level
    day cells) with their adminRow children (per-person day cells). Cells
    1..7 = Sun..Sat, 8 = weekly total (same shape recruiter_retention reads)."""
    rows = page.evaluate(
        """() => { const t = [...document.querySelectorAll('table')]
            .sort((a,b)=>b.querySelectorAll('tr').length-a.querySelectorAll('tr').length)[0];
            if (!t) return [];
            return [...t.querySelectorAll('tr')].map(tr => ({cls: tr.className||'',
                texts: [...tr.querySelectorAll('th,td')].map(c=>(c.innerText||'').replace(/\\s+/g,' ').trim())})); }""")
    sections, cur = [], None
    for r in rows:
        texts = r["texts"]
        if not texts or not texts[0]:
            continue
        if "adminRow" in r["cls"]:
            if cur is not None:
                cur["admins"][texts[0]] = texts[1:9]
        else:
            cur = {"label": texts[0], "cells": texts[1:9], "admins": {}}
            sections.append(cur)
    return sections


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jw_admin_breakdown")
    ap.add_argument("--weeks", type=int, default=6)
    ap.add_argument("--date", default=None, help="override today (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    cur_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    weeks = [cur_sun - dt.timedelta(days=7 * i)
             for i in range(args.weeks - 1, -1, -1)]

    out = {"office_id": OFFICE_ID, "owner": OWNER,
           "scraped_at": dt.datetime.now().isoformat(), "weeks": {}}
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        page.wait_for_selector("#searchMC", timeout=20000)
        body = page.evaluate("() => document.body.innerText || ''")
        if f"Office ID: {OFFICE_ID}" not in body:
            if not fo._switch_office(page, OFFICE_ID, OWNER, confirm_denial=True):
                print(f"FATAL: this account cannot reach office {OFFICE_ID}",
                      flush=True)
                return 1
            page.wait_for_timeout(1500)
        for sun in weeks:
            _load_week(page, sun)
            secs = _parse_full(page)
            out["weeks"][sun.isoformat()] = secs
            n_admin = sum(len(s["admins"]) for s in secs)
            print(f"  AS week {sun}: {len(secs)} sections, {n_admin} admin rows",
                  flush=True)

    # base64 the JSON so cells are inert text — same chunk scheme as 'RP Shot'.
    import base64
    b64 = base64.b64encode(json.dumps(out).encode()).decode()
    chunks = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)]
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(OUT_TAB)
    except Exception:  # noqa: BLE001 — first run creates the tab
        ws = sh.add_worksheet(title=OUT_TAB, rows=200, cols=1)
    ws.clear()
    ws.update([[c] for c in chunks], "A1")
    print(f"wrote {len(b64)} b64 chars in {len(chunks)} chunk(s) -> '{OUT_TAB}'",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

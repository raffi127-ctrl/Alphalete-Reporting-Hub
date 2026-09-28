"""Email Tracking pull — every email an office sent, and whether it was
opened, off `index.cfm?p=792`.

WHY (Megan 2026-09-28). Every list this audit produced carries the caveat
"this is the text log, it cannot see email". It can: the Reports menu has
Email Tracking Data, and I had written it off without looking. That caveat
sits on the never-reached lists now in four teams' hands, and it matters —
someone who was emailed is not someone we failed to contact.

Columns: App Id | Applicant Name | Email Sent To | Phone | Email Type |
Email Name | Status | Date Sent | Date Opened | Time To Open | Delivery.
Phone is what joins it to the SMS log.

  lucy rerun sms_email_tracking --office 11280 --machine "Lucy 2"
  ... pull_email_tracking.py --office 11280 --dates 09-15-2026,09-25-2026

READ-ONLY. Writes tab "Email Tracking <office>" + output/email_tracking_
<office>.json.

TWO TRAPS ON THIS PAGE. The Status filter defaults to "Not Opened Yet", so
a naive read returns only the unopened ones and looks like a complete
answer — it is set to All first. And Date Sent takes ONE day, so a window
is one submission per day, with the day stamped on every row.
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9 — keep lazy

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fetch_office as fo
from automations.recruiting_report import fill as _fill
from automations.shared.tableau_patchright import appstream_direct_session
from automations.sms_thread_dump.run import _recruiting_week

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB_PREFIX = "Email Tracking"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
COLUMNS = ["day", "app_id", "applicant", "email", "phone", "email_type",
           "email_name", "status", "sent", "opened", "time_to_open"]
HEADER_MAP = {
    "app id": "app_id", "applicant name": "applicant",
    "email sent to": "email", "phone": "phone", "email type": "email_type",
    "email name": "email_name", "status": "status", "date sent": "sent",
    "date opened": "opened", "time to open": "time_to_open",
}
WRITE_CHUNK = 4000
CELL_CAP = 45000


def _rqst(page):
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.url or "")
    if m:
        return m.group(1)
    m = re.search(r"rqst=([A-Za-z0-9_-]+)",
                  page.evaluate("() => document.documentElement.innerHTML") or "")
    return m.group(1) if m else None


def _setup(page, day):
    """Status -> everything, the date -> this day, rows per page -> the most
    it offers. Leaving Status alone returns only "Not Opened Yet", which is
    a subset that reads exactly like a full answer."""
    return page.evaluate(
        r"""(day) => {
             const notes = [];
             for (const sel of document.querySelectorAll('select')) {
               const opts = [...sel.options].map(o => (o.text || '').trim());
               const all = [...sel.options].find(
                 o => /^(--\s*)?all(\s*--)?$/i.test((o.text || '').trim()));
               if (all && opts.some(t => /not opened/i.test(t))) {
                 sel.value = all.value;
                 sel.dispatchEvent(new Event('change', {bubbles: true}));
                 notes.push('status=All');
               }
               const big = [...sel.options]
                 .map(o => parseInt((o.text || '').trim(), 10))
                 .filter(n => !isNaN(n)).sort((a, b) => b - a)[0];
               if (big && opts.length <= 6 && big >= 25) {
                 const hit = [...sel.options].find(
                   o => parseInt(o.text, 10) === big);
                 if (hit) {
                   sel.value = hit.value;
                   sel.dispatchEvent(new Event('change', {bubbles: true}));
                   notes.push('rows=' + big);
                 }
               }
             }
             for (const i of document.querySelectorAll('input')) {
               const t = (i.type || '').toLowerCase();
               const near = (i.name || '') + ' ' + (i.id || '');
               if (t === 'date' && /sent/i.test(near + ' ' +
                     (i.closest('td,div') || {innerText: ''}).innerText)) {
                 i.value = day;
                 i.dispatchEvent(new Event('change', {bubbles: true}));
                 notes.push('sent=' + day);
               }
             }
             return notes.join(' ') || 'nothing set';
           }""", day)


def _get_report(page):
    return page.evaluate(
        r"""() => {
             const b = [...document.querySelectorAll(
               'button, input[type=submit], input[type=button], a')]
               .find(x => /get report/i.test(
                 ((x.innerText || x.value || '').trim())));
             if (!b) return 'no Get Report button';
             b.click();
             return 'clicked';
           }""")


def _scrape(page, day):
    got = page.evaluate(
        r"""(wanted) => {
             const headerOf = (t) => [...t.querySelectorAll('tr')].find(tr => {
               const c = [...tr.querySelectorAll('th,td')].map(
                 x => (x.innerText || '').replace(/\s+/g, ' ')
                        .trim().toLowerCase());
               return c.includes('email sent to') && c.includes('phone');
             });
             let tbl = null, head = null;
             for (const t of document.querySelectorAll('table')) {
               const h = headerOf(t);
               if (!h) continue;
               if (!tbl || t.querySelectorAll('tr').length
                           > tbl.querySelectorAll('tr').length) {
                 tbl = t; head = h;
               }
             }
             if (!tbl) return {error: 'no table with Email Sent To + Phone'};
             const names = [...head.querySelectorAll('th,td')].map(
               c => (c.innerText || '').replace(/\s+/g, ' ').trim().toLowerCase());
             const out = [];
             for (const tr of [...tbl.querySelectorAll('tr')]) {
               if (tr === head) continue;
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length < 5) continue;
               const rec = {};
               tds.forEach((td, i) => {
                 const key = wanted[names[i]];
                 if (key) rec[key] = (td.innerText || '')
                   .replace(/\s+/g, ' ').trim();
               });
               if (rec.email || rec.phone) out.push(rec);
             }
             const info = ((document.body.innerText || '')
                           .match(/Showing[^\n]{0,60}/i) || [''])[0];
             return {rows: out, columns: names, info: info};
           }""", HEADER_MAP)
    if got.get("error"):
        raise RuntimeError(got["error"])
    for r in got["rows"]:
        r["day"] = day
    return got


def _next(page):
    return page.evaluate(
        r"""() => {
             const a = [...document.querySelectorAll('a, button, li')]
               .find(e => /^next$/i.test(((e.innerText || '').trim()))
                          && !/disabled/i.test(e.className || '')
                          && !(e.parentElement
                               && /disabled/i.test(e.parentElement.className || '')));
             if (!a) return false;
             a.click();
             return true;
           }""")


def _write_tab(records, meta, office):
    tab = "{} {}".format(TAB_PREFIX, office)
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(tab, rows=max(len(records) + 10, 100),
                              cols=len(COLUMNS) + 1)
    if ws.row_count < len(records) + 5:
        ws.resize(rows=len(records) + 5, cols=len(COLUMNS) + 1)
    rows = [[meta] + [""] * (len(COLUMNS) - 1), list(COLUMNS)]
    for r in records:
        rows.append([str(r.get(c, ""))[:CELL_CAP] for c in COLUMNS])
    for start in range(0, len(rows), WRITE_CHUNK):
        ws.update(values=rows[start:start + WRITE_CHUNK],
                  range_name="A{}".format(start + 1), raw=True)
    return tab, len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280")
    ap.add_argument("--dates", default="", help="FROM,TO in MM-DD-YYYY")
    ap.add_argument("--week", type=int, nargs="?", const=1, default=0)
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    offices = [o.strip() for o in str(a.office).split(",") if o.strip()]
    if a.dates:
        parts = [s.strip() for s in a.dates.split(",") if s.strip()]
        lo = dt.datetime.strptime(parts[0], "%m-%d-%Y").date()
        hi = dt.datetime.strptime(parts[1], "%m-%d-%Y").date()
    else:
        lo, hi = _recruiting_week(back=a.week or 1)
    days, d = [], lo
    while d <= hi:
        days.append(d)
        d += dt.timedelta(days=1)
    print("[email] {} office(s) x {} day(s) {} -> {}".format(
        len(offices), len(days), lo, hi), flush=True)

    OUTPUT_DIR.mkdir(exist_ok=True)
    rc = 0
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        tok = _rqst(page)
        for office in offices:
            fo._switch_office(page, office, "")
            page.wait_for_timeout(1500)
            tok = _rqst(page) or tok
            records = []
            for day in days:
                iso = day.strftime("%Y-%m-%d")
                try:
                    page.goto("https://www.applicantstream.com/index.cfm?"
                              "rqst={}&p=792".format(tok),
                              wait_until="domcontentloaded", timeout=40000)
                    page.wait_for_timeout(3500)
                    print("   {} {}: {}".format(office, iso,
                                                _setup(page, iso)), flush=True)
                    _get_report(page)
                    page.wait_for_timeout(3500)
                    for _n in range(a.max_pages):
                        got = _scrape(page, day.strftime("%m-%d-%Y"))
                        records.extend(got["rows"])
                        if not _next(page):
                            break
                        page.wait_for_timeout(1500)
                except Exception as e:  # noqa: BLE001 — one day must not end it
                    print("   {} {}: FAILED {}".format(
                        office, iso, str(e).splitlines()[0][:120]), flush=True)
                    rc = 1
            print("[email] {}: {} rows".format(office, len(records)), flush=True)
            if not records:
                rc = 1
                continue
            (OUTPUT_DIR / "email_tracking_{}.json".format(office)).write_text(
                json.dumps(records, ensure_ascii=False))
            meta = ("email tracking {:%Y-%m-%d %H:%M} office={} range={}..{} "
                    "rows={}".format(dt.datetime.now(), office, lo, hi,
                                     len(records)))
            if a.dry_run:
                print("[email] DRY RUN — no sheet write. " + meta, flush=True)
                continue
            tab, n = _write_tab(records, meta, office)
            print("[email] {}: {} rows -> tab '{}'".format(office, n, tab),
                  flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())

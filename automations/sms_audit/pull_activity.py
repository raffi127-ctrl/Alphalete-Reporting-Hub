"""Activity pull — every recorded action on an applicant, with its TIME and
who did it, off the AppStream **Activity Report** (`index.cfm?p=704`).

WHY (Megan 2026-09-26): she wants the hour with the highest phone-call answer
rate beside the hour with the highest text reply rate. The SMS List Report is
texts only, the Retention Report is per-day totals, and p=1530 "AI Live Calls"
is broken server-side. p=704 is the one page that carries a timestamp on each
individual action:

  Activity | Source of Activity | Account: Owner Name | Account: Office Name |
  User Name | Applicant Name | Phone | Job Board | Time of Activity

  1 | First Interview Date | Calendar | Rafael Hidalgo | ALPHALETE MARKETING,
  INC. | AI Messaging | Chris Chapa | 12149662181 | Indeed |
  09-25-2026 08:15 AM

"Activity" is the action — the page's own filter lists them — so call outcomes
(No Answer, Left Message, …) land here with an hour attached, which is what
makes an answer-rate-by-hour possible at all. `User Name` separates the
automation from a person, and `Phone` joins to the SMS log and the calendar.

  lucy rerun sms_activity --office 11280 --machine "Lucy 2"
  ... pull_activity.py --office 11280 --dates 09-19-2026,09-25-2026
  ... pull_activity.py --office 11280 --dry-run   # scrape, count, no write

READ-ONLY. Writes tab "Activity <office>" and output/activity_<office>.json.

MECHANICS. The page renders an EMPTY grid until it is submitted — that is why
the first probe could not tell what it held. It carries the date twice, like
p=336 does: `activityDate` in MM-DD-YYYY and `activityDate2` in MM/DD/YYYY,
and both are set. Unlike p=336 it takes ONE date, so a week is seven
submissions rather than a range; the day is stamped on every row so the parts
can be told apart afterwards. Row 1 of the grid is the filter dropdowns, not
data, and is dropped by requiring a numeric first cell.
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

from automations.recruiting_report import fill as _fill
from automations.shared.tableau_patchright import appstream_direct_session
from automations.sms_thread_dump.run import _recruiting_week

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB_PREFIX = "Activity"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
COLUMNS = ["activity", "source", "user", "applicant", "phone", "board", "at"]
HEADER_MAP = {
    "activity": "activity", "source of activity": "source",
    "user name": "user", "applicant name": "applicant", "phone": "phone",
    "job board": "board", "time of activity": "at",
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


def _set_day(page, day):
    """Both date fields, each in its own format — the same two-spelling trap
    p=336 has, and setting only the visible one leaves the report on today."""
    slash = day.replace("-", "/")
    out = page.evaluate(
        r"""([d, slash]) => {
             const set = (name, v) => {
               const el = document.querySelector("input[name='" + name + "']");
               if (!el) return null;
               el.value = v;
               el.dispatchEvent(new Event('change', {bubbles: true}));
               return name + '=' + v;
             };
             const done = [set('activityDate', d), set('activityDate2', slash)]
                            .filter(Boolean);
             if (done.length) return done.join(' ');
             const ins = [...document.querySelectorAll('input')].filter(
               i => /^\d{2}[-/]\d{2}[-/]\d{4}$/.test((i.value || '').trim()));
             ins.slice(0, 2).forEach(i => {
               i.value = /\//.test(i.value) ? slash : d;
               i.dispatchEvent(new Event('change', {bubbles: true}));
             });
             return ins.length ? 'fallback by value' : 'no date field';
           }""", [day, slash])
    if out == "no date field":
        raise RuntimeError("Activity Report has no date field")
    return out


def _scrape(page, day):
    """Grid rows as dicts. The first row is the filter dropdowns ("-Select
    Activity-"), not data — it is dropped by requiring a row number in the
    leading cell, which is also what keeps a totals footer out."""
    got = page.evaluate(
        r"""(wanted) => {
             const tbl = [...document.querySelectorAll('table')].find(
               t => t.offsetParent !== null && /Time of Activity/.test(t.innerText));
             if (!tbl) return {error: 'no grid'};
             const trs = [...tbl.querySelectorAll('tr')];
             const head = trs.find(tr => /Time of Activity/.test(tr.innerText));
             if (!head) return {error: 'no header row'};
             const names = [...head.querySelectorAll('th, td')].map(
               c => (c.innerText || '').replace(/\s+/g, ' ').trim().toLowerCase()
                     .replace(/[^a-z ]/g, '').trim());
             const out = [];
             for (const tr of trs) {
               if (tr === head) continue;
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length < 4) continue;
               const first = (tds[0].innerText || '').trim();
               if (!/^\d+$/.test(first)) continue;
               const rec = {};
               tds.forEach((td, i) => {
                 const key = wanted[names[i]];
                 if (key) rec[key] = (td.innerText || '').replace(/\s+/g, ' ').trim();
               });
               if (rec.activity) out.push(rec);
             }
             return {rows: out, columns: names};
           }""", HEADER_MAP)
    if got.get("error"):
        raise RuntimeError("grid: {}".format(got["error"]))
    for r in got["rows"]:
        r["day"] = day
    return got["rows"]


def _submit(page):
    for how in (lambda: page.get_by_role("button", name=re.compile("Get Report", re.I))
                             .first.click(timeout=6000),
                lambda: page.locator("input[type=submit][value*='Get Report' i]")
                            .first.click(timeout=6000)):
        try:
            how()
            page.wait_for_load_state("networkidle")
            time.sleep(2.0)
            return
        except Exception:
            continue
    raise RuntimeError("no Get Report button on the Activity Report")


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
    cols = ["day"] + COLUMNS
    rows = [[meta] + [""] * len(COLUMNS), list(cols)]
    for r in records:
        rows.append([str(r.get(c, ""))[:CELL_CAP] for c in cols])
    for start in range(0, len(rows), WRITE_CHUNK):
        chunk = rows[start:start + WRITE_CHUNK]
        ws.update(values=chunk, range_name="A{}".format(start + 1), raw=True)
    return tab, len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280", help="one id or a comma list")
    ap.add_argument("--dates", default="",
                    help="FROM,TO in MM-DD-YYYY; default the last Sat-Fri week")
    ap.add_argument("--week", type=int, nargs="?", const=1, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    offices = [o.strip() for o in str(a.office).split(",") if o.strip()]
    if a.dates:
        parts = [s.strip() for s in a.dates.split(",") if s.strip()]
        if len(parts) != 2:
            ap.error("--dates takes FROM,TO in MM-DD-YYYY")
        lo = dt.datetime.strptime(parts[0], "%m-%d-%Y").date()
        hi = dt.datetime.strptime(parts[1], "%m-%d-%Y").date()
    else:
        lo, hi = _recruiting_week(back=a.week or 1)
    days = []
    d = lo
    while d <= hi:
        days.append(d.strftime("%m-%d-%Y"))
        d += dt.timedelta(days=1)
    print("[activity] offices {} · {} day(s) {} → {}".format(
        offices, len(days), days[0], days[-1]), flush=True)

    OUTPUT_DIR.mkdir(exist_ok=True)
    rc = 0
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        tok = _rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the console page")
        for office in offices:
            page.goto("https://www.applicantstream.com/index.cfm?p=104&rqst={}"
                      "&newOfficeId={}".format(tok, office))
            page.wait_for_load_state("networkidle")
            time.sleep(1.0)
            tok = _rqst(page) or tok
            records = []
            for day in days:
                try:
                    page.goto("https://www.applicantstream.com/index.cfm?rqst={}&p=704"
                              .format(tok), wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2.0)
                    _set_day(page, day)
                    _submit(page)
                    got = _scrape(page, day)
                except Exception as e:  # noqa: BLE001 — one day must not kill the week
                    print("[activity] {} {}: FAILED {}: {}".format(
                        office, day, type(e).__name__,
                        str(e).splitlines()[0][:140]), flush=True)
                    rc = 1
                    continue
                print("[activity] {} {}: {} rows".format(office, day, len(got)),
                      flush=True)
                records.extend(got)
            if not records:
                print("[activity] {}: nothing scraped — tab left alone".format(office),
                      flush=True)
                rc = 1
                continue
            (OUTPUT_DIR / "activity_{}.json".format(office)).write_text(
                json.dumps(records, ensure_ascii=False))
            meta = ("activity {:%Y-%m-%d %H:%M} office={} range={}..{} rows={}"
                    .format(dt.datetime.now(), office, days[0], days[-1], len(records)))
            if a.dry_run:
                print("[activity] DRY RUN — no sheet write. " + meta, flush=True)
                continue
            tab, n = _write_tab(records, meta, office)
            print("[activity] {}: {} rows → tab '{}'".format(office, n, tab), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())

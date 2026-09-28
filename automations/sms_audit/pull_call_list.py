"""Call List pull — every applicant on an office's call list with their
STATUS (Open / LM1 / LM2 / LM3 / No Answer), off `index.cfm?p=501`.

WHY (Megan 2026-09-28). The SMS audit found 4,342 people on 11280 who got
exactly one text, and 4 of them booked. I called that abandoned. Megan:
"applicants are called and messaged multiple times though? What is their
status in the call list for the ones you say were only contacted once?
LM1/Open/LM2?"

She is right that the claim does not stand on texts alone. The Retention
Report shows the calls happening at volume — 577 Left Message One, 522 Two,
1,011 Three in a single week — and CLQ (Call List Quick) exists precisely to
mass-text the applicants there was no time to ring. So a single text may be
the LAST step of a worked applicant, not the only contact they ever had.
Nothing in p=336 can tell those apart; the status on the call list can.

  lucy rerun sms_call_list --office 11280 --machine "Lucy 2"
  ... pull_call_list.py --office 11280 --dry-run

READ-ONLY. Writes tab "Call List <office>" + output/call_list_<office>.json.
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

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB_PREFIX = "Call List"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
COLUMNS = ["applicant", "phone", "email", "status", "job_board", "entered"]
HEADER_MAP = {
    "applicant": "applicant", "name": "applicant",
    "first name": "first", "last name": "last",
    "phone": "phone", "email": "email", "status": "status",
    "job board": "job_board", "date entered": "entered",
    "entered date": "entered", "date": "entered",
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


def diagnose(page):
    """Everything about the grid in one shot — a wrong guess at the column
    names otherwise costs a whole queue round trip."""
    return page.evaluate(
        r"""() => {
             const tbls = [...document.querySelectorAll('table')]
               .filter(t => t.offsetParent !== null)
               .map(t => ({
                 rows: t.querySelectorAll('tr').length,
                 head: [...t.querySelectorAll('tr')].slice(0, 3).map(
                   tr => [...tr.querySelectorAll('th,td')].map(
                     c => (c.innerText || '').replace(/\s+/g, ' ').trim()
                   ).join(' | ')).join('  //  ')}))
               .sort((a, b) => b.rows - a.rows).slice(0, 4);
             return {url: location.href, tables: tbls,
                     pager: ((document.body.innerText || '')
                             .match(/Page[^\n]{0,40}/) || [''])[0]};
           }""")


def _scrape(page):
    """Grid rows as dicts, by HEADER NAME — never by position. The call list
    gains and loses columns per office (Distance and Zip only appear when the
    office has them set), so an index-based read silently shifts."""
    got = page.evaluate(
        r"""(wanted) => {
             // Pick the table by its HEADER, not by page text. Matching on
             // innerText picked the toolbar — "Excel - 30 Days", "Apply
             // Filters", "Page 1 of 47" — which mentions plenty and holds
             // no applicants, and the read came back with zero rows.
             const headerOf = (t) => [...t.querySelectorAll('tr')].find(tr => {
               const cells = [...tr.querySelectorAll('th,td')].map(
                 c => (c.innerText || '').replace(/\s+/g, ' ').trim().toLowerCase());
               return cells.includes('status') && cells.includes('phone');
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
             if (!tbl) return {error: 'no table whose header has Phone and Status'};
             const trs = [...tbl.querySelectorAll('tr')];
             const names = [...head.querySelectorAll('th,td')].map(
               c => (c.innerText || '').replace(/\s+/g, ' ').trim().toLowerCase());
             const out = [];
             for (const tr of trs) {
               if (tr === head) continue;
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length < 4) continue;
               const rec = {};
               tds.forEach((td, i) => {
                 const key = wanted[names[i]];
                 if (key) rec[key] = (td.innerText || '')
                   .replace(/\s+/g, ' ').trim();
               });
               if (rec.phone || rec.applicant || rec.first) out.push(rec);
             }
             const pager = ((document.body.innerText || '')
                            .match(/Page\s*\d*\s*of\s*\d+/i) || [''])[0];
             return {rows: out, columns: names, pager: pager};
           }""", HEADER_MAP)
    if got.get("error"):
        raise RuntimeError("grid: {}".format(got["error"]))
    if got.get("pager"):
        print("   grid says: {}".format(got["pager"]), flush=True)
    for r in got["rows"]:
        if not r.get("applicant"):
            r["applicant"] = " ".join(
                x for x in (r.pop("first", ""), r.pop("last", "")) if x).strip()
        r.pop("first", None)
        r.pop("last", None)
    return got["rows"], got["columns"]


def _submit(page):
    """Click Search / Apply Filters and wait.

    The THIRD page in this app that renders its header and pager but no
    body until something is submitted — p=336 needed its dates plus
    Search, p=704 needed Get Report, and this one needs Apply Filters.
    Assume it of any AppStream grid that comes back with a header and
    zero rows."""
    got = page.evaluate(
        r"""() => {
             const btns = [...document.querySelectorAll(
               'input[type=submit], input[type=button], button, a')];
             const hit = btns.find(b => /^(search|apply filters|go)$/i.test(
               ((b.innerText || b.value || '').trim())));
             if (!hit) return 'no search button';
             hit.click();
             return 'clicked ' + ((hit.innerText || hit.value || '').trim());
           }""")
    print("   submit: {}".format(got), flush=True)
    try:
        page.wait_for_load_state("networkidle")
    except Exception:  # noqa: BLE001
        pass
    time.sleep(2.5)
    return got


def _dump_tables(page):
    """Every table with its first rows — so a failed read is diagnosed from
    one run instead of a round trip per guess."""
    return page.evaluate(
        r"""() => [...document.querySelectorAll('table')].map((t, i) => ({
             i: i, rows: t.querySelectorAll('tr').length,
             vis: t.offsetParent !== null,
             first: [...t.querySelectorAll('tr')].slice(0, 3).map(
               tr => [...tr.querySelectorAll('th,td')].map(
                 c => (c.innerText || '').replace(/\s+/g, ' ').trim()
               ).join(' | ').slice(0, 220))
           })).filter(x => x.rows > 1).slice(0, 8)""")


def _next_page(page):
    """Click to the next page of the grid; False when there is no next."""
    return page.evaluate(
        r"""() => {
             const a = [...document.querySelectorAll('a, input[type=button]')]
               .find(e => /^(next|>|»)$/i.test(
                 ((e.innerText || e.value || '').trim())));
             if (!a || a.disabled) return false;
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
    ap.add_argument("--office", default="11280", help="one id or a comma list")
    ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    offices = [o.strip() for o in str(a.office).split(",") if o.strip()]
    OUTPUT_DIR.mkdir(exist_ok=True)
    rc = 0
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        tok = _rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the console page")
        for office in offices:
            fo._switch_office(page, office, "")
            page.wait_for_timeout(1500)
            tok = _rqst(page) or tok
            page.goto("https://www.applicantstream.com/index.cfm?rqst={}&p=501"
                      .format(tok), wait_until="domcontentloaded", timeout=40000)
            page.wait_for_load_state("networkidle")
            time.sleep(2.0)
            d = diagnose(page)
            print("[call_list] {} diagnose: {}".format(office, d["pager"]),
                  flush=True)
            for t in d["tables"][:2]:
                print("   table {} rows | {}".format(t["rows"], t["head"][:200]),
                      flush=True)
            _submit(page)
            records, cols = [], []
            for n in range(a.max_pages):
                try:
                    got, cols = _scrape(page)
                except Exception as e:  # noqa: BLE001
                    print("[call_list] {}: {}".format(office, e), flush=True)
                    rc = 1
                    break
                records.extend(got)
                print("   page {}: {} rows (total {})".format(
                    n + 1, len(got), len(records)), flush=True)
                if not _next_page(page):
                    break
                page.wait_for_load_state("networkidle")
                time.sleep(1.5)
            if not records:
                print("[call_list] {}: nothing scraped — dumping the page so "
                      "the next attempt is not another guess".format(office),
                      flush=True)
                for t in _dump_tables(page):
                    print("   table {} ({} rows, visible={})".format(
                        t["i"], t["rows"], t["vis"]), flush=True)
                    for line in t["first"]:
                        print("      {}".format(line), flush=True)
                rc = 1
                continue
            print("[call_list] {} columns seen: {}".format(office, cols),
                  flush=True)
            (OUTPUT_DIR / "call_list_{}.json".format(office)).write_text(
                json.dumps(records, ensure_ascii=False))
            meta = "call list {:%Y-%m-%d %H:%M} office={} rows={}".format(
                dt.datetime.now(), office, len(records))
            if a.dry_run:
                print("[call_list] DRY RUN — no sheet write. " + meta, flush=True)
                continue
            tab, n = _write_tab(records, meta, office)
            print("[call_list] {}: {} rows → tab '{}'".format(office, n, tab),
                  flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())

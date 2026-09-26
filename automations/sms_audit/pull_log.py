"""SMS log pull — every text an office sent or received over a date range, off
the AppStream **SMS List Report** (Reports → NEW REPORTS → SMS List Report,
`index.cfm?p=336`), into the control sheet, one tab per office.

WHY THIS AND NOT THE CALENDAR WALK (Megan 2026-09-26): `sms_thread_dump` reads
threads off each *booking*, so it only ever sees applicants who booked — and
the people most likely to have been left on read are exactly the ones who never
did. This page has no such filter. It also carries two columns the Chat History
does not:

  * **Sent By** — "AI Messaging" on an automated send, the recruiter's name on
    a human one. This is the real answer to "how quick are our HUMAN recruiters
    responding"; the calendar walk could only guess from who booked.
  * **Status** — Delivered / Error, so a text that never arrived stops counting
    as one we sent.

  lucy rerun sms_log --office 11280,23965,24065 --machine "Lucy 2"
  ... pull_log.py --office 11280 --week 2       # the week before last
  ... pull_log.py --office 11280 --dates 09-19-2026,09-25-2026
  ... pull_log.py --dry-run                     # scrape, print counts, no write

READ-ONLY on AppStream. The only writes are the sheet tab and a local JSON.

Page mechanics (confirmed from a live screenshot 2026-09-26, office 11280):
From Date / To Date are plain text inputs in **MM-DD-YYYY**, both prefilled
with today; a **Search** button reloads the grid in place. The header then
reads "Bandwidth V2 SMS for <from> - <to>", which the pull checks before it
believes a single row. Columns: No, Type (In/Out), Queued At, Sent At, Sender,
Sender Phone, Recipient, Recipient Phone, Applicant Removed, Source, SMS Type,
Body, Character Count, Credits Used, Status, Sent By. One ordinary day in
Raf's office is ~870 rows, so a week is ~5,000.
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
TAB_PREFIX = "SMS Log"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

# What we keep. "No", "Applicant Removed", "Character Count" and "Credits Used"
# are dropped — a week of four offices is ~20k rows and none of those four
# change an answer.
COLUMNS = ["type", "queued_at", "sent_at", "sender", "sender_phone",
           "recipient", "recipient_phone", "source", "sms_type", "body",
           "status", "sent_by"]
HEADER_MAP = {
    "type": "type", "queued at": "queued_at", "sent at": "sent_at",
    "sender": "sender", "sender phone": "sender_phone",
    "recipient": "recipient", "recipient phone": "recipient_phone",
    "source": "source", "sms type": "sms_type", "body": "body",
    "status": "status", "sent by": "sent_by",
}
CELL_CAP = 45000


def _rqst(page):
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.url or "")
    if m:
        return m.group(1)
    m = re.search(r"rqst=([A-Za-z0-9_-]+)",
                  page.evaluate("() => document.documentElement.innerHTML") or "")
    return m.group(1) if m else None


def _fmt(d):
    return d.strftime("%m-%d-%Y")


def _set_range(page, lo, hi):
    """Fill From/To and press Search.

    The two inputs are found by the date already in them — both are prefilled
    with today — and only by name/id as a fallback. Matching on the VALUE is
    what survives the page renaming its fields, which an id-only match would
    not."""
    filled = page.evaluate(
        """([lo, hi]) => {
             const ins = [...document.querySelectorAll('input[type=text], input:not([type])')];
             const dated = ins.filter(i => /^\\d{2}-\\d{2}-\\d{4}$/.test((i.value||'').trim()));
             let from = dated[0], to = dated[1];
             if (!from || !to) {
               const byName = n => ins.find(i =>
                 new RegExp(n, 'i').test((i.name||'') + ' ' + (i.id||'')));
               from = from || byName('from|start|begin');
               to   = to   || byName('^to$|todate|to_date|end');
             }
             if (!from || !to) return 'inputs not found: ' + ins.map(
               i => (i.name||i.id||'?') + '=' + (i.value||'')).join(' | ').slice(0, 300);
             for (const [el, v] of [[from, lo], [to, hi]]) {
               el.value = v;
               el.dispatchEvent(new Event('input', {bubbles: true}));
               el.dispatchEvent(new Event('change', {bubbles: true}));
             }
             return 'ok';
           }""", [lo, hi])
    if filled != "ok":
        raise RuntimeError("SMS List Report date fields: " + filled)

    for how in (lambda: page.get_by_role("button", name=re.compile(r"^\s*Search\s*$", re.I)).first.click(),
                lambda: page.locator("input[type=submit][value*='Search' i]").first.click(),
                lambda: page.locator("button:has-text('Search')").first.click()):
        try:
            how()
            break
        except Exception:
            continue
    else:
        raise RuntimeError("no Search button on the SMS List Report")
    page.wait_for_load_state("networkidle")
    time.sleep(2.0)


def _confirm_range(page, lo, hi):
    """The grid header restates the window it is showing. Trust nothing until
    it matches what we asked for — a Search that silently did not take would
    otherwise hand back TODAY's rows labelled as the week's."""
    txt = page.evaluate("() => document.body.innerText") or ""
    m = re.search(r"SMS for\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})", txt)
    if not m:
        raise RuntimeError("no 'SMS for <from> - <to>' header — did Search run?")
    got = (m.group(1).replace("/", "-"), m.group(2).replace("/", "-"))
    if got != (lo, hi):
        raise RuntimeError("grid shows {} → {}, asked for {} → {}".format(
            got[0], got[1], lo, hi))
    tot = re.search(r"Total:\s*(\d+)\s*\|\s*Incoming:\s*(\d+)\s*\|\s*Outgoing:\s*(\d+)", txt)
    return (int(tot.group(1)), int(tot.group(2)), int(tot.group(3))) if tot else (None, None, None)


def _scrape_grid(page):
    """Rows as dicts keyed by the header text, so a column moving does not
    silently shift every field one to the left."""
    return page.evaluate(
        """(wanted) => {
             const tbl = [...document.querySelectorAll('table')].find(
               t => t.offsetParent !== null && /Recipient Phone/.test(t.innerText)
                    && /Sent By/.test(t.innerText));
             if (!tbl) return {error: 'no grid'};
             const rows = [...tbl.querySelectorAll('tr')];
             const head = rows.find(r => r.querySelectorAll('th').length
                                      || /Recipient Phone/.test(r.innerText));
             if (!head) return {error: 'no header row'};
             const names = [...head.querySelectorAll('th, td')].map(
               c => (c.innerText || '').replace(/\\s+/g, ' ').trim().toLowerCase()
                     .replace(/[^a-z ]/g, '').trim());
             const out = [];
             for (const tr of rows) {
               if (tr === head) continue;
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length < names.length - 2) continue;
               const rec = {};
               tds.forEach((td, i) => {
                 const key = wanted[names[i]];
                 if (key) rec[key] = (td.innerText || '').replace(/\\s+/g, ' ').trim();
               });
               if (rec.type || rec.body) out.push(rec);
             }
             return {rows: out, columns: names};
           }""", HEADER_MAP)


def _write_tab(records, meta, office):
    tab = "{} {}".format(TAB_PREFIX, office)
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(tab, rows=max(len(records) + 10, 100),
                              cols=len(COLUMNS))
    if ws.row_count < len(records) + 5:
        ws.resize(rows=len(records) + 5, cols=len(COLUMNS))
    rows = [[meta] + [""] * (len(COLUMNS) - 1), list(COLUMNS)]
    for r in records:
        rows.append([str(r.get(c, ""))[:CELL_CAP] for c in COLUMNS])
    ws.update(values=rows, range_name="A1", raw=True)
    return tab, len(rows)


def pull_office(page, tok, office, owner, lo, hi):
    if owner:
        if not fo._switch_office(page, office, owner, confirm_denial=True):
            raise RuntimeError("cannot reach office {}".format(office))
        time.sleep(1.5)
        tok = _rqst(page) or tok
    else:
        page.goto("https://www.applicantstream.com/index.cfm?p=104&rqst={}"
                  "&newOfficeId={}".format(tok, office))
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)

    page.goto("https://www.applicantstream.com/index.cfm?rqst={}&p=336".format(tok))
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)
    _set_range(page, lo, hi)
    total, incoming, outgoing = _confirm_range(page, lo, hi)
    got = _scrape_grid(page)
    if got.get("error"):
        raise RuntimeError("grid: {}".format(got["error"]))
    rows = got["rows"]
    print("[sms_log] {}: page says Total {} (in {} / out {}), scraped {}"
          .format(office, total, incoming, outgoing, len(rows)), flush=True)
    # The page's own total is the check on our parse. A short read here means a
    # column moved or a row shape changed, and a quietly short log reads as
    # "nobody texted them" — the exact wrong answer for this audit.
    if total is not None and len(rows) < total:
        print("[sms_log] {}: WARNING scraped {} of {} rows — check the grid columns"
              .format(office, len(rows), total), flush=True)
    return rows, (total, incoming, outgoing)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280",
                    help="one id or a comma list, e.g. 11280,23965,24065")
    ap.add_argument("--owner", default="",
                    help="owner name for the office picker; blank uses the "
                         "newOfficeId hop (one owner only, so pass it per run)")
    ap.add_argument("--dates", default="",
                    help="FROM,TO in MM-DD-YYYY; default the last full Sat-Fri week")
    ap.add_argument("--week", type=int, nargs="?", const=1, default=0,
                    help="1 = the recruiting week just finished, 2 = the one before")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    offices = [o.strip() for o in str(a.office).split(",") if o.strip()]
    if a.dates:
        parts = [s.strip() for s in a.dates.split(",") if s.strip()]
        if len(parts) != 2:
            ap.error("--dates takes exactly FROM,TO in MM-DD-YYYY")
        lo, hi = parts
    else:
        start, end = _recruiting_week(back=a.week or 1)
        lo, hi = _fmt(start), _fmt(end)
    print("[sms_log] offices {} · {} → {}".format(offices, lo, hi), flush=True)

    OUTPUT_DIR.mkdir(exist_ok=True)
    rc = 0
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        tok = _rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the console page")
        for office in offices:
            try:
                rows, totals = pull_office(page, tok, office, a.owner, lo, hi)
            except Exception as e:  # noqa: BLE001 — one office must not kill the rest
                print("[sms_log] {}: FAILED {}: {}".format(
                    office, type(e).__name__, str(e).splitlines()[0][:200]), flush=True)
                rc = 1
                continue
            (OUTPUT_DIR / "sms_log_{}.json".format(office)).write_text(
                json.dumps(rows, indent=1, ensure_ascii=False))
            meta = ("sms_log {:%Y-%m-%d %H:%M} office={} range={}..{} rows={} "
                    "page_total={}".format(dt.datetime.now(), office, lo, hi,
                                           len(rows), totals[0]))
            if a.dry_run:
                print("[sms_log] DRY RUN — no sheet write. " + meta, flush=True)
                continue
            if not rows:
                print("[sms_log] {}: nothing scraped — tab left alone".format(office),
                      flush=True)
                rc = 1
                continue
            tab, n = _write_tab(rows, meta, office)
            print("[sms_log] {}: {} rows → tab '{}'".format(office, n, tab), flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())

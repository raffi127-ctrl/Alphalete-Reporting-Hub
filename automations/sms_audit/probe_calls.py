"""Probe: where does AppStream keep CALL outcomes, and do they carry a time?

Megan 2026-09-26 wants the hour with the highest **phone call answer rate**
beside the hour with the highest text reply rate. The SMS List Report (p=336)
is texts only — it has no call in it — so the call side needs a different
page, and nothing in this repo reads one yet.

The Reports menu lists several candidates (seen on Megan's screen 2026-09-26):
Activity Report, Phone Burner Transactions, Todays Totals, Logins, and the
Retention Report (p=701) which this repo already reads for weekly totals but
which shows No Answers / Left Message 1-2-3 per DAY, not per hour.

This dumps, for one office: every Reports-menu link with its p=, then for each
candidate page the filter form (inputs, buttons, forms) and the grid's header
row plus two sample rows. One queue round trip instead of a guess per round
trip — the same approach that cracked p=336's four date fields.

  lucy rerun probe_calls --machine "Lucy 2"
  ... probe_calls.py --office 11280

READ-ONLY. Writes one control-sheet tab, 'Call Probe <office>'. Delete the
module once the real puller exists.
"""
from __future__ import annotations

import argparse
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill as _fill
from automations.shared.tableau_patchright import appstream_direct_session

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB_PREFIX = "Call Probe"
# What a call page would be called. Deliberately wide: the point of a probe is
# to find out, and a missed page costs another round trip.
HINT = re.compile(r"call|phone|burner|dial|activity|transaction|talk|"
                  r"today.?s total|retention", re.I)
CELL_CAP = 45000


def _rqst(page):
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.url or "")
    if m:
        return m.group(1)
    m = re.search(r"rqst=([A-Za-z0-9_-]+)",
                  page.evaluate("() => document.documentElement.innerHTML") or "")
    return m.group(1) if m else None


def _emit(rows, line):
    print(line[:220], flush=True)
    text = str(line)
    for i in range(0, max(len(text), 1), CELL_CAP):
        rows.append([text[i:i + CELL_CAP]])


def _links(page):
    return page.evaluate(
        r"""() => [...document.querySelectorAll('a')]
              .map(a => ({t: (a.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60),
                          h: a.getAttribute('href') || ''}))
              .filter(x => x.t || x.h)""")


def _page_shape(page):
    """The filter form and the first rows of whatever grid is on the page —
    enough to tell whether it carries a per-call timestamp and an outcome."""
    return page.evaluate(
        r"""() => {
             const q = s => [...document.querySelectorAll(s)];
             const tbl = q('table').filter(t => t.offsetParent !== null
                           && t.querySelectorAll('tr').length > 2)
                          .sort((a, b) => b.innerText.length - a.innerText.length)[0];
             const rowText = tr => [...tr.querySelectorAll('th,td')]
                 .map(c => (c.innerText || '').replace(/\s+/g, ' ').trim()).join(' | ');
             const trs = tbl ? [...tbl.querySelectorAll('tr')] : [];
             return {
               title: document.title,
               inputs: q('input').filter(i => i.type !== 'hidden' || i.value)
                 .slice(0, 25).map(i => i.type + ' ' + (i.name || i.id || '?') +
                                        '=' + (i.value || '').slice(0, 24)),
               buttons: q('button, input[type=submit], input[type=button]')
                 .slice(0, 15).map(b => (b.innerText || b.value || '').trim().slice(0, 30))
                 .filter(Boolean),
               forms: q('form').slice(0, 4).map(f => (f.name || f.id || '?') + ' -> ' +
                        (f.action || '').slice(0, 90)),
               header: trs.length ? rowText(trs[0]) : '(no grid)',
               sample: trs.slice(1, 3).map(rowText),
               rows: trs.length,
             };
           }""")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="probe_calls")
    ap.add_argument("--office", default="11280")
    ap.add_argument("--submit", default="",
                    help="also SUBMIT the date-filtered pages for this date "
                         "(MM-DD-YYYY) and dump what comes back — p=704 and "
                         "p=1520 render an empty grid until you do")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    rows = []
    with appstream_direct_session(verbose=True) as page:
        page.wait_for_timeout(3000)
        tok = _rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the console page")
        page.goto("https://www.applicantstream.com/index.cfm?p=104&rqst={}"
                  "&newOfficeId={}".format(tok, a.office))
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        tok = _rqst(page) or tok
        _emit(rows, "=== office {} · probing for CALL data ===".format(a.office))

        seen, cands = set(), []
        for l in _links(page):
            if not (HINT.search(l["t"]) or HINT.search(l["h"])):
                continue
            m = re.search(r"p=(\d+)", l["h"])
            key = m.group(1) if m else l["h"][:50]
            if key in seen:
                continue
            seen.add(key)
            cands.append((key, l["t"], l["h"]))
            _emit(rows, "LINK p={:<6} {!r}".format(key, l["t"]))

        for key, text, _href in cands:
            if not key.isdigit():
                continue
            try:
                page.goto("https://www.applicantstream.com/index.cfm?rqst={}&p={}"
                          .format(tok, key), wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                shape = _page_shape(page)
            except Exception as e:  # noqa: BLE001 — one bad page must not end the probe
                _emit(rows, "##### p={} ({!r}) — FAILED {}: {}".format(
                    key, text, type(e).__name__, str(e).splitlines()[0][:120]))
                continue
            _emit(rows, "")
            _emit(rows, "##### p={} ({!r}) — {} grid rows".format(key, text, shape["rows"]))
            _emit(rows, "  inputs : {}".format(" | ".join(shape["inputs"])))
            _emit(rows, "  buttons: {}".format(" | ".join(shape["buttons"])))
            _emit(rows, "  forms  : {}".format(" | ".join(shape["forms"])))
            _emit(rows, "  HEADER : {}".format(shape["header"][:600]))
            for smp in shape["sample"]:
                _emit(rows, "  row    : {}".format(smp[:600]))

        # The two pages worth submitting: p=704 Activity Report (date form,
        # Get Report, Download as CSV) and p=1520 Phone Burner Transactions.
        # Both come back empty on a bare load, which is why the first probe
        # could not tell whether they carry a per-call timestamp.
        for pid in ("704", "1520"):
            if not a.submit:
                break
            try:
                page.goto("https://www.applicantstream.com/index.cfm?rqst={}&p={}"
                          .format(tok, pid), wait_until="domcontentloaded",
                          timeout=30000)
                page.wait_for_timeout(2500)
                filled = page.evaluate(
                    r"""(d) => {
                          const ins = [...document.querySelectorAll('input')];
                          const dated = ins.filter(i =>
                            /^\d{2}[-/]\d{2}[-/]\d{4}$/.test((i.value || '').trim())
                            || /date/i.test((i.name || '') + (i.id || '')));
                          dated.forEach(i => {
                            i.value = /\//.test(i.value) ? d.replace(/-/g, '/') : d;
                            i.dispatchEvent(new Event('change', {bubbles: true}));
                          });
                          return dated.map(i => (i.name || i.id || '?') + '=' + i.value)
                                      .join(' | ') || 'no date field';
                        }""", a.submit)
                _emit(rows, "")
                _emit(rows, "##### p={} SUBMITTED for {} — set {}".format(
                    pid, a.submit, filled))
                for name in ("Get Report", "Go", "Search", "Submit"):
                    try:
                        page.get_by_role("button", name=name, exact=False).first.click(
                            timeout=4000)
                        _emit(rows, "  clicked {!r}".format(name))
                        break
                    except Exception:
                        continue
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2500)
                shape = _page_shape(page)
                _emit(rows, "  after submit: {} grid rows".format(shape["rows"]))
                # The Activity column came back holding only "First Interview
                # Date" and "Second Interview Date" — calendar bookings, no
                # call outcome. Before concluding the page cannot answer the
                # call question, read what its OWN filter says it can show:
                # if "No Answer" or "Left Message" is in the dropdown, the
                # report can produce them and the default view simply does
                # not. If it is not there, the page is a booking log.
                opts = page.evaluate(
                    r"""() => [...document.querySelectorAll('select')].map(sel => ({
                          name: sel.name || sel.id || '?',
                          options: [...sel.options].map(o => (o.text || '').trim())
                                     .filter(Boolean).slice(0, 60)}))""")
                for sel in opts:
                    _emit(rows, "  SELECT {}: {}".format(
                        sel["name"], " | ".join(sel["options"])[:900]))
                _emit(rows, "  HEADER : {}".format(shape["header"][:700]))
                for smp in shape["sample"]:
                    _emit(rows, "  row    : {}".format(smp[:700]))
            except Exception as e:  # noqa: BLE001
                _emit(rows, "##### p={} submit FAILED {}: {}".format(
                    pid, type(e).__name__, str(e).splitlines()[0][:140]))

    if a.dry_run:
        print("[probe_calls] DRY RUN — {} lines, no sheet write".format(len(rows)),
              flush=True)
        return 0
    tab = "{} {}".format(TAB_PREFIX, a.office)
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(tab)
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(tab, rows=max(len(rows) + 10, 100), cols=1)
    ws.clear()
    if ws.row_count < len(rows) + 5:
        ws.resize(rows=len(rows) + 5, cols=1)
    ws.update(values=rows, range_name="A1", raw=True)
    print("[probe_calls] wrote {} lines -> '{}'".format(len(rows), tab), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

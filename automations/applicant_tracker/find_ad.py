"""READ-ONLY lookup: which ad did these people apply from?

Walks one office's weekly Retention report (p=701) BACKWARDS from --before,
opens the "Sent to Call List" detail pages (p=715 — First, Last, Email, Phone,
Rating, Job Board, Date and Time, Ad) and prints a FOUND line for every name
matched. Writes nothing anywhere. Built 2026-10-01 for Roshan's sales board:
the org tracker's Call List tab only starts 2026-06-08, so reps hired before
that have no Ad on the sheet and the report is the only place left to look.

    lucy rerun applicant_find_ad --office 19833 --before 2026-06-07 --weeks 24 \
        --names "Emily Garcia;Brianna Scott"

Stops early once every name is found. `logtail applicant_find_ad FOUND` reads
the answers back. Uses the shared rcaptain patchright session (headed — headless
trips Cloudflare) exactly like funnel_board / indeed_source_report.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import datetime as dt
import json
import re
import sys

from automations.shared.tableau_patchright import appstream_direct_session

LABEL = "Sent to Call List"
CARD_ID = "applicant-tracker-sync"

JS_ROW_LINKS = """(label) => {
  const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
  const out = {labels: [], links: [], head: []};
  const trs = [...document.querySelectorAll('tr')];
  if (trs.length) out.head = [...trs[0].children].map(c => c.innerText.trim());
  for (const tr of trs) {
    const f = tr.querySelector('td,th'); if (!f) continue;
    const l = norm(f.innerText); if (l) out.labels.push(l.slice(0, 40));
    if (l.startsWith(norm(label))) {
      [...tr.children].forEach((c, i) => {
        const a = c.querySelector('a');
        if (a) out.links.push([i, c.innerText.trim(), a.getAttribute('href')]);
      });
      break;
    }
  }
  return out;
}"""

JS_TABLE = """() => {
  const tables = [...document.querySelectorAll('table')]; let best = null, n = 0;
  tables.forEach(t => { const r = t.querySelectorAll('tr').length; if (r > n) { n = r; best = t; } });
  if (!best) return {head: [], rows: []};
  const rows = [...best.querySelectorAll('tr')];
  const head = [...rows[0].querySelectorAll('th,td')].map(c => c.innerText.trim());
  const out = [];
  for (let i = 1; i < rows.length; i++) {
    const tds = [...rows[i].querySelectorAll('td')];
    if (tds.length) out.push(tds.map(td => td.innerText.trim()));
  }
  return {head, rows: out};
}"""


def _norm(s):
    return " ".join((s or "").split()).lower()


def _abs(href):
    return href if href.startswith("http") else "https://applicantstream.com/" + href.lstrip("/")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", required=True)
    ap.add_argument("--names", required=True, help="semicolon-separated 'First Last'")
    ap.add_argument("--before", default="2026-06-07", help="last Sunday to look at (YYYY-MM-DD)")
    ap.add_argument("--weeks", type=int, default=24)
    ap.add_argument("--label", default=LABEL)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--fuzzy", action="store_true",
                    help="also print CANDIDATE rows: same last name + first 3 letters of first name")
    a = ap.parse_args(argv)

    want = {_norm(n): n.strip() for n in a.names.split(";") if n.strip()}
    found = {}
    end = dt.datetime.strptime(a.before, "%Y-%m-%d").date()
    start = end - dt.timedelta(days=6)
    print("find_ad: office %s, %d names, weeks back from %s: %d" % (a.office, len(want), end, a.weeks), flush=True)

    with appstream_direct_session(headless=a.headless, verbose=True, allow_form_login=True) as page:
        tok = re.search(r"rqst=([A-Za-z0-9\-]+)", page.url).group(1)
        page.goto("https://applicantstream.com/index.cfm?p=104&rqst=%s&newOfficeId=%s" % (tok, a.office),
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        for w in range(a.weeks):
            wk = start - dt.timedelta(days=7 * w)
            page.goto("https://applicantstream.com/index.cfm?rqst=%s&p=701" % tok,
                      wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector("form[name=frmRR] input[name=weekStart]", timeout=30000)
            except Exception:
                print("NO frmRR on p=701; forms=%r; text=%r" % (
                    page.evaluate("() => [...document.forms].map(f => f.name)"),
                    page.evaluate("() => document.body.innerText.slice(0, 300)")), flush=True)
                break
            page.evaluate("""([slash, dash]) => { const f = document.forms['frmRR'];
                f.startDate2.value = slash; f.weekStart.removeAttribute('readonly');
                f.weekStart.value = dash; HTMLFormElement.prototype.submit.call(f); }""",
                          [wk.strftime("%m/%d/%Y"), wk.strftime("%m-%d-%Y")])
            page.wait_for_load_state("domcontentloaded")
            # The weekly grid renders slowly (funnel_board waits up to 150s on
            # its sibling report). First run read 23 of 24 weeks before the
            # label row existed and saw nothing — poll for the row instead.
            info = {"head": [], "labels": [], "links": []}
            for _ in range(60):
                page.wait_for_timeout(2000)
                info = page.evaluate(JS_ROW_LINKS, a.label)
                if info["links"]:
                    break
            if w == 0:
                print("head=%r labels=%r" % (info["head"], info["labels"][:30]), flush=True)
            links = info["links"]
            print("week of %s: %d linked cells %r" % (wk, len(links), [(c, v) for c, v, _ in links]), flush=True)
            # one page per week when the Weekly Total cell is itself a link
            if links and links[-1][0] < len(info["head"]) and "total" in _norm(info["head"][links[-1][0]]):
                links = [links[-1]]
            for col, cnt, href in links:
                page.goto(_abs(href), wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_selector("table tr", timeout=20000)
                except Exception:
                    pass
                t = page.evaluate(JS_TABLE)
                if w == 0 and col == links[0][0]:
                    print("detail head=%r rows=%d" % (t["head"], len(t["rows"])), flush=True)
                hi = {_norm(h): i for i, h in enumerate(t["head"])}
                fi, li = hi.get("first name", 1), hi.get("last name", 2)
                ai = hi.get("ad", len(t["head"]) - 2)
                for r in t["rows"]:
                    if len(r) <= max(fi, li):
                        continue
                    full = _norm(r[fi] + " " + r[li])
                    if a.fuzzy and full not in want:
                        for k, v in want.items():
                            kf, kl = k.split(" ", 1)[0], k.rsplit(" ", 1)[-1]
                            if _norm(r[li]) == kl and _norm(r[fi])[:3] == kf[:3]:
                                print("CANDIDATE %s ~ %s %s | week of %s | %s" % (
                                    v, r[fi], r[li], wk, r[ai] if ai < len(r) else "?"), flush=True)
                    if full in want and want[full] not in found:
                        found[want[full]] = {"week_of": str(wk), "ad": r[ai] if ai < len(r) else "?",
                                             "row": r[:ai + 1]}
                        print("FOUND %s | week of %s | %s" % (want[full], wk, found[want[full]]["ad"]), flush=True)
            if len(found) == len(want):
                break
    print("RESULT " + json.dumps(found), flush=True)
    print("MISSING " + json.dumps([n for n in want.values() if n not in found]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

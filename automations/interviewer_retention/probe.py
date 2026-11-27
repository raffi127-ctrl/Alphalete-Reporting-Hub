"""READ-ONLY probe: what one office's AppStream calendar day says, row by row.

Card step 1.1 (Interviewer Retention). Opens the Calendar day view (p=102) for
one office and one day and saves, for every section (FIRST INTERVIEWS, SECOND
INTERVIEWS, ...):
  * the column headers,
  * every row, each <select> shown as its CHOSEN option,
  * every option each dropdown offers (Done By, Follow Up Status, ...), so
    the Follow Up Status -> ARS column match can be checked against the real
    list instead of a guess.

Changes nothing in AppStream: it navigates and reads. Writes one JSON file to
output/interviewer_retention/.

    python -m automations.interviewer_retention.probe --office 11280 --date 11-24-2026
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "interviewer_retention"

# For every calendar section table (the ones with a 'Booked By' header): each
# column header that holds a <select>, and the union of the options it offers.
_OPTIONS_JS = """() => {
  const out = [];
  for (const tb of document.querySelectorAll('table')) {
    const hdr = tb.rows[0] ? [...tb.rows[0].cells].map(c => (c.innerText || '').trim()) : [];
    if (hdr.findIndex(h => /booked by/i.test(h)) < 0) continue;
    let section = '';
    for (let el = tb.previousElementSibling; el && !section; el = el.previousElementSibling) {
      const t = (el.innerText || '').trim();
      if (/INTERVIEW|FIRST DAY/i.test(t)) section = t.slice(0, 60);
    }
    const cols = {};
    for (const r of [...tb.rows].slice(1)) {
      [...r.cells].forEach((c, i) => {
        c.querySelectorAll('select').forEach(s => {
          const key = (hdr[i] || ('col' + i)) + (s.name ? ' [' + s.name.replace(/_\\d+$/, '') + ']' : '');
          cols[key] = cols[key] || new Set();
          [...s.options].forEach(o => cols[key].add(o.text.trim()));
        });
      });
    }
    out.push({section, headers: hdr,
              dropdowns: Object.fromEntries(Object.entries(cols).map(([k, v]) => [k, [...v]]))});
  }
  return out;
}"""


def probe(office: str, day: dt.date, headless: bool = True) -> dict:
    from automations.late_join_audit import probe as lj
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.sms_thread_dump import run as dump

    with appstream_direct_session(headless=headless, verbose=True) as page:
        tok = dump._rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the AppStream console page")
        page.goto(f"https://www.applicantstream.com/index.cfm?p=104&rqst={tok}"
                  f"&newOfficeId={office}")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        rows = lj._day_view(page, tok, day)        # [['SECTION'|'ROW', section, cells...]]
        options = page.evaluate(_OPTIONS_JS)
    return {"office": office, "day": day.isoformat(),
            "read_at": dt.datetime.now().isoformat(timespec="seconds"),
            "rows": rows, "dropdowns": options}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="interviewer_retention.probe")
    ap.add_argument("--office", required=True, help="AppStream office id, e.g. 11280")
    ap.add_argument("--date", required=True, help="MM-DD-YYYY")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    a = ap.parse_args(argv)
    day = dt.datetime.strptime(a.date, "%m-%d-%Y").date()
    got = probe(a.office, day, headless=not a.headed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"probe_{a.office}_{day.isoformat()}.json"
    out.write_text(json.dumps(got, indent=1, ensure_ascii=False), encoding="utf-8")
    secs = [r for r in got["rows"] if r[0] == "SECTION"]
    print(f"saved {out}")
    for s in secs:
        n = sum(1 for r in got["rows"] if r[0] == "ROW" and r[1] == s[1])
        print(f"  {s[1]!r}: {n} rows | headers: {s[2:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

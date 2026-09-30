"""Late Join audit -- PROBE: what the AppStream calendar shows for a 1st round.

Before the audit is built (Rafael, 2026-09-30: every "Late Join" is checked
against the booked slot, 5 min grace), this reads one day's First Interview
table for the given offices and writes EVERY cell of every row -- the status
dropdown's chosen value, who set it and when -- to the control sheet tab
"Late Join Probe", so the columns can be read from the laptop.

READ-ONLY on AppStream. Runs on Lucy 2 (the live AppStream session).

    lucy rerun late_join_probe --office 22583,11280 --date 09-30-2026
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.recruiting_report import fill as _fill
from automations.shared.tableau_patchright import appstream_direct_session
from automations.sms_thread_dump import run as dump

TAB = "Late Join Probe"

# every visible row of the expanded day: each cell as text, a <select> as its
# CHOSEN option (innerText would list every option), checked radios marked
_ROWS_JS = """(dstr) => {
  const cell = td => {
    const sel = [...td.querySelectorAll('select')].map(
      s => 'SELECT=' + (s.options[s.selectedIndex] ? s.options[s.selectedIndex].text : ''));
    const radios = [...td.querySelectorAll('input[type=radio]')].map(
      r => (r.checked ? '(x)' : '( )') + (r.value || ''));
    const title = [...td.querySelectorAll('[title]')].map(e => 'TITLE=' + e.title);
    let txt = (td.innerText || '').trim().replace(/\\s+/g, ' ');
    if (sel.length) txt = sel.join(' | ');
    return [txt, ...radios, ...title].filter(Boolean).join(' ; ');
  };
  const out = [];
  for (const tr of document.querySelectorAll('tr')) {
    if (tr.offsetParent === null) continue;
    const tds = [...tr.querySelectorAll(':scope > td, :scope > th')];
    if (tds.length < 7) continue;
    // the day's rows start with the date (sms_thread_dump._day_rows); keep
    // the column header row right above them too
    const first = (tds[0].innerText || '').trim();
    if (first === dstr || (!out.length && /time/i.test(tr.innerText || '') && /name/i.test(tr.innerText || '')))
      out.push(tds.map(cell));
  }
  return out;
}"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="late_join_audit.probe")
    ap.add_argument("--office", default="22583", help="comma list")
    ap.add_argument("--date", default="", help="MM-DD-YYYY (default today)")
    ap.add_argument("--limit", type=int, default=40, help="rows per office")
    a = ap.parse_args(argv)
    day = (dt.datetime.strptime(a.date, "%m-%d-%Y").date() if a.date
           else dt.date.today())
    ds = dump._fmt(day)
    offices = [o.strip() for o in a.office.split(",") if o.strip()]
    rows = [[f"late_join_probe {dt.datetime.now():%Y-%m-%d %H:%M} date={ds} offices={offices}"]]
    with appstream_direct_session(verbose=True) as page:
        tok = dump._rqst(page)
        for office in offices:
            page.goto(f"https://www.applicantstream.com/index.cfm?p=104&rqst={tok}"
                      f"&newOfficeId={office}")
            page.wait_for_load_state("networkidle")
            time.sleep(1.0)
            dump._goto_week_containing(page, tok, day)
            n = dump._expand_day(page, ds)
            got = page.evaluate(_ROWS_JS, ds) if n >= 0 else []
            print(f"[late_join_probe] {office} {ds}: header says {n}, rows {len(got)}", flush=True)
            late = [r for r in got if any("Late" in c for c in r)]
            print(f"[late_join_probe] {office}: {len(late)} rows mention Late", flush=True)
            for r in (got[:a.limit] + [r for r in late if r not in got[:a.limit]]):
                rows.append([office] + r)
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    sh = _fill._client().open_by_key(dump.CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(TAB)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(TAB, rows=max(200, len(rows) + 10), cols=max(26, width))
    ws.update(values=rows, range_name="A1", raw=True)
    print(f"[late_join_probe] {len(rows) - 1} rows -> tab '{TAB}'", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

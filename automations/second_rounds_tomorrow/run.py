"""Second rounds booked for TOMORROW, per org office (Carlos 2026-09-14).

Reads the AppStream Weekly Calendar (p=105) for every org office and counts
the "Second Interview Date: <tomorrow>" band's Applicants number — the same
page/band mechanics sms_thread_dump proved for First Interviews. Read-only on
AppStream; results land on the control sheet tab "SR Tomorrow" (the mini reads
them back and renders the screenshot-style image).

  lucy rerun second_rounds_tomorrow                 # tomorrow, all org offices
  ... run.py --date 09-15-2026 --office 11580       # one office / explicit day
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.shared.tableau_patchright import appstream_direct_session
from automations.funnel_board.roster import ORG
from automations.recruiting_report import fill as _fill

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB = "SR Tomorrow"


def _rqst(page):
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.url or "")
    if not m:
        m = re.search(r"rqst=([A-Za-z0-9_-]+)",
                      page.evaluate("() => document.documentElement.innerHTML") or "")
    return m.group(1) if m else None


def _banner_week(page):
    txt = page.evaluate("() => document.body.innerText") or ""
    m = re.search(r"Calendar for Week:\s*(\d{2}-\d{2}-\d{4})\s*To\s*(\d{2}-\d{2}-\d{4})", txt)
    return (m.group(1), m.group(2)) if m else (None, None)


def _shift_week(page, back):
    ok = page.evaluate(
        """(back) => {
          const btns = Array.from(document.querySelectorAll('a,button,input'));
          const pick = btns.find(b => (b.textContent || b.value || '')
                                 .trim() === (back ? '<' : '>'));
          if (!pick) return 'no arrow';
          pick.click();
          return 'ok';
        }""", back)
    if ok != "ok":
        raise RuntimeError(f"week shift failed: {ok}")
    page.get_by_role("button", name=re.compile("Get Report", re.I)).click()
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)


def _goto_week_containing(page, tok, target):
    page.goto(f"https://www.applicantstream.com/index.cfm?p=105&rqst={tok}")
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)
    for _ in range(6):
        lo, hi = _banner_week(page)
        if not lo:
            raise RuntimeError("no 'Calendar for Week' banner — not on p=105?")
        lo_d = dt.datetime.strptime(lo, "%m-%d-%Y").date()
        hi_d = dt.datetime.strptime(hi, "%m-%d-%Y").date()
        if lo_d <= target <= hi_d:
            return (lo, hi)
        _shift_week(page, back=target < lo_d)
    raise RuntimeError("couldn't reach target week")


def _counts_for(page, date_str):
    """(second, first, band names seen) for one office's loaded calendar."""
    txt = page.evaluate("() => document.body.innerText") or ""
    bands = re.findall(r"([A-Za-z][A-Za-z ]{2,30}) Date: %s\. Applicants: (\d+)"
                       % re.escape(date_str), txt)
    second = first = 0
    for name, n in bands:
        low = name.strip().lower()
        if "second" in low:
            second += int(n)
        elif "first" in low:
            first += int(n)
    return second, first, [b[0].strip() for b in bands]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="MM-DD-YYYY (default: tomorrow)")
    ap.add_argument("--office", default="", help="one office id (default: all org)")
    a = ap.parse_args(argv)

    target = (dt.datetime.strptime(a.date, "%m-%d-%Y").date() if a.date
              else dt.date.today() + dt.timedelta(days=1))
    date_str = target.strftime("%m-%d-%Y")
    offices = [(n, oid) for n, oid, _own in ORG if not a.office or oid == a.office]
    print(f"[sr_tomorrow] {date_str} — {len(offices)} office(s)", flush=True)

    rows, bands_seen = [], set()
    with appstream_direct_session(verbose=True) as page:
        tok = _rqst(page)
        if not tok:
            raise RuntimeError("no rqst token")
        for name, oid in offices:
            try:
                page.goto("https://www.applicantstream.com/index.cfm?p=104"
                          f"&rqst={tok}&newOfficeId={oid}")
                page.wait_for_load_state("networkidle")
                time.sleep(1.0)
                _goto_week_containing(page, tok, target)
                second, first, bands = _counts_for(page, date_str)
                bands_seen.update(bands)
                rows.append([name, second, first])
                print(f"  {name:24s} 2nd={second:<4d} 1st={first}", flush=True)
            except Exception as e:  # noqa: BLE001 — one office must not kill the run
                rows.append([name, "", ""])
                print(f"  {name:24s} FAILED: {str(e).splitlines()[0][:80]}", flush=True)

    print(f"[sr_tomorrow] bands seen: {sorted(bands_seen)}", flush=True)
    sh = _fill.open_by_key(CONTROL_SHEET_ID)
    try:
        ws = sh.worksheet(TAB)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(TAB, rows=60, cols=6)
    ws.update("A1", [[f"second rounds for {date_str}",
                      dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                     ["Manager", "2nd tomorrow", "1st tomorrow"]] + rows,
              raw=True)
    print(f"[sr_tomorrow] wrote {len(rows)} rows to '{TAB}'", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

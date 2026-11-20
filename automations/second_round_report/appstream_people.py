"""Per-person AppStream lists for the 2nd-round report (Carlos 2026-11-19:
"There may be a mismatch on applicant stream with who it says on there that
conducted the interview. If it says Carlos Hidalgo conducted the interview and
it's different on the daily update, that's purposely or intentionally marked
incorrect.").

PULL (needs the AppStream session -> runs on Lucy 2):
    lucy rerun second_round_report --appstream-pull --from 2026-10-26 --through 2026-11-18

Walks Retention Details (p=701) for office 11580 day by day and reads every
detail page (p=715) behind the 2nd-round, offer, brought-on-board and new-start
rows -- names, email, phone, Done By 1st / Done By 2nd, date and time -- into
the control sheet's "2R AppStream Pull" tab (rewritten each pull). The report
reads that tab anywhere; nothing in AppStream is changed.

The office's report week can start on any weekday, so each day is found by its
column header; a day missing from the week on screen opens the week holding it.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Dict, List, Optional

CONTROL_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB = "2R AppStream Pull"
HEADER = ["Day", "Row", "First", "Last", "Email", "Phone", "Done By 1st", "Done By 2nd",
          "Date/Time", "Pulled At"]
# Retention Details rows read (label prefixes, matched like the report reads them).
LABELS = ["Total Second Interviews", "Second Interviews Showed Up", "Offered Job From Second Round",
          "Brought on Board Booked", "Total New Starts Scheduled", "New Starts Showed Up"]

_DATES_JS = r"""() => {
  const out = [];
  document.querySelectorAll('tr').forEach(tr => [...tr.children].forEach(c => {
    const m = (c.innerText || '').match(/([A-Z][a-z]{2}) (\d{1,2}), (\d{4})/);
    if (m) out.push(m[0]);
  }));
  return [...new Set(out)];
}"""
_LABELS_JS = r"""() => [...document.querySelectorAll('tr')].map(tr => {
  const f = tr.querySelector('td,th'); return f ? (f.innerText || '').replace(/\s+/g, ' ').trim() : '';
}).filter(Boolean)"""


def _hdr(d: dt.date) -> str:
    return "%s %d, %d" % (d.strftime("%b"), d.day, d.year)


def _col(h: List[str], *names: str) -> Optional[int]:
    for n in names:
        for i, x in enumerate(h):
            if x == n:
                return i
    for n in names:
        for i, x in enumerate(h):
            if n in x:
                return i
    return None


def _open_on(app, d: dt.date) -> List[str]:
    """Open the report week holding `d`; return the dates on screen."""
    from automations.ad_photo_threads.appstream_ads import open_week
    open_week(app, d)
    app.page.wait_for_timeout(1500)
    return app.page.evaluate(_DATES_JS) or []


def pull(lo: dt.date, hi: dt.date, office: str = "11580", log=print) -> List[List[str]]:
    from automations.applicant_tracker.applicantstream import session
    from automations.linkedin_2nd_round_contacts.run import _READ_TABLE, _count
    days = [lo + dt.timedelta(days=i) for i in range((hi - lo).days + 1)]
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    rows: List[List[str]] = []
    with session() as app:
        owner = app.select_office(office)
        log("[2R pull] office %s = %s, %s .. %s" % (office, owner, lo, hi))
        todo = list(days)
        shown_labels = None
        while todo:
            d0 = todo[0]
            on_screen = set(_open_on(app, d0))
            if shown_labels is None:
                shown_labels = app.page.evaluate(_LABELS_JS)
                have = [l for l in LABELS if any(s.lower().startswith(l.lower()) for s in shown_labels)]
                log("[2R pull] report rows found: %s" % have)
                missing = [l for l in LABELS if l not in have]
                if missing:
                    log("[2R pull] NOT on this report: %s" % missing)
            here = [d for d in todo if _hdr(d) in on_screen]
            if not here:
                raise RuntimeError("the report week opened for %s doesn't show it (on screen: %s)"
                                   % (d0, sorted(on_screen)[:8]))
            hrefs = [(d, lbl, app.detail_href(lbl, _hdr(d))) for d in here for lbl in LABELS]
            for d, lbl, h in hrefs:
                n = _count(h) if h else 0
                if not n:
                    continue
                app._goto_detail(h)
                t = app.page.evaluate(_READ_TABLE)
                h_ = [" ".join((x or "").lower().split()) for x in t["header"]]
                fi, li = _col(h_, "first name"), _col(h_, "last name")
                ei, pi = _col(h_, "email"), _col(h_, "phone")
                b1, b2 = _col(h_, "done by 1st"), _col(h_, "done by 2nd")
                ti = _col(h_, "interview date/time", "date and time", "date/time")
                got = 0
                for r in t["rows"]:
                    g = lambda i: (r[i] if i is not None and i < len(r) else "").strip()
                    if not (g(fi) or g(li)):
                        continue
                    got += 1
                    rows.append([d.isoformat(), lbl, g(fi), g(li), g(ei), g(pi), g(b1), g(b2), g(ti), stamp])
                if got < n:
                    log("[2R pull] %s %s: cell says %d, page listed %d" % (d, lbl, n, got))
            todo = [d for d in todo if d not in here]
            log("[2R pull] %s .. %s read (%d rows so far)" % (here[0], here[-1], len(rows)))
    return rows


def write_tab(rows: List[List[str]], log=print) -> None:
    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(CONTROL_SHEET)
    try:
        ws = sh.worksheet(TAB)
    except Exception:  # noqa: BLE001 -- first pull: make the tab
        ws = sh.add_worksheet(title=TAB, rows=max(100, len(rows) + 10), cols=len(HEADER))
    _retry(lambda: ws.clear())
    if ws.row_count < len(rows) + 5:
        ws.add_rows(len(rows) + 5 - ws.row_count)
    _retry(lambda: ws.update("A1", [HEADER] + rows, value_input_option="RAW"))
    log("[2R pull] wrote %d row(s) to '%s'" % (len(rows), TAB))


def read_tab() -> List[Dict[str, str]]:
    """The last pull, as dicts keyed by HEADER. [] when there is no tab yet."""
    from automations.recruiting_report.fill import open_by_key, _retry
    try:
        ws = open_by_key(CONTROL_SHEET).worksheet(TAB)
    except Exception:  # noqa: BLE001
        return []
    vals = _retry(lambda: ws.get("A1:J5000"))
    if not vals:
        return []
    hdr = vals[0]
    return [dict(zip(hdr, list(r) + [""] * len(hdr))) for r in vals[1:] if r]


def loose(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")[-10:]

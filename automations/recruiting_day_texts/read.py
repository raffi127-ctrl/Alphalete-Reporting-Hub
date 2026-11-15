"""Today's column of one office's Retention Details -> a Day.

A row that is MISSING from the report raises (never read as zero). A cell
whose link says count=0 is a proven zero ([[feedback_empty_means_proven_zero]]).
A detail page that lists fewer people than its cell's count also raises: a
half-read schedule texted to an owner is worse than no text.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.recruiting_day_texts import config as C


@dataclass
class Day:
    day: dt.date
    owner: str
    first: List[Tuple[dt.time, str]] = field(default_factory=list)
    second: List[Tuple[dt.time, str]] = field(default_factory=list)
    ns_scheduled: List[str] = field(default_factory=list)
    ns_showed: List[str] = field(default_factory=list)
    # {'first last' lowercase: start time} from the calendar; {} = not read
    ns_times: Dict[str, dt.time] = field(default_factory=dict)

    def ns_with_times(self) -> List[Tuple[Optional[dt.time], str]]:
        """New starts sorted by start time; anyone without one goes last."""
        got = [(self.ns_times.get(" ".join(n.lower().split())), n)
               for n in self.ns_scheduled]
        return sorted(got, key=lambda p: (p[0] is None, p[0] or dt.time(0), p[1]))

    def slots(self, which: str) -> List[Tuple[dt.time, int]]:
        """[(time, count)] sorted by time -- the Timeslot Count layout."""
        counts: Dict[dt.time, int] = {}
        for t, _ in getattr(self, which):
            counts[t] = counts.get(t, 0) + 1
        return sorted(counts.items())


_TIME = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*([AP]M)", re.I)


def parse_when(s: str) -> Optional[Tuple[dt.date, dt.time]]:
    """'11/13/2026 8:15 AM' -> (date, time). None if it isn't one."""
    m = _TIME.search(s or "")
    if not m:
        return None
    mo, d, y, h, mi, ap = m.groups()
    h = int(h) % 12 + (12 if ap.upper() == "PM" else 0)
    return dt.date(int(y), int(mo), int(d)), dt.time(h, int(mi))


def _col(header: List[str], *names: str) -> int:
    for n in names:
        if n in header:
            return header.index(n)
    for i, h in enumerate(header):           # e.g. '1st interview date/time'
        if any(n in h for n in names):
            return i
    raise RuntimeError("detail table has no %s column (header: %s)"
                       % (" / ".join(names), header))


def names_of(header: List[str], rows: List[List[str]]) -> List[str]:
    fi, li = _col(header, "first name"), _col(header, "last name")
    out, seen = [], set()
    for r in rows:
        n = ("%s %s" % (r[fi] if fi < len(r) else "",
                        r[li] if li < len(r) else "")).strip()
        n = " ".join(w[:1].upper() + w[1:] for w in n.split())
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def timed(header: List[str], rows: List[List[str]], day: dt.date,
          label: str) -> List[Tuple[dt.time, str]]:
    ti = _col(header, "interview date/time", "date/time")
    fi, li = _col(header, "first name"), _col(header, "last name")
    out = []
    for r in rows:
        got = parse_when(r[ti] if ti < len(r) else "")
        if not got:
            raise RuntimeError("%s: no interview time for %s %s (%r)"
                               % (label, r[fi], r[li], r[ti] if ti < len(r) else ""))
        if got[0] != day:
            raise RuntimeError("%s: %s %s is on %s, not %s -- wrong column?"
                               % (label, r[fi], r[li], got[0], day))
        out.append((got[1], ("%s %s" % (r[fi], r[li])).strip()))
    return sorted(out)


def read_day(app, office: C.Office, day: dt.date, labels=C.LABELS,
             log=print) -> Day:
    """`app` = applicant_tracker ApplicantStream session. Needs `day` in the
    report's current week (the report renders only that week)."""
    from automations.linkedin_2nd_round_contacts.run import (_READ_TABLE, _count,
                                                             date_header)
    owner = app.select_office(office.appstream_id)
    app.open_retention_details()
    hdr = date_header(day)
    hrefs = {}
    for lbl in labels:
        h = app.detail_href(lbl, hdr)
        if h is None:
            raise RuntimeError("%s (%s): no %r cell for %s on Retention Details"
                               % (office.owner, office.appstream_id, lbl, hdr))
        hrefs[lbl] = h
    out = Day(day=day, owner=owner or office.owner)
    for lbl, h in hrefs.items():
        n = _count(h)
        if not n:
            log("  %s: 0" % lbl)
            continue
        app._goto_detail(h)
        t = app.page.evaluate(_READ_TABLE)
        if len(t["rows"]) < n:
            raise RuntimeError("%s: cell says %d, detail page listed %d"
                               % (lbl, n, len(t["rows"])))
        if lbl == C.L_FIRST:
            out.first = timed(t["header"], t["rows"], day, lbl)
        elif lbl == C.L_SECOND:
            out.second = timed(t["header"], t["rows"], day, lbl)
        elif lbl == C.L_NS_SCHED:
            out.ns_scheduled = names_of(t["header"], t["rows"])
        elif lbl == C.L_NS_SHOWED:
            out.ns_showed = names_of(t["header"], t["rows"])
        log("  %s: %d" % (lbl, n))
    return out


# ---------------------------------------------------------- the usual ----

def average(vals: List[int]) -> float:
    """Mean of the days the office was OPEN. A 0 on a past weekday is a closed
    day (a holiday, a shut office), not a slow one -- counting it would make a
    normal day look high and hide a real drop."""
    open_days = [v for v in vals if v > 0]
    return sum(open_days) / float(len(open_days)) if open_days else 0.0


# ------------------------------------------------- 7am-vs-7am history ----
# WHY NOT THE FINAL COUNTS (checked 2026-11-15, Raf's office): 1st rounds are
# mostly booked THE SAME DAY -- last Monday ended at 210, while the Monday
# calendar the day before held 27. AppStream's detail page has no "booked at"
# time, so a past day's 7am count cannot be rebuilt. A morning read compared
# with a full day's total would turn red every day. So the alert compares this
# morning with this office's own EARLIER MORNINGS, recorded on Lucy 1 (it sends
# every text, so it sees every morning). No alert until MIN_HISTORY mornings.
MORNINGS = Path.home() / ".config" / "recruiting-report" / "recruiting_day_texts_mornings.json"


def _mornings_load() -> Dict[str, Dict[str, int]]:
    try:
        return json.loads(MORNINGS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def morning_record(office: C.Office, d: "Day") -> None:
    """Keep today's 7am counts (one entry per office per day; a resend
    overwrites, never doubles)."""
    m = _mornings_load()
    m["%s|%s" % (office.appstream_id, d.day.isoformat())] = {
        "first": len(d.first), "second": len(d.second)}
    cut = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    m = {k: v for k, v in m.items() if k.rsplit("|", 1)[-1] >= cut}
    try:
        MORNINGS.parent.mkdir(parents=True, exist_ok=True)
        MORNINGS.write_text(json.dumps(m), encoding="utf-8")
    except Exception:  # noqa: BLE001 -- costs one day of history, never a text
        pass


def morning_usual(office: C.Office, day: dt.date,
                  weeks: int = C.LOOKBACK_WEEKS) -> Dict[str, float]:
    """{'first': avg, 'second': avg} of this office's 7am counts on the same
    weekday over the last `weeks` weeks. A count with fewer than MIN_HISTORY
    open mornings behind it is left out -- no alert beats a guessed one."""
    m = _mornings_load()
    out = {}
    for key in ("first", "second"):
        vals = []
        for w in range(1, weeks + 1):
            e = m.get("%s|%s" % (office.appstream_id,
                                 (day - dt.timedelta(days=7 * w)).isoformat()))
            if e is not None:
                vals.append(int(e.get(key) or 0))
        if len([v for v in vals if v > 0]) >= C.MIN_HISTORY:
            out[key] = average(vals)
    return out


def low_flags(d: Day, avg: Optional[Dict[str, float]]) -> Dict[str, float]:
    """{'first': avg, ...} for each count that is clearly below its usual."""
    if not avg:
        return {}
    out = {}
    for key in ("first", "second"):
        a = avg.get(key) or 0
        if a >= C.LOW_MIN_AVG and len(getattr(d, key)) < C.LOW_SHARE * a:
            out[key] = a
    return out


# --------------------------------------------------- hand-off to Lucy 1 ----

def to_payload(office: C.Office, mode: str, d: Day,
               avg: Optional[Dict[str, float]] = None) -> Dict:
    return {"office": office.key, "mode": mode, "day": d.day.isoformat(),
            "owner": d.owner,
            "first": [[t.strftime("%H:%M"), n] for t, n in d.first],
            "second": [[t.strftime("%H:%M"), n] for t, n in d.second],
            "ns_scheduled": d.ns_scheduled, "ns_showed": d.ns_showed,
            "ns_times": {k: v.strftime("%H:%M") for k, v in d.ns_times.items()},
            "usual": avg or {}}


def from_payload(p: Dict) -> Tuple[C.Office, str, Day, Dict[str, float]]:
    def tt(s):
        h, m = s.split(":")
        return dt.time(int(h), int(m))
    d = Day(day=dt.date.fromisoformat(p["day"]), owner=p["owner"],
            first=[(tt(a), b) for a, b in p["first"]],
            second=[(tt(a), b) for a, b in p["second"]],
            ns_scheduled=list(p["ns_scheduled"]), ns_showed=list(p["ns_showed"]),
            ns_times={k: tt(v) for k, v in (p.get("ns_times") or {}).items()})
    return C.office(p["office"]), p["mode"], d, dict(p.get("usual") or {})


# ------------------------------------------------ new-start times (calendar) --

# Calendar (p=102) section headings that hold first days. Each heading is its own
# small table; the rows are the NEXT table whose header has Time + First Name
# (seen on Atef's 11/14 calendar). Columns are found by header name.
NS_SECTIONS = ("FIRST DAY OF TRAINING", "FIRST DAY OF SALES")

_CAL_FIRST_DAYS = r"""(sections) => {
    const norm = s => (s||'').replace(/\s+/g,' ').trim();
    const out = []; let section = null;
    for (const t of document.querySelectorAll('table')) {
        const txt = norm(t.innerText);
        const head = sections.find(s => txt.toUpperCase().startsWith(s));
        if (head && txt.length < 200 && t.querySelectorAll('tr').length <= 2) {
            section = head; continue;
        }
        if (!section) continue;
        const trs = [...t.querySelectorAll('tr')];
        const hdr = trs.length ? [...trs[0].children].map(c => norm(c.innerText).toLowerCase()) : [];
        const ti = hdr.findIndex(h => h === 'time' || h.startsWith('time'));
        const fi = hdr.findIndex(h => h.startsWith('first name'));
        const li = hdr.findIndex(h => h.startsWith('last name'));
        if (ti < 0 || fi < 0) continue;
        for (const tr of trs.slice(1)) {
            const c = [...tr.children].map(x => norm(x.innerText));
            if (!c[fi]) continue;
            out.push({section, time: c[ti] || '',
                      first: (c[fi] || '').split(' ')[0] ? c[fi] : '',
                      last: li >= 0 ? (c[li] || '') : ''});
        }
        section = null;
    }
    return out;
}"""


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def parse_clock(s: str) -> Optional[dt.time]:
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", s or "", re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
    return dt.time(h, int(m.group(2)))


def new_start_times(app, office: C.Office, day: dt.date, log=print) -> Dict[str, dt.time]:
    """{'first last' (lowercase): start time} from TODAY's calendar.

    Only today: the calendar opens on today, and moving it takes the script-tag
    trick ([[reference_appstream_calendar_reads]]) -- not worth it for a morning
    text that is always about today. Raises when the page cannot be read; the
    caller then shows names without times rather than guessing."""
    if day != dt.date.today():
        raise RuntimeError("calendar times are only read for today")
    # A browser pop-up on the calendar blocks every later page call with no
    # timeout -- a probe sat 20 minutes on Atef's on 2026-11-14. Dismiss any.
    if not getattr(app, "_rdt_dialog_guard", False):
        app.page.on("dialog", lambda d: d.dismiss())
        app._rdt_dialog_guard = True
    app.select_office(office.appstream_id)
    app.open_calendar()
    app.page.wait_for_timeout(2500)
    body = app.page.evaluate("() => document.body.innerText")
    want = day.strftime("%m-%d-%Y")
    if want not in (body or ""):
        raise RuntimeError("calendar is not showing %s" % want)
    rows = app.page.evaluate(_CAL_FIRST_DAYS, list(NS_SECTIONS))
    out: Dict[str, dt.time] = {}
    for r in rows:
        t = parse_clock(r.get("time", ""))
        name = ("%s %s" % (r.get("first", ""), r.get("last", ""))).strip()
        if t and name and _key(name) not in out:
            out[_key(name)] = t
    log("  new-start times on the calendar: %d" % len(out))
    return out

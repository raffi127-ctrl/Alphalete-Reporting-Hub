"""Tomorrow's 1st and 2nd round interviews, by time slot, for the 7 PM post.

THE ASK (Raf, Loom 2026-11-13, on the Daily Focus thread): "Can we also get a
breakdown of what time slots we have for the next day scheduled for first and
second ... total first interviews, second interviews ... so that everyone knows
what really the second round schedule is for the next day."

Source: AppStream -> Calendar -> Weekly Calendar (p=105), the
"First Interview Date: <d>" and "Second Interview Date: <d>" bands of each of
the office's calendars -- same page and click mechanics as sms_thread_dump and
second_rounds_tomorrow. READ-ONLY on AppStream. Times are the office's own.

"Next day" = the next weekday (Mon-Fri): the Friday post shows Monday, the same
way the report itself is a Mon-Fri board.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from collections import Counter
from typing import Dict, Iterable, Optional

BANDS = (("first", "First Interview"), ("second", "Second Interview"))


def next_day(today: dt.date) -> dt.date:
    """The next Mon-Fri date after `today`."""
    d = today + dt.timedelta(days=1)
    while d.weekday() > 4:
        d += dt.timedelta(days=1)
    return d


def _clock(s: str) -> Optional[dt.time]:
    try:
        return dt.datetime.strptime((s or "").strip().upper(), "%I:%M %p").time()
    except ValueError:
        return None


def _band_count(page, band: str, ds: str) -> int:
    txt = page.evaluate("() => document.body.innerText") or ""
    m = re.search(r"%s Date: %s\. Applicants: (\d+)" % (re.escape(band), re.escape(ds)), txt)
    return int(m.group(1)) if m else 0


def _band_rows(page, band: str, ds: str):
    """Expand one band and read its table. The day's rows all carry the same
    date in cell 0 whichever band they sit under, so only ONE band is ever open
    at a time -- the caller reloads the week before the next band."""
    page.get_by_text(f"{band} Date: {ds}.", exact=False).first.click()
    time.sleep(1.0)
    return page.evaluate(
        """(dstr) => {
             const out = [];
             document.querySelectorAll('tr').forEach(tr => {
               const tds = [...tr.querySelectorAll('td')];
               if (tds.length < 7 || tr.offsetParent === null) return;
               const c = tds.map(td => (td.innerText || '').trim());
               if (c[0] !== dstr) return;
               out.push({time: c[1], name: c[2]});
             });
             return out;
           }""", ds)


def read(day: dt.date, offices: Iterable[str]) -> Dict:
    """{'first': {time: n}, 'second': {...}, 'totals': {'first': n, 'second': n},
    'problems': [str]} across every office calendar given.

    Totals come off the band header ("Applicants: N"), which AppStream counts
    itself; the per-slot split comes off the table. If the table showed fewer
    rows than the header, the gap is listed as a problem (and lands as an
    'unknown time' line) rather than silently shrinking the total."""
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.sms_thread_dump import run as dump

    ds = day.strftime("%m-%d-%Y")
    slots = {k: Counter() for k, _ in BANDS}
    totals = {k: 0 for k, _ in BANDS}
    problems = []
    read_ok = 0
    offices = list(offices)
    with appstream_direct_session(verbose=False) as page:
        tok = dump._rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the AppStream console page")
        for office in offices:
            try:
                page.goto("https://www.applicantstream.com/index.cfm?p=104"
                          f"&rqst={tok}&newOfficeId={office}")
                page.wait_for_load_state("networkidle")
                time.sleep(1.0)
                for key, band in BANDS:
                    dump._goto_week_containing(page, tok, day)
                    n = _band_count(page, band, ds)
                    if not n:
                        continue
                    rows = _band_rows(page, band, ds)
                    totals[key] += n
                    for r in rows:
                        slots[key][r["time"] or "?"] += 1
                    if len(rows) < n:
                        slots[key]["?"] += n - len(rows)
                        problems.append(f"{office} {band}: table showed "
                                        f"{len(rows)} of {n}")
                read_ok += 1
            except Exception as exc:  # noqa: BLE001 -- one office can't hold the rest
                problems.append(f"{office}: {type(exc).__name__}: "
                                f"{str(exc).splitlines()[0][:120]}")
    if not read_ok:
        raise RuntimeError("no AppStream calendar could be read: "
                           + "; ".join(problems))
    if read_ok < len(offices):
        # a partial count posted as if complete is worse than a late one
        raise RuntimeError("calendar read incomplete: " + "; ".join(problems))
    return {"first": dict(slots["first"]), "second": dict(slots["second"]),
            "totals": totals, "problems": problems}


def _sort_key(t: str):
    c = _clock(t)
    return (c is None, c or dt.time(0), t)


def format_text(day: dt.date, data: Dict) -> str:
    """Slack reply: one line per time slot, 1st and 2nd side by side, totals
    on top. Monospace block so the columns line up on a phone."""
    first, second = data.get("first") or {}, data.get("second") or {}
    tot = data.get("totals") or {}
    head = (f"*Interviews booked for {day:%a} {day.month}/{day.day}*\n"
            f"1st rounds: *{tot.get('first', 0)}*   ·   "
            f"2nd rounds: *{tot.get('second', 0)}*")
    times = sorted(set(first) | set(second), key=_sort_key)
    if not times:
        return head + "\nNothing booked yet."
    lines = [f"{'Time':<10}{'1st':>5}{'2nd':>5}"]
    for t in times:
        label = "no time" if t == "?" else t
        lines.append(f"{label:<10}{first.get(t, 0) or '-':>5}{second.get(t, 0) or '-':>5}")
    lines.append(f"{'Total':<10}{tot.get('first', 0):>5}{tot.get('second', 0):>5}")
    return head + "\n```" + "\n".join(lines) + "```"


def screenshot(day: dt.date, office: str, out_png) -> Dict:
    """Picture of one office's Weekly Calendar for `day`, with that day's 1st
    and 2nd round bands BOTH open (Raf 2026-11-13: "a 2nd post that grabs the
    LinkedIn screenshot of what's booked for the next day" -- office 24226,
    'Linkedin Test', per Megan). READ-ONLY on AppStream.

    Returns {'first': n, 'second': n} off the band headers so the caption can
    say the counts even when the picture is long. A day with nothing booked
    still gets a picture: an empty calendar IS the answer."""
    from pathlib import Path
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.sms_thread_dump import run as dump

    ds = day.strftime("%m-%d-%Y")
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    with appstream_direct_session(verbose=False) as page:
        tok = dump._rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the AppStream console page")
        page.goto("https://www.applicantstream.com/index.cfm?p=104"
                  f"&rqst={tok}&newOfficeId={office}")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        dump._goto_week_containing(page, tok, day)
        for key, band in BANDS:
            counts[key] = _band_count(page, band, ds)
            if counts[key]:
                page.get_by_text(f"{band} Date: {ds}.", exact=False).first.click()
                time.sleep(1.0)
        # Hide every OTHER day's rows: one day's open band would otherwise sit
        # in a picture of the whole week. Rows are matched by the date in
        # cell 0, the same way _band_rows reads them.
        page.evaluate(
            """(dstr) => {
                 document.querySelectorAll('tr').forEach(tr => {
                   const tds = [...tr.querySelectorAll('td')];
                   if (tds.length < 7) return;
                   const c0 = (tds[0].innerText || '').trim();
                   if (/^\d\d-\d\d-\d{4}$/.test(c0) && c0 !== dstr)
                     tr.style.display = 'none';
                 });
               }""", ds)
        time.sleep(0.5)
        page.screenshot(path=str(out_png), full_page=True)
    return counts


def screenshot_caption(day: dt.date, counts: Dict) -> str:
    return (f"*LinkedIn (AppStream 24226) booked for {day:%a} "
            f"{day.month}/{day.day}*\n1st rounds: *{counts.get('first', 0)}*   ·   "
            f"2nd rounds: *{counts.get('second', 0)}*")

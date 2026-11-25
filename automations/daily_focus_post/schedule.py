"""Tomorrow's 1st and 2nd round interviews, by time slot, one post per funnel.

WHERE (Raf, Loom 2026-11-18): under the day's "Daily Update M/D" thread, one
reply per AppStream funnel (Main / El Paso / AI / LinkedIn), 2nd rounds on
top with a morning/afternoon split, 1st rounds below. Older ask below.

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


def read(day: dt.date, offices: Iterable[str]) -> Dict[str, Dict]:
    """{office: {'first': {time: n}, 'second': {...}, 'totals': {...},
    'problems': [str]}} -- or {office: {'error': str}} for a calendar that
    couldn't be read. One AppStream session for all of them; each funnel is
    its own post, so one bad calendar never holds the others.

    Totals come off the band header ("Applicants: N"), which AppStream counts
    itself; the per-slot split comes off the table. If the table showed fewer
    rows than the header, the gap lands as a 'no time' line rather than
    silently shrinking the total."""
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.sms_thread_dump import run as dump

    ds = day.strftime("%m-%d-%Y")
    out: Dict[str, Dict] = {}
    with appstream_direct_session(verbose=False) as page:
        tok = dump._rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the AppStream console page")
        for office in offices:
            slots = {k: Counter() for k, _ in BANDS}
            totals = {k: 0 for k, _ in BANDS}
            problems = []
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
            except Exception as exc:  # noqa: BLE001 -- one office can't hold the rest
                out[office] = {"error": f"{type(exc).__name__}: "
                                        f"{str(exc).splitlines()[0][:120]}"}
                continue
            out[office] = {"first": dict(slots["first"]),
                           "second": dict(slots["second"]),
                           "totals": totals, "problems": problems}
    return out


def _sort_key(t: str):
    c = _clock(t)
    return (c is None, c or dt.time(0), t)


def _am_pm(slots: Dict[str, int]):
    clocks = [(_clock(t), n) for t, n in slots.items()]
    am = sum(n for c, n in clocks if c is not None and c.hour < 12)
    pm = sum(n for c, n in clocks if c is not None and c.hour >= 12)
    return am, pm


# One color per funnel so the four replies tell apart at a glance (Megan,
# 2026-11-19: "headers labeling which accounts ... color coding so the red
# numbers are main funnel, blue are linked in, green is AI" -- but keep it
# TEXT, not a picture). Slack can't color text, so a colored dot leads the
# header and each round line. El Paso got no color from Megan: orange.
FUNNEL_DOT = {
    "Main": ":red_circle:",
    "LinkedIn": ":large_blue_circle:",
    "AI": ":large_green_circle:",
    "El Paso": ":large_orange_circle:",
}


def format_funnel(day: dt.date, label: str, office: str, data: Dict) -> str:
    """One funnel's reply. 2nd rounds FIRST and on their own (Raf 2026-11-18:
    "I want to separate the first and the second round ... just look at the
    second round slots, clean cut"), each round with a morning / afternoon
    count so "is the afternoon full?" is answered at a glance. Monospace
    block so the columns line up on a phone."""
    tot = data.get("totals") or {}
    dot = FUNNEL_DOT.get(label, ":white_circle:")
    head = (f"{dot} *{label.upper()} FUNNEL* ({office}) \u2014 interviews "
            f"booked for *{day:%a} {day.month}/{day.day}*")
    if not (tot.get("first") or tot.get("second")):
        return head + "\nNothing booked yet."
    parts = [head]
    for key, name in (("second", "2nd rounds"), ("first", "1st rounds")):
        slots = data.get(key) or {}
        n = tot.get(key, 0)
        if not n:
            parts.append(f"{dot} *{name}: 0*")
            continue
        am, pm = _am_pm(slots)
        parts.append(f"{dot} *{name}: {n}*   "
                     f"(morning {am} \u00b7 afternoon {pm})")
        lines = [f"{'no time' if t == '?' else t:<10}{slots[t]:>4}"
                 for t in sorted(slots, key=_sort_key)]
        parts.append("```" + "\n".join(lines) + "```")
    return "\n".join(parts)


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
            r"""(dstr) => {
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


def screenshot_caption(day: dt.date, counts: Dict, office: str = "24226") -> str:
    return (f"*LinkedIn ({office}) calendar for {day:%a} "
            f"{day.month}/{day.day}*\n2nd rounds: *{counts.get('second', 0)}*"
            f"   \u00b7   1st rounds: *{counts.get('first', 0)}*")

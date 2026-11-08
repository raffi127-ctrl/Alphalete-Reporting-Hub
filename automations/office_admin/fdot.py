"""Who started this week: ApplicantStream Calendar -> FIRST DAY OF TRAINING
-> Show Up = Yes.

Megan 2026-11-06, with a screenshot of Raf's real calendar: "Prob anyone marked
as showed up on the training calendar for that week on app stream" ... "it would
only be sent to those marked showed up on that week".

WHY THIS EXISTS. New Starts -> Apex reads its roster off the ORG sales board's
'New Starts/Raf' box and leans on the OBCL for start dates. No other office has
either ("No other office uses the OBCL so we will need to find another way to
pull the correct reps"). The training calendar does: it belongs to an
ApplicantStream account, so it is per-office for free, and it is the same page
`offered.py` already reads for background checks.

ONE CONDITION, AND IT IS NOT THE OBVIOUS ONE. The rows also carry a Follow Up
Status (Cancelled / Confirmed / Booked Today - Confirmed / Called) and it is
tempting to read 'Cancelled' as "did not start". Megan: "it's just if they are
scheduled to start" -- it describes the APPOINTMENT, not the outcome. Show Up
is the outcome. So Show Up = Yes is the whole rule and nothing else is
consulted.

SHOW UP IS A PAIR OF RADIO BUTTONS, not a dropdown. `offered.py` reads a
<select id="sOfferPosition">; this is a different control and none of that code
transfers. The checked radio in the Show Up COLUMN is what is read -- the
column found by its header text, then that cell's radios.

THE SECTION MATTERS MORE THAN USUAL. The same page carries FIRST DAY OF SALES
(empty on the screenshot: "No First Day of Sales found for 11-02-2026") and
other banners. Taking the wrong one would create payroll records for people who
have not started, so a read that cannot find the training banner RAISES. An
empty list means the page was read and nobody showed; it never means "we could
not tell".

A WEEK IS SEVEN READS. The calendar is per-day -- index.cfm?p=102 with
cd=MM/DD/YYYY -- so Monday to Sunday are fetched in turn and pooled,
de-duplicated by email. All seven, not Mon-Sat: Megan, 2026-11-08, "Monday to
Friday, actually all 7 days". A training day nobody expected is exactly the one
that would be missed. Somebody rescheduled inside the week appears twice (No on Monday, Yes on
Wednesday); a Yes on any day wins, and one row per person is what stops a
second payroll record for a real employee.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

SECTION = "FIRST DAY OF TRAINING"

# -> {ok, error, rows: [{first, last, phone, email, show, section, had_control}]}
#
# The banner regex and the header-by-text rule are deliberately the same shape
# as offered.READ_JS: one page, two readers, and a layout change should break
# both in the same recognisable way rather than one of them silently.
READ_JS = r"""(want) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const banner = /^([A-Z0-9 &]*?(INTERVIEWS?|ORIENTATIONS?|TRAINING|SALES))\b/;
  const out = [];
  let section = '', header = null, sawSection = false;

  // Yes / No off the CHECKED radio. Its own label where there is one, then the
  // text immediately beside it, then its value -- in that order, because
  // value is the one most likely to be a 1/0 that tells us nothing.
  const radioWord = inp => {
    if (inp.labels && inp.labels.length) {
      const t = norm(inp.labels[0].innerText);
      if (t) return t;
    }
    const lab = inp.closest('label');
    if (lab) {
      const t = norm(lab.innerText);
      if (t) return t;
    }
    let n = inp.nextSibling;
    while (n) {
      const t = norm(n.textContent);
      if (t) return t;
      n = n.nextSibling;
    }
    return norm(inp.value);
  };

  for (const n of document.querySelectorAll('tr, td, th, div, span, h1, h2, h3, h4, b, strong')) {
    if (n.tagName !== 'TR') {
      if (n.querySelector('tr')) continue;
      const m = norm(n.innerText).match(banner);
      if (m && m[1] !== section) {
        section = m[1];
        header = null;
        if (section.indexOf(want) === 0) sawSection = true;
      }
      continue;
    }
    if (n.querySelector('tr')) continue;          // a layout row, not a data row
    const cells = [...n.children];
    const texts = cells.map(c => norm(c.innerText));
    const low = texts.map(t => t.toLowerCase().replace(/[^a-z ]/g, '').trim());
    if (low.includes('first name') && low.includes('email')) {
      if (header) section = '';     // a second header = a banner we missed
      header = {};
      for (const k of ['first name', 'last name', 'phone', 'email', 'show up']) {
        const i = low.indexOf(k);
        if (i >= 0) header[k] = i;
      }
      continue;
    }
    if (!header) continue;
    // The Show Up control, in the Show Up COLUMN -- not "any radio on the row",
    // which would pick up whatever else the office adds later.
    let show = '', had = false;
    if ('show up' in header && header['show up'] < cells.length) {
      const radios = [...cells[header['show up']].querySelectorAll('input[type=radio]')];
      had = radios.length > 0;
      const on = radios.find(r => r.checked);
      if (on) show = radioWord(on);
    }
    if (!had && !texts.some(t => t)) continue;    // spacer row
    const at = k => (k in header && header[k] < texts.length) ? texts[header[k]] : '';
    const first = at('first name');
    if (!first) continue;
    out.push({first: first, last: at('last name'), phone: at('phone'),
              email: at('email'), show: show, section: section, had_control: had});
  }
  if (!sawSection) return {ok: false, error: 'no "' + want + '" banner on the calendar', rows: out};
  return {ok: true, rows: out};
}"""


def _in_section(row: Dict) -> bool:
    return str(row.get("section", "")).upper().startswith(SECTION)


def check_rows(rows: List[Dict]) -> None:
    """Refuse a read we cannot trust.

    Training rows on the page but no Show Up control found in ANY of them means
    the column moved or the markup changed -- not that nobody showed up. The
    difference matters: one is "nobody started this week", the other is a
    silently empty roster.
    """
    mine = [r for r in rows if _in_section(r)]
    if mine and not any(r.get("had_control") for r in mine):
        raise RuntimeError(
            "%d rows under %s but no Show Up control in any of them -- the "
            "column moved or the page changed." % (len(mine), SECTION))


def showed_up(rows: List[Dict]) -> List[Dict]:
    """Training rows marked Show Up = Yes, one per person."""
    out, seen = [], set()
    for r in rows:
        if not _in_section(r):
            continue
        if str(r.get("show", "")).strip().lower() != "yes":
            continue
        first = str(r.get("first") or "").strip()
        last = str(r.get("last") or "").strip()
        email = str(r.get("email") or "").strip()
        phone = re.sub(r"\D", "", str(r.get("phone") or ""))[-10:]
        if not first:
            continue
        # Email where there is one -- it is proof, and the Blue Ink match
        # downstream reports `matched_on` for exactly this reason. Name plus
        # phone is the fallback, not the default.
        key = email.lower() or (first.lower(), last.lower(), phone)
        if key in seen:
            continue
        seen.add(key)
        out.append({"first_name": first, "last_name": last, "email": email,
                    "phone": phone, "stage": "Showed up (first day of training)"})
    return out


def read(app, office_id: str, day: dt.date, log=print) -> List[Dict]:
    """One day's showed-up training rows for one office.

    `app` is an applicant_tracker ApplicantStream session. RAISES when the
    calendar cannot be read; an empty list means it WAS read and nobody showed.
    """
    from automations.raf_daily_update.run import _CAL_NAV_JS
    app.select_office(office_id)
    app.open_calendar()
    app.page.wait_for_timeout(10000)                   # rows render late
    if day != dt.date.today():
        app.page.evaluate(_CAL_NAV_JS, day.strftime("%m/%d/%Y"))
        app.page.wait_for_timeout(15000)
        want = "found for %s" % day.strftime("%m-%d-%Y")
        on_day = app.page.evaluate("(w) => document.body.innerText.includes(w)", want)
        if not on_day:
            # That phrase only appears for a section with nothing in it, so its
            # absence is not proof of a failed move -- check the date box too
            # before calling it a failure.
            shown = app.page.evaluate(
                "() => { const i = document.querySelector('input[value*=\"-\"]');"
                " return i ? i.value : ''; }")
            if day.strftime("%m-%d-%Y") not in str(shown):
                raise RuntimeError("the calendar would not move to %s" % day)
    got = app.page.evaluate(READ_JS, SECTION)
    if not got.get("ok"):
        raise RuntimeError("training calendar: %s" % got.get("error"))
    rows = got.get("rows") or []
    check_rows(rows)
    people = showed_up(rows)
    log("  %s: %d training rows, %d showed up" % (
        day, sum(1 for r in rows if _in_section(r)), len(people)))
    return people


def read_week(app, office_id: str, week_start: dt.date, log=print,
              days: int = 7) -> List[Dict]:
    """Monday to Sunday of one week, pooled and de-duplicated.

    Every day is read. A day that cannot be read raises rather than being
    skipped quietly -- a missing Tuesday is a missing new start, and the first
    anybody would hear of it is a rep with no payroll record.
    """
    monday = week_start - dt.timedelta(days=week_start.weekday())
    out: List[Dict] = []
    for i in range(days):
        out.extend(read(app, office_id, monday + dt.timedelta(days=i), log=log))
    pooled = showed_up([{"first": p["first_name"], "last": p["last_name"],
                         "phone": p["phone"], "email": p["email"],
                         "show": "Yes", "section": SECTION} for p in out])
    log("  week of %s: %d showed up (%d rows before de-duplicating)"
        % (monday, len(pooled), len(out)))
    return pooled


def main(argv=None) -> int:
    """Read-only check: who started this week, as this would see it.

        python -m automations.office_admin.fdot --office 11280
        python -m automations.office_admin.fdot --office 11280 --week 2026-11-02
        python -m automations.office_admin.fdot --office 11280 --date 2026-11-02
    """
    import argparse
    ap = argparse.ArgumentParser(
        description="Who showed up for first day of training (read-only).")
    ap.add_argument("--office", required=True, help="ApplicantStream office id, e.g. 11280")
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week to read")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD, one day only")
    args = ap.parse_args(argv)
    from automations.applicant_tracker.applicantstream import session
    with session() as app:
        if args.date:
            people = read(app, args.office, dt.date.fromisoformat(args.date))
        else:
            start = (dt.date.fromisoformat(args.week) if args.week
                     else dt.date.today())
            people = read_week(app, args.office, start)
    for p in people:
        print("  %-28s %-12s %s" % ("%s %s" % (p["first_name"], p["last_name"]),
                                    p["phone"], p["email"] or "(no email)"))
    print("%d showed up" % len(people))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""READ-ONLY: what the calendar page ACTUALLY says after we drive it to a day.

WHY THIS EXISTS. read_calendar decides it arrived by testing the page for one
literal string -- "found for MM-DD-YYYY". For Cyrus (22815) on 2026-11-16 that
test fails on every run (08:10, 08:32 and 12:38 on 2026-11-19, two drives each
the last time), so the day is abandoned and Shawn Gunnoe, Alexis Ochoa and
Cameron Simpson come out with no start date. Megan looked at that day in
ApplicantStream on 2026-11-19: it HAS second-round rows. So the day is not
empty and the read is wrong about something.

Testing for one expected string cannot say WHY it is missing. This prints what
is really there: the date the page names, every "... for <date>" phrase it
carries, whether our marker is present, and how many rows each section has.

CHANGES NOTHING. One office, one page, no writes, nothing clicked.

    lucy rerun daily_update_calday_probe 22815 2026-11-16
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

PHRASES_JS = r"""() => {
    const t = document.body.innerText || '';
    const dates = [...t.matchAll(/([A-Za-z' ]{3,30})\s+for\s+(\d{2}-\d{2}-\d{4})/g)]
        .map(m => m[0].trim());
    const heads = [...document.querySelectorAll('tr')]
        .map(tr => (tr.innerText || '').replace(/\s+/g, ' ').trim())
        .filter(x => /FIRST DAY OF TRAINING|SECOND INTERVIEW|FIRST INTERVIEW/i.test(x))
        .slice(0, 8);
    return {
        picker: (document.querySelector('#topLevelDatePicker') || {}).value || '',
        title: (t.split('\n').find(l => /Calendars?\s+for/i.test(l)) || '').trim(),
        phrases: [...new Set(dates)].slice(0, 25),
        sections: heads,
        rows: document.querySelectorAll('tr').length,
    };
}"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("office_pos", nargs="?", default="22815")
    ap.add_argument("date_pos", nargs="?", default="2026-11-16")
    args = ap.parse_args(argv)
    office, day = args.office_pos, dt.date.fromisoformat(args.date_pos)

    from automations.applicant_tracker.applicantstream import session
    from automations.office_admin.cal_nav import CAL_NAV_JS

    with session() as app:
        print("office %s -> %s" % (office, app.select_office(office)))
        app.open_calendar()
        app.page.wait_for_timeout(10000)
        print("opens on picker=%r" % app.page.evaluate(
            "() => (document.querySelector('#topLevelDatePicker')||{}).value || ''"))

        status = app.page.evaluate(CAL_NAV_JS, day.strftime("%m/%d/%Y"))
        print("CAL_NAV_JS said: %r" % status)
        app.page.wait_for_timeout(15000)

        want = "found for %s" % day.strftime("%m-%d-%Y")
        here = app.page.evaluate(
            "(w) => document.body.innerText.includes(w)", want)
        print("\nour marker %r present? %s" % (want, here))

        info = app.page.evaluate(PHRASES_JS)
        print("\npicker now : %r" % info["picker"])
        print("title line : %r" % info["title"])
        print("total <tr> : %d" % info["rows"])
        print("\nEVERY '... for <date>' PHRASE ON THE PAGE:")
        for p in info["phrases"] or ["(none)"]:
            print("   %r" % p)
        print("\nSECTION HEADER ROWS:")
        for h in info["sections"] or ["(none)"]:
            print("   %s" % h[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())

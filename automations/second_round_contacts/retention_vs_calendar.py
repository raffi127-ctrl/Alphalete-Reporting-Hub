"""READ-ONLY: does the Retention Details report agree with the calendar?

WHY THIS EXISTS. Megan, 2026-11-19, over the Retention Details report: Raf had
"51 2nd interviews scheduled" and "32 showed". The calendar read for 11/18 came
back 50 rows, 23 showed, with 0 rows skipped -- so the gap is NOT a parsing
loss, and a plausible story ("probably a different day") is not evidence.

So this asks both sources the same question and prints them side by side:

  1. THE REPORT, DAY BY DAY. For every day of this week it reads the cell where
     'Total Second Interviews' / 'Second Interviews Showed Up' meets that day's
     column. The count lives in the cell's own link (count=<n>), so this needs
     one report load and no clicking. If one column says 51/32 and the next
     says 50/23, the two numbers were simply read off two different days and
     there is nothing wrong with either source.

  2. THE PEOPLE, NOT THE COUNT. For the day asked about it opens the
     'Second Interviews Showed Up' detail page and dumps the names, because a
     count that matches can still be a different set of people.

  3. THE CALENDAR, SAME DAY. It then reads the Second Interviews table with the
     SAME reader the 6pm nudge uses and diffs the two name lists both ways.
     Whoever is on one side and not the other is named.

CHANGES NOTHING. One office, two read-only pages, no writes, nothing clicked.

    PYTHONPATH=. .venv/bin/python -m \\
        automations.second_round_contacts.retention_vs_calendar --office 11280

Office and date are positional too, which is the form the mini can pass
(`lucy rerun` hands extra args through as positionals and its own argparse
eats anything starting with "-"):

    lucy rerun second_round_retention_vs_calendar 11280 2026-11-18
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

from automations.second_round_contacts import config as C
from automations.second_round_contacts.second_interviews import (
    ROW_JS, name_of, shown_date, showed_up)


def week_of(d: dt.date):
    """Sunday .. Saturday around `d` -- the report's own column window."""
    sunday = d - dt.timedelta(days=(d.weekday() + 1) % 7)
    return [sunday + dt.timedelta(days=i) for i in range(7)]


def parse_shown(shown) -> "dt.date | None":
    """The calendar's own date string -> a date. It writes the picker value
    ('11/18/2026') when the picker is there and a long form
    ('Wednesday, November 18, 2026') when it is not, so both are accepted
    rather than assuming the one we happened to see."""
    # Drop a leading weekday ONLY -- lstrip() with a letter set would eat the
    # month name too and leave "18, 2026".
    text = re.sub(r"^\s*[A-Za-z]+day\s*,?\s*", "",
                  str(shown or "").strip())
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y",
                "%B %d %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("office_pos", nargs="?", default=None)
    ap.add_argument("date_pos", nargs="?", default=None)
    ap.add_argument("--office", default=None)
    ap.add_argument("--date", default=None,
                    help="the day to compare name-by-name "
                         "(default: whatever day the calendar lands on)")
    args = ap.parse_args(argv)

    office = args.office or args.office_pos or "11280"
    when = args.date or args.date_pos
    asked = dt.date.fromisoformat(when) if when else None

    from automations.linkedin_2nd_round_contacts.run import _count, date_header
    from automations.applicant_tracker.applicantstream import session

    with session() as app:
        owner = app.select_office(office)
        print("office %s -> %s" % (office, owner))

        # ---- 1. the report, column by column -------------------------------
        app.open_retention_details()
        days = week_of(asked or dt.date.today())
        print("\n=== RETENTION DETAILS, DAY BY DAY ===")
        print("   %-16s %6s %6s" % ("", "booked", "showed"))
        grid = {}
        for d in days:
            hdr = date_header(d)
            held = _count(app.detail_href(C.LABEL_HELD, hdr))
            shw = _count(app.detail_href(C.LABEL_SHOWED, hdr))
            grid[d] = (held, shw)
            print("   %-16s %6d %6d"
                  % (d.strftime("%a %b ") + str(d.day), held, shw))

        # ---- 2. which day the calendar is actually on ----------------------
        app.open_calendar()
        cal_day = shown_date(app)
        print("\ncalendar is showing: %s" % cal_day)
        data = app.page.evaluate(ROW_JS)
        if data.get("error"):
            print("\nCALENDAR READ REFUSED: %s" % data["error"])
            return 1
        rows = data["rows"]
        cal_all = sorted(name_of(r) for r in rows)
        cal_showed = sorted(name_of(r) for r in rows if showed_up(r))
        print("   heading %r -- %d row(s), %d marked showed up"
              % (data.get("section"), len(cal_all), len(cal_showed)))

        # The comparison day is the one the CALENDAR is on: that is the only
        # day both sources can be asked about in one pass, because
        # open_calendar_for cannot be driven on this page.
        day = asked or parse_shown(cal_day)
        if day is None:
            print("\n(could not read the calendar's date, so no name diff)")
            return 0

        # ---- 3. the same day's names, off the report -----------------------
        # BOTH hrefs come off ONE report load: detail_href does not navigate,
        # so collecting first and visiting after costs two page loads instead
        # of four (the same reason read_lists does it this way).
        app.open_retention_details()
        hdr = date_header(day)
        href_all = app.detail_href(C.LABEL_HELD, hdr)
        href_showed = app.detail_href(C.LABEL_SHOWED, hdr)
        rep_all = sorted(app.names_at(href_all))
        rep_showed = sorted(app.names_at(href_showed))

        print("\n=== %s: REPORT vs CALENDAR ===" % hdr)
        print("   booked   report %3d   calendar %3d" % (len(rep_all), len(cal_all)))
        print("   showed   report %3d   calendar %3d" % (len(rep_showed), len(cal_showed)))

        def diff(title, a, b, a_name, b_name):
            only_a = sorted(set(a) - set(b))
            only_b = sorted(set(b) - set(a))
            print("\n   %s" % title)
            if not only_a and not only_b:
                print("      the SAME people on both sides")
                return
            for n in only_a:
                print("      %-28s on %s, NOT on %s" % (n, a_name, b_name))
            for n in only_b:
                print("      %-28s on %s, NOT on %s" % (n, b_name, a_name))

        diff("BOOKED", rep_all, cal_all, "the report", "the calendar")
        diff("SHOWED UP", rep_showed, cal_showed, "the report", "the calendar")

        # Anyone the report counts as showed but the calendar does not is the
        # whole question: print what the calendar's own cells say about them.
        by_name = {name_of(r): r for r in rows}
        missing = sorted(set(rep_showed) - set(cal_showed))
        if missing:
            print("\n   WHAT THE CALENDAR SAYS ABOUT THE ONES IT DID NOT COUNT")
            for n in missing:
                r = by_name.get(n)
                if not r:
                    print("      %-28s is not on the calendar at all" % n)
                    continue
                raw = r.get("show_raw") or {}
                print("      %-28s showed=%-8s offer=%-5s status=%r action=%r"
                      % (n, r.get("showed") or "-", r.get("offered") or "-",
                         r.get("status"), r.get("action")))
                print("      %-28s show-up cell=%r" % ("", raw.get("text", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

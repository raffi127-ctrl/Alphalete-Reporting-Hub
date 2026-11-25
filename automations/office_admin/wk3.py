"""Who is in WEEK 3 of starting -- the people whose drug test goes out now.

RAF SAID WHEN, AND IT IS NOT WITH THE BACKGROUND CHECK. Asked on 2026-11-24
whether the drug test could ride along on the BGC press, Rafael Hidalgo:

    "If we send the drug test with the background check, it'll cause
     confusion, it'll need resent because the applicant won't find it / if
     they're new and they take it, the owner gets charged more money.
     we like doing the drug test on WK3 of starting
     so I think a button to send it would be great."

Three separate reasons, and each one rules out the shared press on its own:
the invite goes stale before anybody looks for it, a test taken in week 1
bills the owner again in week 3, and a second email arriving the same hour as
the background check is the one people ignore. So this is its OWN list, its
own button and its own Sterling order.

WHICH WEEK, EXACTLY. Week 1 is the week somebody started -- their First Day
Of Training. Week 3 is therefore the week beginning FOURTEEN DAYS after that
week began, so the people to send to today are the ones whose training week
started two weeks ago. `start_week_for` does that arithmetic in one place so
no caller has to count Sundays.

SUNDAY-START, like everything else that reads this calendar. ApplicantStream's
own Retention Report reads a week of 11-08-2026 as 11/08 to 11/14, and
`shared.onboarding_week.week_start_of` is the one implementation of that.
Counting weeks from a Monday here would put a Saturday classroom in the wrong
week and send somebody their drug test seven days early.

THE LIST IS SHOWED-UP ONLY. It comes from `fdot`, which reads FIRST DAY OF
TRAINING with Show Up = Yes -- the same read that feeds payroll. Somebody who
booked training and never came has no start date, so there is no week 3 to
count to. A read that cannot find the training banner RAISES there and so
raises here: an empty list means the calendar was read and nobody started
that week, and it never means "we could not tell".

WHAT THIS DOES NOT DO. It does not know who already has a drug test. Sterling
refuses to invite the same email twice (portal-map.md), so a repeat press is
refused at the far end rather than silently double-billing -- but the admin
still sees the whole week and ticks, which is why `already_sent` is reported
beside each person rather than quietly filtered out. Somebody who needs a
re-send is exactly the person a filter would hide.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

# Week 1 is the week they started; week 3 begins 14 days later. One constant,
# because "three weeks" is said as a number of weeks and written as a number
# of days, and that is where an off-by-seven lives.
WEEKS_AFTER_START = 2
DAYS_BEFORE = WEEKS_AFTER_START * 7


def start_week_for(day: Optional[dt.date] = None) -> dt.date:
    """The Sunday of the TRAINING week whose people are in week 3 on `day`.

    >>> start_week_for(dt.date(2026, 11, 25)).isoformat()   # a Wednesday
    '2026-11-08'

    That is the Sunday two weeks before this one: somebody who started in the
    week of 11/08 is in their third week during the week of 11/22.
    """
    from automations.shared.onboarding_week import week_start_of
    return week_start_of(day or dt.date.today()) - dt.timedelta(days=DAYS_BEFORE)


def find(office, *, today: Optional[dt.date] = None, session=None,
         log=print) -> List[Dict]:
    """The week-3 people for one office, off its own ApplicantStream calendar.

    Returns fdot's rows unchanged ({first_name, last_name, phone, email}) with
    `start_week` added, so the page can say which week it is showing without
    recomputing it. RAISES when the calendar cannot be read.
    """
    from automations.office_admin import fdot
    if session is None:
        from automations.applicant_tracker.applicantstream import session
    sunday = start_week_for(today)
    with session() as app:
        rows = fdot.read_week(app, office.appstream_id, sunday, log=log)
    out = []
    for r in rows:
        p = dict(r)
        p["start_week"] = sunday.isoformat()
        out.append(p)
    log("  week 3 of the week starting %s: %d person(s)" % (sunday, len(out)))
    return out

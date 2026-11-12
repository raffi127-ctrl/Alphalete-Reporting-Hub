"""Which Sunday a day belongs to -- the onboarding board's week, in one place.

MOVED HERE 2026-11-11 so it can SHIP. `office_admin.fdot` reads a week of the
training calendar on an OFFICE computer, and it was reaching into
`icd_onboarding.board` for this. That package is ours: its siblings read Google
Sheets, which an office Mac has no access to.

Pure, and imports nothing. `icd_onboarding.board` re-exports both names, so
every existing caller is unchanged.
"""
from __future__ import annotations

import datetime as dt


def week_start_of(day: dt.date) -> dt.date:
    """The SUNDAY of the week that `day` falls in.

    Sunday to Saturday, not Monday to Sunday (Megan, 2026-11-09: "I want to see
    every new start scheduled for that week Sunday - Sat"). Training runs on
    Saturdays, so a Monday-start week splits a Saturday classroom off from the
    week it belongs to and the person lands on the wrong sheet.

    IT IS ALSO APPLICANTSTREAM'S OWN WEEK, which is the reason to keep it.
    Its Retention Report takes a week of 11-08-2026 and heads the columns
    "11/08/2026 11/14/2026 -- Nov 8 Sunday ... Nov 14 Saturday" (Megan sent the
    page, 2026-11-09). The board is seeded off that calendar, so a board week
    that disagreed with it would put people one column out from the report
    anybody would check this against.
    """
    return day - dt.timedelta(days=(day.weekday() + 1) % 7)


def week_label(week_start: dt.date) -> str:
    """'11/08/2026' -- the Sunday, which is what the Week of column holds."""
    return week_start_of(week_start).strftime("%m/%d/%Y")

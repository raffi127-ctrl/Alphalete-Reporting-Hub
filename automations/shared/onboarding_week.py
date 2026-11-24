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


def tab_name(week_start: dt.date) -> str:
    """The per-week tab for a week, named for its MONDAY the way the OBCL names
    its own -- 'OBCL 11.23'.

    MOVED HERE 2026-11-24 so it can SHIP, for the same reason `week_start_of`
    was. `icd_onboarding.relay_board` is the only way an office's own computer
    reaches its board, and it needs this one name; it was reaching into
    `icd_onboarding.book`, whose siblings open Google Sheets -- which that
    machine has no access to at all. `book` re-exports it, so every existing
    caller is unchanged.

    TWO CONVENTIONS MEET HERE AND THEY ARE A DAY APART. The board's `Week of`
    column holds the SUNDAY (`week_label`), because the week runs Sunday to
    Saturday to match ApplicantStream's Retention Report. The OBCL names its
    tabs for the MONDAY -- "D2D OBCL 11.23" is the week those people start. So
    the tab is the Sunday PLUS one, not the calendar Monday on or before the
    date.

    Subtracting `weekday()` is the obvious thing and it is wrong: a Sunday has
    weekday 6, so 11/15 would land on OBCL 11.9 -- a week early, and every row
    filed against the wrong week.
    """
    monday = week_start_of(week_start) + dt.timedelta(days=1)
    return "OBCL %d.%d" % (monday.month, monday.day)

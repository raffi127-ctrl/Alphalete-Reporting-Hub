"""Where the Wednesday New Starts fill reads and writes.

ONE BOX, THREE SOURCES:
  col 'Trainers'  <- 'Line Up WE <m>.<d>' (same workbook), the blue
                     'Is Training / New Start Name' box
  col 'Location'  <- 'All in One Local Office - Raf', tab 'D2D OBCL <m>.<d>'
                     of the week's MONDAY
  col 'Team'      <- the TRAINER's team, off the sales board's own roster

Nothing here is a row or a column NUMBER. Every one is a row-1 / header-row
LABEL, because the box moves down the tab every week (r178 on WE 9.13, r186 on
WE 9.6) and the roster grows sideways all week.
[[feedback_no_hardcoded_columns]]
"""
from __future__ import annotations

import datetime as dt

# The sales board -- same workbook the 5-minute sweep writes.
from automations.alphalete_sales_board.config import SPREADSHEET_ID  # noqa: F401

# 'All in One Local Office - Raf' -- the recruiting book. Its 'D2D OBCL <m>.<d>'
# tabs are one per classroom Monday and carry the applicant's home city.
OBCL_BOOK_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
OBCL_TAB_PREFIX = "D2D OBCL"

# The line-up tab lives in the SALES BOARD workbook, one per week, titled with
# the same Sunday the board tab uses.
LINEUP_TAB_PREFIX = "Line Up WE"

# --- labels, not coordinates ------------------------------------------------
BOX_TITLE = "New Starts/Raf"       # col C, one row above the box's header row
BOX_NAME_LABEL = "Classroom"       # the header over the new starts' names
BOX_TRAINER_LABEL = "Trainers"
BOX_LOCATION_LABEL = "Location"
BOX_TEAM_LABEL = "Team"

ROSTER_TEAM_LABEL = "Team"         # row 1 of the roster block

LINEUP_TRAINER_LABEL = "Is Training"
LINEUP_NEWSTART_LABEL = "New Start Name"

OBCL_FIRST_LABEL = "Name"
OBCL_LAST_LABEL = "Last Name"
OBCL_LOCATION_LABEL = "Location"


def week_ending(day: dt.date) -> dt.date:
    """The Sunday that closes `day`'s Mon-Sun week -- the tab-title date."""
    return day + dt.timedelta(days=6 - day.weekday())


def week_monday(day: dt.date) -> dt.date:
    """The Monday that opens `day`'s week -- the OBCL tab-title date.

    Wednesday's classroom intake is named for the MONDAY it started, which is
    what Eve means by 'la fecha del ultimo lunes'. On a Monday that is today.
    """
    return day - dt.timedelta(days=day.weekday())


def board_tab(day: dt.date) -> str:
    s = week_ending(day)
    return "Sales Board WE %d.%d" % (s.month, s.day)


def lineup_tab(day: dt.date) -> str:
    s = week_ending(day)
    return "%s %d.%d" % (LINEUP_TAB_PREFIX, s.month, s.day)


def obcl_tab(day: dt.date) -> str:
    m = week_monday(day)
    return "%s %d.%d" % (OBCL_TAB_PREFIX, m.month, m.day)

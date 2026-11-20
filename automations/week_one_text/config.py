"""Week-table texts off the Vantura Sales Boards (Carlos 2026-11-19), to the
NEW A Players chain, Monday-Friday:

* 10:45 AM -- WEEK 1 (shot "week1"), cut at TODAY's day column. Carlos:
  "every day at 10:45 a.m., Monday through Friday, I want a screenshot like
  this of the week ones. The screenshot should end at whatever the current
  day is ... it should be sent on the A Players text chain." His sample =
  B56:H62 on a Thursday: title row to last rep, Roll Call across to Thu.
* 11:30 AM -- WEEK 1 through WEEK 4 (shot "weeks"), the whole table width
  (through Date Gone / Prior Weeks / Total Sales / Trainer). Carlos: "at
  11:30 a.m., I want the screenshot of week 1, week 2, week 3, and week 4
  for both AT&T and Verizon."

Both shots go out for BOTH boards: AT&T (the NDS Sales Board) and Verizon
("you'll do it both for AT&T and Verizon").
"""
from __future__ import annotations

import os
from pathlib import Path

_PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura master
SHEET_ID = os.environ.get("SALES_BOARD_SHEET_ID", _PROD_SHEET_ID)

# board key -> the tab and the name the text uses (Carlos says "AT&T" for NDS).
BOARDS = {
    "nds": {"tab": "NDS Sales Board", "label": "AT&T"},
    "verizon": {"tab": "Verizon Sales Board", "label": "Verizon"},
}
BOARD_ORDER = ["nds", "verizon"]

SHOTS = ["week1", "weeks"]
SEND_TIMES = {"week1": (10, 45), "weeks": (11, 30)}
WEEKS_SHOWN = 4               # the "weeks" shot: WEEK 1 .. WEEK 4, never TERMINATED

# (board, shot) -> routing key in b2b_dispositions.config.TEXT_ROUTES.
ROUTES = {
    ("nds", "week1"): ("NDS WEEK 1", "nds_week_one"),
    ("verizon", "week1"): ("VZ WEEK 1", "vz_week_one"),
    ("nds", "weeks"): ("NDS WEEKS 1-4", "nds_weeks"),
    ("verizon", "weeks"): ("VZ WEEKS 1-4", "vz_weeks"),
}

WEEKDAYS = [0, 1, 2, 3, 4]              # Monday .. Friday (python weekday)
DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]

LABEL_COL = 2                 # column B: the tables' titles, headers and names
READ_RANGE = "A1:N400"        # the reps, the boxes and the week tables

STATE_PATH = Path.home() / ".config" / "recruiting-report" / "week_one_text_state.json"

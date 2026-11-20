"""NDS Week 1 text (Carlos 2026-11-19): every weekday at 10:45 AM, a picture
of the NDS Sales Board's WEEK 1 table -- the new starts' roll call -- texted
to the NEW A Players chain.

Carlos: "So every day at 10:45 a.m., Monday through Friday, I want a
screenshot like this of the week ones. The screenshot should end at whatever
the current day is. So tomorrow, the screenshot should go all the way up
until Friday, and it should be sent on the A Players text chain."

"Like this" = his own crop: the table's title row down to its last rep, from
Roll Call across to TODAY's day column (Thursday's shot stops at Thu).
"""
from __future__ import annotations

import os
from pathlib import Path

# Routing key in b2b_dispositions.config.TEXT_ROUTES -> [NEW A Players].
CAMPAIGN_LABEL = "NDS WEEK 1"
KIND = "nds_week_one"

_PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura master
SHEET_ID = os.environ.get("SALES_BOARD_SHEET_ID", _PROD_SHEET_ID)
TAB = "NDS Sales Board"

SEND_TIME = (10, 45)
WEEKDAYS = [0, 1, 2, 3, 4]              # Monday .. Friday (python weekday)
DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]

LABEL_COL = 2                 # column B: the table's title, header and names
READ_RANGE = "A1:N400"        # the reps, the boxes and the week tables

STATE_PATH = Path.home() / ".config" / "recruiting-report" / "week_one_text_state.json"

"""Where the birthdays live, who gets the reminder, and what it says.

SCOPE: RAF'S OFFICE ONLY (Megan, 2026-09-13). Not an org-wide report. The
suppression data this leans on -- the 'Terminated Reps' tab and the weekly sales
board -- is only populated for Raf (945 of the 1,002 2026 termination rows), so
pointing this at another office would silently lose its safety net.
"""
from __future__ import annotations

import os
from automations.shared.workbooks import ALL_IN_ONE_RAF

# --- the birthday store -----------------------------------------------------
# 'All in One Local Office - Raf' -- the same workbook as 'Terminated Reps', so
# the store and the suppression list are one open/auth away from each other.
STORE_SHEET_ID = ALL_IN_ONE_RAF
STORE_TAB = "DOB LUCY"

# Column titles, row 1. Everything is found BY LABEL -- never by index -- so a
# column inserted by hand doesn't rot the report. [[no hardcoded rows or columns]]
COL_NAME = "Rep Name"
COL_MMDD = "Birthday (MM/DD)"
COL_SOURCE = "Source"
COL_ADDED = "Added"
COL_SKIP = "Skip"          # a person types anything here to opt out. Never ours.
COL_NOTES = "Notes"
# Added 2026-10-21 (Algemar Kennel's birthday AND 1-year anniversary went by
# with nothing from Lucy). Both optional: a tab without them still loads.
#   Start Date  full M/D/YYYY -- the year IS needed here, it is the "N years".
#               Filled from the sales board's own 'Start Date' column; typed by
#               hand for staff, who are not on the board.
#   Staff       anything typed = admin/leadership, not a rep. They never appear
#               on the sales board, so the board check would always skip them;
#               a person marking them Staff is the evidence instead.
COL_START = "Start Date"
COL_STAFF = "Staff"
HEADERS = [COL_NAME, COL_MMDD, COL_SOURCE, COL_ADDED, COL_SKIP, COL_NOTES,
           COL_START, COL_STAFF]

# --- where the reminder goes ------------------------------------------------
# The admin-staff iMessage group, as a NAME NEEDLE for text_post.resolve_group
# (case-insensitive substring; it raises on 0 or 2+ hits rather than guessing).
# Never a chat.db ROWID/GUID: those name a DIFFERENT room on a different Mac,
# which is why every send resolves by name afresh.
#
# Set 2026-09-13 from Megan's screenshot of the chat: it is titled "Admin Staff"
# (party-popper icon). Kept as a NEEDLE, not a GUID, so it resolves fresh on
# whichever Lucy runs the job.
#
# *** THIS REPORT RUNS ON LUCY 1. *** Megan, 2026-09-13: "lucy is in the imessage
# chat. I'm not. So it needs to run on Lucy 1." Verified there the same day --
# find_groups("Admin Staff") returns exactly one chat, 9 participants. It does
# NOT resolve from Megan's laptop (14 other groups do, including all three
# Alphalete ones), so a run from anywhere else fails at resolution. That failure
# is correct and loud, never a silent skip.
GROUP_ADMIN_STAFF = os.environ.get("BIRTHDAY_GROUP", "Admin Staff").strip()

# The reminder fires the DAY BEFORE, so there is a day to get the photo.
DAYS_AHEAD = 1

# Emoji go in as REAL characters -- iMessage renders ':cake:' literally.
CAKE = "\U0001F382"

# Where the photo goes once somebody has it (Megan, 2026-09-13). Named in the
# TEXT only -- this report posts nothing to Slack itself, so this is a label a
# person reads, not a channel id to resolve.
SOCIAL_CHANNEL = "#alphaletesocialmedia"

# --- the same-day Slack shout-out (Eve, 2026-10-21: "a y b") ------------------
# Posted AS Lucy on the day itself, in #alphalete-sales (Eve's pick, same day)
# -- the channel the Sales Board and Production posts already go to. Channel id,
# not a name. Set BIRTHDAY_SLACK_CHANNEL="" to switch the post off.
SLACK_CHANNEL = os.environ.get("BIRTHDAY_SLACK_CHANNEL", "C068PH3RFSM").strip()

HUB_CARD = "Birthday Reminders"
HUB_REPORT_ID = "birthday_reminders"

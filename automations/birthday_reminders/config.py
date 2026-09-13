"""Where the birthdays live, who gets the reminder, and what it says.

SCOPE: RAF'S OFFICE ONLY (Megan, 2026-09-13). Not an org-wide report. The
suppression data this leans on -- the 'Terminated Reps' tab and the weekly sales
board -- is only populated for Raf (945 of the 1,002 2026 termination rows), so
pointing this at another office would silently lose its safety net.
"""
from __future__ import annotations

import os

# --- the birthday store -----------------------------------------------------
# 'All in One Local Office - Raf' -- the same workbook as 'Terminated Reps', so
# the store and the suppression list are one open/auth away from each other.
STORE_SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
STORE_TAB = "DOB LUCY"

# Column titles, row 1. Everything is found BY LABEL -- never by index -- so a
# column inserted by hand doesn't rot the report. [[no hardcoded rows or columns]]
COL_NAME = "Rep Name"
COL_MMDD = "Birthday (MM/DD)"
COL_SOURCE = "Source"
COL_ADDED = "Added"
COL_SKIP = "Skip"          # a person types anything here to opt out. Never ours.
COL_NOTES = "Notes"
HEADERS = [COL_NAME, COL_MMDD, COL_SOURCE, COL_ADDED, COL_SKIP, COL_NOTES]

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

HUB_CARD = "Birthday Reminders"
HUB_REPORT_ID = "birthday_reminders"

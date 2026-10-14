"""Rep Knock Breakdown — settings.

Ask (Raf, Loom + #l10 thread 2026-10-13): "a thread per rep posted in the thread
every hour" in the channel he made, #alphalete-sales-knocking-data — every line
of OwnerVille's Today's Activity knock table for that rep, color-coded like the
page, so "we can catch things like this failure right here" (GPS 'Failure, 0.45
mile is out of range'). "Maybe every week it would have to reset" -> one thread
per rep per WEEK (Sunday start). And: "if a rep has 3 failed knocks in a row can
we also have it text my Aplayersknocking report please?" -> the iMessage room
"Knocking Chat A-Players" (the room gap_alerts already texts for Raf).
"""
from __future__ import annotations

from pathlib import Path

# #alphalete-sales-knocking-data — PRIVATE, created by Raf 2026-10-13. Lucy must
# be a member or every post fails; a private channel Lucy has not joined does
# not always say so clearly (see gap_alerts.config SLACK_HOURLY_CHANNEL).
SLACK_CHANNEL = "C0C8KBT065D"
SLACK_CHANNEL_NAME = "#alphalete-sales-knocking-data"

TEXT_GROUP = "Knocking Chat A-Players"

# Raf's own office, the master login on Lucy 1 (rhidalgo == 11280). No
# impersonation: this is his office's reps only.
OFFICE_NAME = "Rafael Hidalgo"
CAMPAIGN_ID = "3"                    # RES AT&T — same pin gap_alerts uses for Raf

PAGE_TODAYS_ACTIVITY = 88

# 3 GPS failures in a row = the text. Raf's number.
FAIL_STREAK = 3

# Rows per picture. OwnerVille pages the table at 50; a 150-knock day as ONE
# image is ~4,500px tall and unreadable on a phone, so it goes as pages.
ROWS_PER_IMAGE = 50

# The selling day, machine-local (Lucy 1 is Central). The plist fires at :05;
# these are the guard the code applies, so a hand run at 9am posts nothing.
WINDOW = {
    # weekday(): (first hour, last hour) inclusive
    0: (14, 21), 1: (14, 21), 2: (14, 21), 3: (14, 21), 4: (14, 21),
    5: (11, 18),
}

STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "rep_knock_breakdown_state.json")
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "rep_knock_breakdown"

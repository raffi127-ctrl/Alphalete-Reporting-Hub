"""NDS (RES AT&T OOF) reports for Carlos's crew -- settings.

Carlos 2026-10-19: "instead of going through fiber codes and Raf's login
... you're going to start going through mine ... the campaign on Ownerville
... AT&T OOF ... OOF is out of footprint ... we're just going to refer to it
as NDS, so label NDS knocks board etc."

Runs on LUCY 2 (its Ownerville login IS Carlos's office 11580 -- no
impersonation), under the RES AT&T OOF campaign. Replaces the Fiber reports
(gap_alerts guests on Lucy 1), which are switched off in their own config.
"""
from __future__ import annotations

from pathlib import Path

TEAM = "NDS"                                   # the word in front of every post
CAMPAIGN_LABEL = "RES AT&T OOF"                # as the Ownerville picker shows it
# invD2DClientId of RES AT&T OOF on office 11580. Found by
# `rerun b2b_dispositions --probe-campaigns` on Lucy 2 (2026-10-19).
CAMPAIGN_ID = "1"       # picker href on 2026-10-19: p=510&invD2DClientId=1

# Where it goes (Carlos's rooms).
TEXT_GROUPS = ["NEW A Players", "ATT B2B Leaders"]
SLACK_CHANNEL = "C07J46MQNUX"                  # #alphalete-gp-sales
# `--recap-week`: last week's Mon-Sat board + every day's end-of-day board in
# ONE new thread here (Carlos 2026-11-06: "Create a thread on the a players
# slack and post them all on there").
RECAP_CHANNEL = "C0AJQA8P716"                  # #a-players-b2b
THREAD_BOARD = "%s Knocks Board" % TEAM        # "<title> — Month Dth YYYY" (shared style)
THREAD_GAPS = "%s 15 Min Gaps" % TEAM

# Hours, on this machine's clock (Lucy 2 = Central). Sunday off unless
# shared/day_override says that date is a Saturday.
# 1:30 since 2026-11-03 (Carlos: "lets start our knocks board 30 mins earlier
# moving forward"); was 2:00. Saturday unchanged.
WEEKDAY_START, WEEKDAY_STOP = (13, 30), (21, 0)
SATURDAY_START, SATURDAY_STOP = (11, 45), (18, 0)    # 11:45-6:00 since 2026-11-07 (Carlos); was 10:15-5:30
# One-off earlier starts, by date (Carlos 2026-10-30: "the NDS knock board and
# the NDS 15-minute gaps start 30 minutes early today"). Only the START moves;
# stop and slots are unchanged. Safe to leave old dates here.
START_OVERRIDES = {"2026-10-30": (13, 30)}

# First Knock colours on the board (Sebastian 2026-10-21, OK'd by Eve): this
# crew starts at 2:00, not Raf's 1:30 -- green up to 2:00, gray 2:01-2:29, red
# from 2:30. Every other KPI still reads Raf's "Knocking KPI's" tab.
FIRST_KNOCK_GREEN_AT = (14, 0)
FIRST_KNOCK_RED_AT = (14, 30)

# Extra board slots on top of the hourly ones (Carlos 2026-10-22: "send the
# knock board at 2:30 as well and then have it continue its regular
# schedule"). Weekday clock; each is a (hour, minute) half-hour slot.
EXTRA_BOARD_SLOTS: list = []       # 2:30 is covered by the half-hour rule now
# Saturday (Carlos 2026-10-24: "board + gaps at 10:15, 10:30, 10:45, 11 and
# then continue on the regular schedule"): three extra board slots inside the
# 10 o'clock hour; 11:00 onward is the hourly rule.
# Saturday (Carlos 2026-11-07): boards 11:45, 12:00, 12:15, 12:30, then every
# 30 min to 6:00. An hour with named slots uses ONLY those, so hour 12 names
# all three; 1pm onward is the half-hour rule.
SAT_EXTRA_BOARD_SLOTS = [(11, 45), (12, 0), (12, 15), (12, 30)]
GAPS_EVERY_MIN = 15          # the typed list
BOARD_EVERY_MIN = 30         # the picture (hourly until 2026-10-26: "send every 30 minutes instead of every hour")
CALLOUT_EVERY_MIN = 60       # "no dispo, no credit check" lines
GAP_THRESHOLD_MIN = 15

# Post kinds, as the b2b_dispositions text handoff keys them.
KIND_BOARD = "nds_board"
KIND_GAPS = "nds_gaps"
KIND_WEEK = "nds_week"
# The Mon–Sat combined board (weekly_knock_dispositions, row key below) on
# Saturday, right after the last board of the day (Carlos 2026-10-26).
WEEK_ROW_KEY = "Carlos Hidalgo (NDS)"
WEEK_AFTER = SATURDAY_STOP
# Monday morning: last week's Mon–Sat board again, as a reply in that day's
# "NDS Metrics —" thread (Carlos 2026-11-02: "didn't we go over Monday morning
# posting an NDS knocks board for the whole [week] in the NDS metrics thread").
# Slack only (the Saturday one already texted it). First tick at/after this
# clock on a Monday; the metrics thread is up by ~7:45.
WEEK_MONDAY_AFTER = (10, 0)
WEEK_MONDAY_THREAD = "NDS Metrics"

# Reps who knock on RAF's Ownerville but belong on THIS knocks board (Carlos
# 2026-11-03: "theres two people whos knocks will be under rafs owner ville
# (just for knocks not anywhere else) ... Cinthya reyes and nathaly benitez").
# Their rows are lifted off the relay workbook's 'Lucy Knocks' tab, where
# gap_alerts (Lucy 1) drops Raf's board rows every 30 min -- no second
# Ownerville session, no impersonation. Keyed by that tab's Key column; names
# matched the way total_knocks.guests matches (loose, unique hits only).
# BOARD ONLY: not the gaps list, not the call-outs, not the owners' board
# share (Raf's row there already carries them). Raf's own board is untouched.
BORROWED_ROWS = {"rafael": ["Cinthya Reyes", "Nathaly Benitez"]}
# Raf's rows are re-shared only when HIS board draws (~:04 and ~:34), so a
# board drawn at :00/:30 carried numbers 26 minutes old (Carlos 2026-11-03
# 2:30pm: "the numbers dont seem accurate"). Before pulling, a board tick
# waits up to this many minutes for a share newer than the slot's start;
# past that it draws with what is there and says so in the log.
BORROWED_FRESH_WAIT_MIN = 9
# Since 2026-11-03 Raf's board draws on HIS office Mac (Lucy 1's gap_alerts
# for him is switched off), so nothing writes his 'Lucy Knocks' row any more
# -- Cinthya + Nathaly vanished from the NDS board 11/04-11/05. His Mac
# relays his knocks to the 'ICD Knocks' tab like every office; this maps a
# borrowed key to that office key. Both tabs are read; the newer row wins.
BORROWED_ICD_OFFICES = {"rafael": "raf"}   # ICD office key read off the relay 2026-11-06

# Credit checks for the call-outs come from Carlos's own SaraPlus, relayed by
# his office Mac mini under this ICD office key (icd_alerts).
RELAY_OFFICE_KEY = "carlos-b2batt"

# "No dispositions from" (Carlos 2026-11-06): at these weekday slots, every
# rep in the Stations tab's car-ride grid (Vantura master, C6:F15 = Territory
# Leader + Rep #1-#3 under ALPHALETE NDS) who has no dispositions yet is
# named in one message. Reads the same pull the gaps use (our Ownerville +
# the borrowed rows off Raf's relay for Cinthya/Nathaly). Slots that fall on
# a board draw (2:30, 3:00) post right after the board's wait for Raf's
# share, so ~:35/:05; 2:45 and 3:15 land on the tick.
NO_DISPO_SLOTS = [(14, 30), (14, 45), (15, 0), (15, 15)]          # Mon-Fri
NO_DISPO_SAT_SLOTS = [(12, 15), (12, 30), (12, 45)]               # Saturday (Carlos 2026-11-07)
NO_DISPO_WEEKDAYS = [0, 1, 2, 3, 4, 5]         # Mon-Sat (Carlos 2026-11-07: Saturday too)
NO_DISPO_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura master
NO_DISPO_TAB = "Stations"
NO_DISPO_RANGE = "C6:F15"
NO_DISPO_SLOT_GRACE_MIN = 14                   # anything before the next slot still counts (a slow tick)
KIND_NO_DISPO = "nds_no_dispo"
# Carlos 2026-11-06: "just on the att b2b leaders text chain" -- a text to
# ATT B2B Leaders only (b2b_dispositions TEXT_ROUTES), no Slack post.
NO_DISPO_SEND = True

STATE_PATH = Path.home() / ".config" / "recruiting-report" / "nds_oof_state.json"
PROFILE_DIR = Path(__file__).resolve().parents[1] / "uploaded" / ".browser_profile_nds_oof"

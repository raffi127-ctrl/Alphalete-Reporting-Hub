"""Where the ad photo threads read from.

The SPINE is the interviewers' sheet (ARS REPORT - R to Z): one row per
1st-round candidate with the date, the full name and the ad title. Slack only
supplies the screenshot — we find the candidate's name in the day's thread and
take the image(s) off that reply.

Each sheet tab pairs with one daily Slack thread. The thread is found by its
wording (a different interviewer posts it every day), never by who posted it.
"""
from __future__ import annotations

import re

# ARS REPORT (5) - R to Z — shared with the runners' Sheets account 2026-09-21.
SHEET_ID = "16UruNs3bHGJ_pBvmD6T9KEqMAtDNNyuKArA_es6f0LE"

# #rafs-office-recruiting-11280 — where the 1st-round threads live.
SOURCE_CHANNEL_ID = "C0AUAS88FGW"

# Where the ad threads go live: #rafs-local-office-indeed-photos (Raf
# 2026-09-21: "lets move the post to the new channel I just made ... I don't
# like the recruiting channel getting so clogged up"). The 1st-rounds threads
# are still READ from SOURCE_CHANNEL_ID. The first night's posts in the old
# channel were taken out with `--retire-channel C0AUAS88FGW`.
LIVE_CHANNEL_ID = "C0C3LCLKZTN"

# The scheduled tick posts nothing for days BEFORE this date (an explicit
# `--nightly --date` still runs). 2026-09-21: the first night in the new
# channel is posted by hand, so the tick can't race it and double-post; from
# 9/22 on the tick runs as usual. "" = never paused.
NIGHTLY_PAUSED_BEFORE = "2026-09-22"

# "Every day at the end of the day": the nightly agent ticks every 30 min and
# posts the day once it's past this time, Central. The last 1st-round slot is
# ~3:45 PM and the sheet is filled as they go, so 7 PM has the whole day.
# Mon–Sat; Sunday has no 1st rounds.
POST_AFTER_CT = (19, 0)
POST_WEEKDAYS = {0, 1, 2, 3, 4, 5}

# Lucy's token has no pins:write, so Eve pins the week's threads by hand
# (2026-09-21). Whenever a run opens new threads, Lucy DMs her the links to
# pin, plus last week's to unpin. Stops by itself once Lucy can pin.
PIN_REMINDER_USER = "U088E2KJEV8"   # Evelyn Sobrino

# Each candidate line is labelled with the ApplicantStream it came from, BY
# NAME (Raf 2026-09-21: "label it with what the applicant stream is called,
# not the account number"). Names as ApplicantStream shows them (the same
# names Raf's recruiting to-do uses).
#
# Raf 2026-09-21: "1st rds from all 3 funnels are all in the same recruiting
# funnel" — the third stream (24065 New Recruiter Test) has no thread or tab
# of its own; its 1st rounds land in the Irving thread + "Rafael Hidalgo" tab,
# so they carry that row's label.
#
# sheet tab -> the daily Slack thread whose replies carry its screenshots.
#   "🦏 Alphalete (Irving) - September 18th- 1st Rounds 🦏"
#   "📱 2nd funnel IMessage Test - September 18th - 1st rounds 📱"
SOURCES = [
    {
        "office_id": "11280",
        "stream": "ALPHALETE MARKETING, INC.",
        "label": "Alphalete (Irving)",
        "tab": "Rafael Hidalgo",
        "thread_re": re.compile(r"alphalete\s*\(irving\).*1st\s*round", re.I),
    },
    {
        "office_id": "23965",
        "stream": "2nd Funnel iMessage Test",
        "label": "2nd funnel iMessage Test",
        "tab": "Raf Hidalgo 2nd funnel",
        "thread_re": re.compile(r"2nd\s*funnel.*1st\s*round", re.I),
    },
]

# First live test (Eve 2026-09-21): a group DM with Lucy instead of the real
# channel. IDs, not names — Lucy has no users:read.
TEST_DM_USERS = [
    "U045Z8N0ZQC",   # Rafael Hidalgo
    "U07FWSYP3NV",   # Camila Hornos Kraschinsky
    "U04G5HJBGFN",   # Megan Hidalgo
    "U088E2KJEV8",   # Evelyn Sobrino
    "U07R68ZGHT6",   # Perla Falabella
    "U09HN07PPU5",   # Maddie Buck
]

# Found by the header text, never by column letter — the template moves.
COL_DATE = "Date 1st Rd"
COL_NAME = "Full Name"
COL_TITLE = "Ad Title"
COL_INTERVIEWER = "1st Round Interviewer"
COL_QUALIFY = "Qualify"
COL_STARS = "Star Rating"

# How far back the sheet is read to learn which ads are running. Long enough
# that a slow ad still has enough rows to be recognised, short enough that a
# retired ad's old spellings don't compete with today's.
TITLE_LOOKBACK_DAYS = 45

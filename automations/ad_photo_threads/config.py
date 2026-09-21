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

# Megan 2026-09-21: every funnel Raf runs, each labelled with its
# ApplicantStream account number. The third one, 24065 "New Recruiter Test"
# (live since 9/18), starts 1st rounds 9/21.
#
# sheet tab -> the daily Slack thread whose replies carry its screenshots.
#   "🦏 Alphalete (Irving) - September 18th- 1st Rounds 🦏"
#   "📱 2nd funnel IMessage Test - September 18th - 1st rounds 📱"
SOURCES = [
    {
        "office_id": "11280",
        "label": "11280 · Alphalete (Irving)",
        "tab": "Rafael Hidalgo",
        "thread_re": re.compile(r"alphalete\s*\(irving\).*1st\s*round", re.I),
    },
    {
        "office_id": "23965",
        "label": "23965 · 2nd funnel iMessage Test",
        "tab": "Raf Hidalgo 2nd funnel",
        "thread_re": re.compile(r"2nd\s*funnel.*1st\s*round", re.I),
    },
    {
        # Interviews start 2026-09-21 (Camila), same posting guideline as the
        # other two. Tab name is a guess until it exists — a missing tab is
        # skipped, so check `--dry-run` output once their first thread is up.
        "office_id": "24065",
        "label": "24065 · New Recruiter Test",
        "tab": "Raf Hidalgo New Recruiter Test",
        "thread_re": re.compile(r"new\s*recruiter.*1st\s*round", re.I),
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

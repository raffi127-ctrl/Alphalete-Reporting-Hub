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

# Where the ad threads go live: #indeed-photos-rafs-local-office (Raf
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
# posts the day once it's past this time, in the OFFICE's zone (OFFICES
# below; the name says CT from when Rafael was the only office). The last
# 1st-round slot is 3:45 PM CT (Camila 2026-09-22) and the sheet is filled as they go; Raf
# 9/22: "to be safe lets do 4:30 local time of the pulling instead of 7:00pm".
# A shot posted after the pull is caught by the late-photo watch next nights.
# Mon–Sat; Sunday has no 1st rounds.
POST_AFTER_CT = (16, 30)
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

# EVERY OFFICE (Eve 2026-09-23): the same threads for each owner with a
# check mark on Raf's list, each into its own #indeed-photos-<owner>s-office
# channel (created 9/23, Lucy + Lucy Reporting invited). One entry per office:
# where its 1st rounds are read (ARS REPORT workbook + tab, the office's
# recruiting channel + the daily thread's wording) and where its ad threads go.
# The Rafael globals above ARE the "rafael" entry; `use(office)` points them
# at another office for one pass, so collect/post read the right one.
#
# `tz`: each office posts at 4:30 PM ITS local time (Eve 9/23), until the
# owners say otherwise. Rafael stays on Central (his "local time of the
# pulling", 9/22). None = look it up in office_tz (the zones table), Central
# if nobody has placed the office yet.
#
# `live`: False = manual runs only (`--office KEY`), the nightly tick skips it.
# New offices start False and go live after Eve checks the preview.
ARS_A_TO_C = "1BltgRTW_tm-Y0AlUIVxqHHqh3cpSUwWc5F1Ako01gVw"

OFFICES = [
    {
        "key": "rafael",
        "owner": "Rafael Hidalgo",
        "tz": "America/Chicago",
        "live": True,
        "sheet_id": SHEET_ID,
        "source_channel": SOURCE_CHANNEL_ID,
        "live_channel": LIVE_CHANNEL_ID,
        "paused_before": NIGHTLY_PAUSED_BEFORE,
        "sources": SOURCES,
    },
    {
        # Preview office (Eve 9/23). Daily thread in
        # #carlos-hidalgo-office-recruiting-11580:
        #   ":wolf:*ALPHALETE MARKETING - 1st ROUNDS - SEPTEMBER 23rd*:wolf:"
        "key": "carlos",
        "owner": "Carlos Hidalgo",
        "tz": None,
        "live": False,
        "sheet_id": ARS_A_TO_C,
        "source_channel": "C09L1S3MQ1E",
        "live_channel": "C0C3XGN541G",     # #indeed-photos-carlos-hidalgos-office
        "paused_before": "",
        "sources": [
            {
                "office_id": "11580",
                "stream": "ALPHALETE MARKETING",
                "label": "Alphalete Marketing",
                "tab": "Carlos Hidalgo",
                "thread_re": re.compile(r"alphalete\s*marketing.*1st\s*round", re.I),
            },
        ],
    },
]


def office(key: str) -> dict:
    for o in OFFICES:
        if o["key"] == key.strip().lower():
            return o
    raise KeyError(f"no office {key!r} — known: {', '.join(o['key'] for o in OFFICES)}")


def office_zone(o: dict) -> str:
    if o.get("tz"):
        return o["tz"]
    try:
        from automations.first_to_second_below_mark import office_tz
        return office_tz.zone_or_fallback(o["owner"])[0]
    except Exception:                                     # noqa: BLE001
        return "America/Chicago"


def use(o: dict) -> None:
    """Point this module's globals at office `o` for the rest of the pass."""
    global SHEET_ID, SOURCE_CHANNEL_ID, LIVE_CHANNEL_ID, NIGHTLY_PAUSED_BEFORE, SOURCES
    SHEET_ID = o["sheet_id"]
    SOURCE_CHANNEL_ID = o["source_channel"]
    LIVE_CHANNEL_ID = o["live_channel"]
    NIGHTLY_PAUSED_BEFORE = o.get("paused_before") or ""
    SOURCES = o["sources"]


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

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
# Days: POST_WEEKDAYS below.
POST_AFTER_CT = (16, 30)
# Mon–Fri (Raf 2026-09-23: "we don't do 1st rds on saturday").
POST_WEEKDAYS = {0, 1, 2, 3, 4}

# One thread per ad FOREVER, a new one only for a new ad (Raf 2026-09-23:
# "we don't need a new thread every week"). Its header still shows THIS
# week's % removed / avg stars. False = the old fresh-thread-every-week.
ONE_THREAD_PER_AD = True

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
        # First office after Rafael (Eve 9/23). Daily thread in
        # #carlos-hidalgo-office-recruiting-11580:
        #   ":wolf:*ALPHALETE MARKETING - 1st ROUNDS - SEPTEMBER 23rd*:wolf:"
        "key": "carlos",
        "owner": "Carlos Hidalgo",
        "tz": None,
        # Off 9/23 night while the channel is re-posted with the new title
        # rule (a merge lost one duplicate's people); back on after.
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


# The rest of the offices with a check mark on Raf's list (Eve 9/23). Same
# shape as Carlos, one stream each: (key, owner, ARS workbook, tab, office id,
# company as ApplicantStream shows it, recruiting channel, indeed-photos
# channel, the daily thread's wording). They start not live: last week and
# this week are posted by hand first, then they go live.
# Rashad's regex is anchored at the start: an "EOD-ELEVATE ... 1st ROUNDS"
# recap is posted the evening after and must not be taken for the thread.
# His 1st rounds move to #23411-elevate-specialized-acquisitions-inc-rashad-reed
# from 9/24 (Raf 9/23), so both channels are read (collect.source_channels).
ARS_D_TO_I = "1U5GZyzuXmzeNRKDL8V_lvCpzEtpjxuy4LLCDT3gDKcQ"
ARS_J_TO_L = "1sq_0VY-y1kzcQ8SAOmqs4VLE_2bPSJpCLTFufcUtQW4"
ARS_M_TO_Q = "12zye9tduziss1w-EdZKkPJ2DE-dg-xB0aqvC2H3cLao"
ARS_R_TO_Z = SHEET_ID
SOUTH_SHORE = "13a1ACbG_F_r1g5D9Zny7fSixuolobwyEL1YQXu1WgJk"

_MORE = [
    ("salik", "Salik Hammad", ARS_R_TO_Z, "Salik Mallick", "21328", "Elite Prime Group",
     "C05BPNNJGE7", "C0C3RDDJ9MH", r"elite\s*prime\s*group.*1st\s*round"),
    ("kash", "Kash Rai", ARS_J_TO_L, "Kash Rai", "22177", "Palace Acquisitions Inc",
     "C08U6GCS7SB", "C0C3VMK0B1U", r"palace\s*acquisitions.*1st\s*round"),
    ("cyrus", "Cyrus Wade", ARS_A_TO_C, "Cyrus Wade", "22815", "Ambient Marketing",
     "C0AUC4PAF2A", "C0C3G969J2K", r"ambient\s*marketing.*1st\s*round"),
    ("aya", "Aya Al-Khafaji", ARS_A_TO_C, "Aya Al-Khafaji", "22992", "Indelible Marketing",
     "C0AU7GN2TJ7", "C0C3XGN68GJ", r"indelible\s*marketing.*1st\s*round"),
    ("rashad", "Rashad Reed", ARS_R_TO_Z, "Rashad Reed", "23411", "Elevate Specialized Acquisitions",
     ["C0APEHLHDD2", "C0BEWHY5KQ9"], "C0C3XGN9K0S",
     r"^\W*elevate\s*specialized.*1st\s*round"),
    ("haytham", "Haytham Nagi", ARS_D_TO_I, "Haytham Nagi", "22524", "Horizon Edge Alliance",
     "C0AUUSCSEV7", "C0C4S176UQG", r"horizon\s*edge.*1st\s*round"),
    ("jacob", "Jacob Dover", ARS_J_TO_L, "Jacob Dover", "23607", "Rockstarworld Incorporated",
     "C0B9N1WDBB8", "C0C3VMKLZGE", r"rockstarworld.*1st\s*round"),
    ("khalil", "Khalil Mansour", ARS_J_TO_L, "Khalil Mansour", "11901", "Ever Forward Marketing",
     "C0AUKHN120L", "C0C4S17G62U", r"ever\s*forward.*1st\s*round"),
    ("isaiah", "Isaiah Revelle", ARS_D_TO_I, "Isaiah Revelle", "19717", "Legacy Acquisitions Inc",
     "C0AU0G0K2DD", "C0C3XGP0ZEE", r"legacy\s*acquisitions.*1st\s*round"),
    ("maxamad", "Maxamad Aden", ARS_M_TO_Q, "Max Aden", "23066", "Maximal Management",
     "C0AH5G7SY66", "C0C3ZJ7F1FT", r"maximal\s*management.*1st\s*round"),
    ("atef", "Atef Choudhury", ARS_A_TO_C, "Atef Choudhury", "23467", "Domin8 Acquisitions (Denver)",
     "C0B85KRS5FU", "C0C3G97KHFH", r"domin8.*1st\s*round"),
    ("roshan", "Roshan Amin Ahmad", ARS_R_TO_Z, "Roshan Ahmad", "19833", "Sapphire Marketing",
     "C0AUUT7JH33", "C0C41A9G6JG", r"sapphire\s*marketing.*1st\s*round"),
    ("ryan", "Ryan McSpadden", ARS_R_TO_Z, "Ryan McSpadden", "22820", "Highline Management Team",
     "C0794R5TLG5", "C0C3G97JN1M", r"highline\s*management.*1st\s*round"),
    # SOUTH SHORE | PROFITS - Report (New), same folder as the ARS books (Eve
    # 9/23). Drew's live tab is " Drew Tepper New" -- leading space and all;
    # his old "Drew Tepper" tab stopped in September. Samuel, Jose and Colten
    # post a "FIRST ROUND THREAD: 09/23 please post photo, ..." thread; Jose's
    # started 9/22 (nothing posted before). Joseph Delgado's tab has no Ad
    # Title column and no rows since 9/14, so he isn't here yet.
    ("drew", "Drew Tepper", SOUTH_SHORE, " Drew Tepper New", "22583", "Precision Management",
     "C0AUKGJAX8C", "C0C3XGN1W9G", r"precision\s*management.*1st\s*round"),
    ("samuel", "Samuel Acay", SOUTH_SHORE, "Samuel Acay", "23751", "Samuel Acay",
     "C0BHAAAKASJ", "C0C3G96BU6B", r"first\s*round\s*thread"),
    ("jose", "Jose Velasquez", SOUTH_SHORE, "José Velasquez", "22434", "Jose Velasquez",
     "C0AU9JBCJGK", "C0C3ZJ7FNDP", r"first\s*round\s*thread"),
    ("colten", "Colten Wright", SOUTH_SHORE, "Colten Wright", "14733", "Colten Wright",
     "C0AUAPMEF37", "C0C3ZJ7FTH7", r"first\s*round\s*thread"),
]

# Zones the office_tz table can't place yet; everyone else falls to Central.
_TZ = {"atef": "America/Denver"}       # "Domin8 Acquisitions (Denver)"

OFFICES += [
    {
        "key": key, "owner": owner, "tz": _TZ.get(key), "live": False,
        "sheet_id": book, "source_channel": src, "live_channel": live,
        "paused_before": "",
        "sources": [{"office_id": oid, "stream": company, "label": company,
                     "tab": tab, "thread_re": re.compile(rx, re.I)}],
    }
    for key, owner, book, tab, oid, company, src, live, rx in _MORE
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

"""Wiring for the Sara+ (SaraPlus) issue-escalation bot. No secrets here — the
Slack token and the Gmail app password come from the same gitignored files
every other report uses (see automations/shared/slack_metrics_post.py and
automations/scheduled_6_days_out/email_send.py).

Fully wired as of 2026-07-17. The bot stays SAFE while testing: --dry-run
previews the exact email and sends nothing, and a live run with no recipients /
no channel refuses with a clear error instead of half-escalating. It only goes
live once the launchd job is installed on the mini (deploy/com.alphalete.sara-down.plist).
"""
from __future__ import annotations

import os

# --- 1) The Slack channel to watch -------------------------------------------
# #saraplus-issues (private, created by Raf 2026-07-17). Lucy is a member, so it
# can read the posted screenshots. Override with the SARA_DOWN_CHANNEL_ID env
# var or --channel to point at a TEST channel while building.
CHANNEL_ID = os.environ.get("SARA_DOWN_CHANNEL_ID", "C0BHR6T1P2B")

# --- 2) Who is allowed to trigger a send -------------------------------------
# The channel is PRIVATE and curated by Raf, so its MEMBERSHIP is the allow-list:
# anyone he adds can report an issue, anyone he removes can't — nothing to
# maintain here. Empty tuple = "any member of the channel who posts a screenshot
# triggers a send". To lock it down to specific people instead, list their Slack
# user ids (look one up with:  python -m automations.sara_down.run --whois EMAIL).
#   U045Z8N0ZQC = Rafael Hidalgo (raffi127@gmail.com)
APPROVED_POSTERS: tuple[str, ...] = ()

# --- 3) Who the escalation email goes to -------------------------------------
# TO = Sara+ support. CC = our leaders + the marketing inbox, so they're on the
# thread and can reply-all. Plain address lists (programmatic sends can't expand
# a Gmail group name — they need explicit addresses).
TO_ADDRS: tuple[str, ...] = (
    "support@saraplus.com",          # Sara+ support team (Megan 7/17)
)
CC_ADDRS: tuple[str, ...] = (
    "raffi127@gmail.com",            # Raf
    "alphaletemarketing@gmail.com",  # Alphalete Marketing inbox
    "dylanjtwaddle@gmail.com",       # Dylan Twaddle
)

# --- Email wording -----------------------------------------------------------
# Matches how Raf actually writes these ("Sara+ Issue", "Hey team, …"). Subject
# is "Sara+ Issue" with the report date appended -> "Sara+ Issue — 7/17/2026"
# (Megan 7/17). The issue text comes from the reporter's Slack message;
# {reporter}/{when} fill in the body per-message.
SUBJECT = "Sara+ Issue"
# Used when the reporter posts a bare screenshot with no note.
DEFAULT_NOTE = ("We're seeing an issue with Sara+ in the field (see attached). "
                "Can we look into it?")

# How many recent channel messages to scan each run. 20 is plenty at a 5-min
# cadence; a burst of reports during a real outage still fits.
SCAN_LIMIT = 20

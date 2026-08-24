"""Everything about this report that a human might want to change.

Nothing here is a row/column index -- columns are found by their header LABEL
and weeks by the date in the tab's header row, so a template edit can't
silently shift what we read (see the no-hardcoded-columns rule in CLAUDE.md).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# "All in One Local Office - Raf" -- the same workbook bg_check_sync writes to.
SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"

# A new tab per week: "D2D OBCL 8.24", "D2D OBCL 8.31", ... The rolling
# undated "D2D OBCL" tab is deliberately NOT used as a source: it stacks every
# week ever, and we only ever want the lineup that is about to start.
DATED_TAB_PREFIX = "D2D OBCL"

# Our own log tab (created on first send). We never write into the OBCL
# columns themselves -- those are hand-maintained by the recruiting team.
LEDGER_TAB = "Blue Ink Log"

# --- Column labels on the OBCL tabs ----------------------------------------
COL_FIRST = "Name"
COL_LAST = "Last Name"
COL_EMAIL = "Email"
COL_PHONE = "Phone"
COL_FINAL_STATUS = "Final Status"
COL_BG_STATUS = "BG Status"          # real header is "BG Status : Last Checked"
COL_FRIDAY = "Friday Confirmation"
COL_TRAINER = "Trainer"

# --- Who does NOT get Blue Ink ---------------------------------------------
# Rule from Megan (2026-08-24): if they aren't going to start, don't send.
#
# Final Status (col J) started as "blank means still in the pipeline", so this
# began as "must be blank". That was wrong: the column carries GOOD outcomes
# too -- "Showed Up To CR" appeared on 8/24 and the blank-only rule silently
# excluded someone who WAS starting. So it's a block-list now (Megan's call,
# 2026-08-24): name the outcomes that stop a send, let everything else through.
#
# Matched as SUBSTRINGS of the case/accent-folded value, so "Quit before
# Classroom", "Quit during Classroom" and a future "Quit - CR" all hit "quit"
# without needing the exact wording.
FINAL_STATUS_BLOCK_MARKERS = (
    "quit",           # Quit before / during Classroom
    "failed",         # Failed BGC
    "terminat",       # Terminated
    "no show", "noshow", "no-show",
    "resched",        # RESCHEDULING
    "declin",         # Declined
    "backed out",
)

# Values we've seen that are FINE -- someone who reached one of these is still
# starting and still needs docs. Anything in Final Status that matches neither
# this nor the block markers still SENDS (that's what a block-list means), but
# gets printed as a loud unrecognised-value warning, so a new bad outcome gets
# caught by a human on the next run instead of silently mailing the wrong
# person forever. That warning is the safety net the blank-only rule used to be.
FINAL_STATUS_KNOWN_OK = (
    "showed up to cr",
)

# BG Status values that disqualify. These are two of the ten options in the
# column's dropdown; the rest (Passed, Sent, Taken - Pending, Review,
# Unperformable, Expired, Pending (Name Issue)) still get docs, because docs
# go out while the background check is still moving.
BG_STATUS_BLOCK = {"failed", "adverse action"}

# Friday Confirmation values that disqualify (Megan 2026-08-24). Someone who
# declined the Friday confirmation isn't showing up Monday, so they don't get
# docs -- same logic as the Final Status rule. "Failed Background" here is the
# same call: it caught Joshua Applegate, whose Final Status was blank and whose
# BG Status said only "Unperformable", so neither of the other two rules saw
# him. The column's remaining values (Confirmed: OTP, Confirmed: Via Sms, BOB
# Friday, NA: Sent Text) all still send -- "NA: Sent Text" means the
# confirmation text went out and nobody has answered yet, which is not a no.
FRIDAY_BLOCK = {"declined", "failed background"}

# --- Blue Ink ---------------------------------------------------------------
# Account: alphaletemarketing@gmail.com. The private API key is read from a
# gitignored file at the repo root (the repo is PUBLIC -- never inline it):
#
#   blueink-creds.json
#   {"blueink_api_key": "...", "envelope_template_id": "T-xxxxxxxxxx"}
#
# or from env BLUEINK_PRIVATE_API_KEY / BLUEINK_TEMPLATE_ID.
CREDS_PATH = REPO_ROOT / "blueink-creds.json"

API_BASE = "https://api.blueink.com/api/v2"

# The signer role key on the envelope template. All four templates on this
# account label their one signer 'employee-1'; `--list-templates` prints the
# real keys if a future template differs.
SIGNER_KEY = "employee-1"

BUNDLE_LABEL = "Alphalete New Start Docs"
EMAIL_SUBJECT = "Your Alphalete onboarding documents"
EMAIL_MESSAGE = (
    "Welcome aboard! Please sign these before your first day. "
    "Reach out to your trainer if anything looks wrong."
)


def _creds() -> dict:
    try:
        return json.loads(CREDS_PATH.read_text())
    except Exception:
        return {}


def api_key() -> str:
    val = str(_creds().get("blueink_api_key")
              or os.environ.get("BLUEINK_PRIVATE_API_KEY", "")).strip()
    if not val:
        raise RuntimeError(
            f"No Blue Ink API key. Create {CREDS_PATH.name} at the repo root "
            '{"blueink_api_key": "...", "envelope_template_id": "T-..."} '
            "(Blue Ink -> Settings -> API, on the alphaletemarketing@gmail.com "
            "account), or set BLUEINK_PRIVATE_API_KEY. That file is gitignored "
            "by the *-creds.json* rule -- never commit it.")
    return val


def template_id() -> str:
    val = str(_creds().get("envelope_template_id")
              or os.environ.get("BLUEINK_TEMPLATE_ID", "")).strip()
    if not val:
        raise RuntimeError(
            "No Blue Ink envelope template set. Run "
            "`python -m automations.blueink_docs.run --list-templates` to see "
            f"the options, then put its id in {CREDS_PATH.name} as "
            '"envelope_template_id" (or set BLUEINK_TEMPLATE_ID).')
    return val

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
# Megan added this column 2026-08-24 (col N at the time, between "Onboarding
# Quizzes" and "Headshot Photo" -- found by LABEL, so it can move). Two states
# live in it: a light-green background the moment we send, and the checkbox
# ticked once Blue Ink shows the packet SIGNED. Note the space: the header
# reads "Blue Ink", not "Blueink".
COL_BLUEINK = "Blue Ink"
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
# THE RULE ITSELF MOVED to automations/shared/new_start_eligibility.py on
# 2026-09-26 -- it is the same question every step on the OBCL tab has to
# answer, and there were three disagreeing copies of it. Re-exported under the
# original names so nothing that reads config.FINAL_STATUS_BLOCK_MARKERS et al
# has to change. Edit the shared module, not this.
#
# Note what did NOT move: the email checks in roster._skip_reason. "No email
# address" is a Blue Ink send problem, not a fact about whether the person is
# starting -- the follow-up report still owes their leader a text.
from automations.shared.new_start_eligibility import (  # noqa: E402
    BG_STATUS_BLOCK,
    FINAL_STATUS_BLOCK_MARKERS,
    FINAL_STATUS_KNOWN_OK,
    FRIDAY_BLOCK,
)

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

# The Envelope Template's NAME as it appears on /dashboard/templates -- the UI
# path finds its row by this text. Keep it in step with envelope_template_id in
# blueink-creds.json (that id is only used by the now-capped API path).
TEMPLATE_NAME = "UNIVERSAL I9 MASTER FORM"

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

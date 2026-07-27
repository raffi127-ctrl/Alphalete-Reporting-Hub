"""Config for OAT Processing — the one place to edit the knobs.

Nothing secret lives here: the ApplicantStream session/credentials are reused
from `automations.applicant_tracker` (same site, same login). Only the OAT-
specific behaviour knobs live here so they're easy to find and change.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import os

# --- Office ---------------------------------------------------------------- #
# Carlos's office. On Lucy 2 this is the machine's own account, so the office
# picker (#searchMC) can always see it. Overridable for a test office.
OFFICE_ID = os.environ.get("OAT_OFFICE_ID", "11580")
OFFICE_HINT = "CARLOS HIDALGO"

# --- Decision thresholds (from Carlos's Loom) ------------------------------ #
# Reissue / duplicate window: an applicant who applied again within this many
# days is a duplicate and can't be reissued to the call list. Carlos said
# "applied within the last month or whatever the rule is" — 30 days is the
# working value; change here if the ATS rule differs.
REISSUE_WINDOW_DAYS = int(os.environ.get("OAT_REISSUE_WINDOW_DAYS", "30"))

# Re-text cutoff after a past interview / no-show: if their last interview was
# MORE than this many days ago we may text them again; within it we remove for
# duplicate without texting. Carlos: "as long as it's been over a week, we're
# good to text them again ... within the week, we just remove them."
RETEXT_MIN_DAYS = int(os.environ.get("OAT_RETEXT_MIN_DAYS", "7"))

# --- Phone-lookup branch (PARKED for v1) ----------------------------------- #
# The no-phone applicants (Octo Browser → the source's Indeed account → search
# name → grab phone) are NOT automated in v1. When False, no-phone applicants
# are left untouched and flagged to the human queue (see NO_PHONE_FLAG_*).
AUTOMATE_PHONE_LOOKUP = os.environ.get("OAT_AUTOMATE_PHONE_LOOKUP", "0") == "1"

# Where flagged no-phone applicants get surfaced for a human. Default is a local
# CSV under output/ (dry-run friendly, no external side effects). A Slack post
# or a Sheet tab can be wired later.
NO_PHONE_FLAG_CSV = os.environ.get(
    "OAT_NO_PHONE_FLAG_CSV", "output/oat-no-phone-queue.csv")

# --- Safety --------------------------------------------------------------- #
# A hard cap on how many applicants one run will act on. The OAT queue can be
# large; keep runs short (and mistakes small) by processing a bounded batch.
# --limit N on the CLI overrides this downward.
MAX_PER_RUN = int(os.environ.get("OAT_MAX_PER_RUN", "60"))

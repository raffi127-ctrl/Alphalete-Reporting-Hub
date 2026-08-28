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

# ARM auto re-text: when True, a quiet (>RETEXT_MIN_DAYS) applicant is auto-texted
# the FOR LUCY re-engagement message via the SMS widget, then removed
# ('re-texted & removed'). When False, they're only FLAGGED (no send). Armed full
# by Megan 2026-07-28 after the real-send validation (Stephany). Sends real SMS.
RETEXT_ARMED = os.environ.get("OAT_RETEXT_ARMED", "1") == "1"

# --- Phone-lookup branch (LIVE 2026-07-28) --------------------------------- #
# No-phone applicant → open their Indeed resume via the AS 'View resume' link
# (a signed employers.indeed.com URL, no login needed — Megan's method) and pull
# the real phone, fill it in, and Send to AI. Proven on Nevaeh (+1 817 550 4383).
# When False, no-phone applicants are just flagged to the human queue.
AUTOMATE_PHONE_LOOKUP = os.environ.get("OAT_AUTOMATE_PHONE_LOOKUP", "1") == "1"

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

# --- Multi-office namespacing (2026-08-26) --------------------------------- #
# The push works more than one office now (Carlos 11580, Atef 23467 — see
# automations/applicant_push/offices.py). Every per-day artefact this module
# writes is keyed by DATE ALONE — the activity CSV, the flagged snapshot the
# noon/4pm post reads, the no-number cache, the blocked-read cache — so two
# offices sharing them would overwrite each other's queue state and post each
# other's applicants. This suffix is appended to those filenames.
#
# EMPTY for 11580 ON PURPOSE: Carlos's files keep their exact existing names, so
# nothing already in flight (today's caches, today's thread) moves underneath him.
FILE_SUFFIX = os.environ.get("OAT_FILE_SUFFIX", "")
# Same reason for the Sheet tab each walk appends its proof row to.
WALK_DIAG_TAB = os.environ.get("OAT_WALK_DIAG_TAB", "OAT Walk Diag")

# --- Remove the truly uncontactable (Carlos 2026-08-27) ------------------- #
# When the resume lookup proves an applicant has NO reachable number — the resume
# opened and carries none, or there is no resume at all and the panel is blank —
# remove them with the "Incorrect / Insufficient Contact Info" reason rather than
# leaving them to circle the queue. Filing them as a DUPLICATE (the old catch-all)
# was actively misleading: the removal reason is the only record of why someone
# was dropped, and "duplicate" on an applicant who simply had no number makes the
# ad look like it produced a repeat rather than an unusable applicant.
#
# NEVER fires on a BLOCKED resume read — that is our failure, not the applicant's,
# and it retries (see _is_blocked_detail / _mark_nophone_blocked).
#
# NOTE this replaces the flag-for-human path for CONFIRMED-empty resumes, which is
# what feeds Megan's noon/4pm "needs a number pulled from Indeed" post. Those
# applicants had no number to pull, so the post gets shorter and truer; blocked
# reads still flag exactly as before.
REMOVE_NO_PHONE = os.environ.get("OAT_REMOVE_NO_PHONE", "1") == "1"

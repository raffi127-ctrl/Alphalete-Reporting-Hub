"""Config for the Weekly Promotion Check-In.

Every id / channel / owner is env-overridable so the check-in can point at a
sandbox Sheet or a test DM while building (sandbox-first / preview-first rules).
"""
from __future__ import annotations

import os

# --- SOURCE: the office Sales Board (read-only) -----------------------------
# "Alphalete SALES BOARD 2025". We read the NEWEST "Sales Board WE M.D" tab and
# pull each rep's Trainer / Field Status (week) / Team / Leadership Status (level).
# NEVER written to.
BOARD_SHEET_ID = os.environ.get("PROMO_BOARD_SHEET_ID") \
    or "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"

# --- TARGET: Maud's Recognition sheet (append-only) -------------------------
# One tab per week (M.D.YY), cols: Rep | Trainer | Owner | Recognition | Notes.
# We append promotion rows to the CURRENT week's tab (created by
# automations.leaders_call.recognition_tab). Additive only — never edit/clear.
RECOGNITION_SHEET_ID = os.environ.get("PROMO_RECOGNITION_SHEET_ID") \
    or "1lgYjfpCwYbeeGAdx7FEyI9PIqFk-W57X7HaZ4nsuoFM"
# Force a specific target tab (testing). Blank => the current week's M.D.YY tab.
RECOGNITION_TAB_OVERRIDE = os.environ.get("PROMO_RECOGNITION_TAB", "").strip()

# The recognition sheet's "Owner" for every promotion off THIS board. Confirmed
# by cross-referencing a shared rep (Noemi Ontiveros / trainer Andrew Sanborn)
# to her existing recognition row. One office => one owner; override if it moves.
OWNER = os.environ.get("PROMO_OWNER", "Rafael Hidalgo")

# --- SLACK -----------------------------------------------------------------
# Post as Jiraiya (the /dd bot). #alphalete-lvl1-chat is where the Level 1
# leaders live; Jiraiya must be a MEMBER of it to post.
CHANNEL_ID = os.environ.get("PROMO_CHANNEL_ID", "C09JG28CD27")   # #alphalete-lvl1-chat

# TWO DIFFERENT CARDS, same cadence (Megan 2026-11-17):
#
#   BOARD card  -> #alphalete-lvl1-chat. Pick-list read off OUR Sales Board.
#                  This office only, so every rep on it is one of Raf's and the
#                  trainer/owner are already known. UNCHANGED.
#   ORG card    -> #top-leaders-alphalete-org. The org's leaders are not on
#                  Raf's board, so there is nothing to pick from: the card
#                  opens a short form instead (rep name + trainer typed in,
#                  ICD and level picked). See message.build_org_message.
#
# #top-leaders-alphalete-org is PRIVATE — Jiraiya must be invited (Megan 2026-11-09).
LVL1_CHANNEL_IDS = tuple(c.strip() for c in os.environ.get(
    "PROMO_CHANNEL_IDS", CHANNEL_ID).split(",") if c.strip())
ORG_CHANNEL_IDS = tuple(c.strip() for c in os.environ.get(
    "PROMO_ORG_CHANNEL_IDS", "C067TTGFEFR").split(",") if c.strip())
# Kept for anything that still asks for "every channel this posts to".
CHANNEL_IDS = LVL1_CHANNEL_IDS + ORG_CHANNEL_IDS
# Preview target: DM this user the interactive card before it goes to the channel.
PREVIEW_USER = os.environ.get("PROMO_PREVIEW_USER", "").strip()

# --- The promotion ladder ---------------------------------------------------
# LADDER just marks which board levels are still promotable (used to filter the
# pick-list — a Mastermind rep has nowhere to go). The RECOGNITION level is NOT
# inferred from the board anymore: the board's "Leadership Status" is a moving
# target (it can already be bumped to the new level), so the LEADER picks the
# target level on the card (Megan 2026-07-28). See LEVEL_CHOICES.
LADDER = {
    "Entry Level": ("Level 1", "LVL 1 Leader"),
    "Level 1":     ("Level 2", "LVL 2 Leader"),
    "Level 2":     ("Mastermind", "Mastermind"),
}
# Levels that appear on the board (top of the ladder = not promotable further).
TOP_LEVEL = "Mastermind"

# The "Promoted to" dropdown: (label shown, Recognition string written). The
# leader picks ONE per batch; every rep picked in that submit logs at this level.
# Wording mirrors the sheet's existing rows ("LVL 1 Leader").
LEVEL_CHOICES = [
    ("Level 1", "LVL 1 Leader"),
    ("Level 2", "LVL 2 Leader"),
    ("Mastermind", "Mastermind"),
]

# Slack Block Kit identifiers (kept here so the bot handler + builder agree).
BLOCK_CALLBACK = "promo_checkin"          # message-level tag we look for
ACTION_PICK = "promo_pick_reps"           # the multi-select action_id
ACTION_SUBMIT = "promo_submit"            # "Log promotions" button
ACTION_NONE = "promo_none"                # "No promotions this week" button
ACTION_LEVEL = "promo_pick_level"         # the "Promoted to" single-select
ACTION_REMOVE = "promo_remove_open"       # "Remove a mistake" button (opens modal)
REMOVE_CALLBACK = "promo_remove_modal"    # the remove modal's callback_id
ACTION_REMOVE_PICK = "promo_remove_pick"  # the remove modal's multi-select

# --- The ORG card (#top-leaders-alphalete-org): type-it-in form --------------
# Slack allows free-text inputs only in a MODAL (an `input` block is invalid in
# a posted message), so the org card is one button that opens the form.
ACTION_ADD = "promo_add_open"             # "Add a promotion" button (opens form)
MANUAL_CALLBACK = "promo_manual_modal"    # the form's callback_id
# One block_id per field; the handler reads these back off the submission.
FIELD_FIRST = "promo_first"
FIELD_LAST = "promo_last"
FIELD_TRAINER = "promo_trainer"
FIELD_ICD = "promo_icd"
FIELD_LEVEL = "promo_level"

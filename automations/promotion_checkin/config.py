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

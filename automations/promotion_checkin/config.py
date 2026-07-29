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
# A rep's CURRENT board level -> (new level after promotion, the Recognition
# string written to the sheet). "Auto next level up": one pick per rep, no menu.
# Recognition strings mirror the sheet's existing wording ("LVL 1 Leader").
LADDER = {
    "Entry Level": ("Level 1", "LVL 1 Leader"),
    "Level 1":     ("Level 2", "LVL 2 Leader"),
    "Level 2":     ("Mastermind", "Mastermind"),
}
# Levels that appear on the board (top of the ladder = not promotable further).
TOP_LEVEL = "Mastermind"

# Slack Block Kit identifiers (kept here so the bot handler + builder agree).
BLOCK_CALLBACK = "promo_checkin"          # message-level tag we look for
ACTION_PICK = "promo_pick_reps"           # the multi-select action_id
ACTION_SUBMIT = "promo_submit"            # "Log promotions" button
ACTION_NONE = "promo_none"                # "No promotions this week" button

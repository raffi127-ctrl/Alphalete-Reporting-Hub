"""Headshot pipeline settings (Raf 2026-08-23, #l10-alphalete).

Someone posts a new hire's headshot in the watch channel with the person's
name as the caption. The bot cuts the background, puts the person on pure
white, and posts the finished headshot back in the thread — the name goes in
the FILENAME only (no text on the photo; Megan 2026-08-23). A copy is
archived for the Roadmap upload (that leg is Phase 2 — the Roadmap portal
upload is not automated yet).
"""
from __future__ import annotations

import os

# The channel to watch for headshot posts. Left empty on purpose until Raf
# picks/creates the channel — set it here or via HEADSHOTS_CHANNEL_ID.
# (Test with:  python -m automations.headshots.run --dry-run --channel C0…)
CHANNEL_ID = os.environ.get("HEADSHOTS_CHANNEL_ID", "").strip()

# Only process posts from these Slack user ids (admins). Empty = anyone in
# the channel. Fill with --whois like sara_down.
APPROVED_POSTERS: list[str] = []

# How many recent messages to scan each tick.
SCAN_LIMIT = 50

# Finished image geometry. 4:5 portrait is what badge/roadmap headshots use.
PHOTO_W = 1200
PHOTO_H = 1500

# How much empty white to leave around the person, as a fraction of the
# subject's height (breathing room above the head / beside the shoulders).
HEAD_MARGIN = 0.08

# rembg model. "u2net_human_seg" is trained on people — cleaner hair edges
# than the generic model. The model file downloads once to ~/.u2net/.
REMBG_MODEL = "u2net_human_seg"

# Archive of processed headshots (clean + named), grouped by date.
OUTPUT_DIR = os.path.join("output", "headshots")

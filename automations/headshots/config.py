"""Headshot pipeline settings (Raf 2026-08-23, #l10-alphalete).

weekly_thread.py starts a thread each Monday in the office channel asking
people to reply with the headshot photo + the person's name (Megan
2026-08-23). run.py watches the replies, cuts the background, puts the
person on pure white, and posts the finished headshot back in the thread —
the name goes in the FILENAME only (no text on the photo). A copy is
archived for the Roadmap upload (that leg is Phase 2 — the Roadmap portal
upload is not automated yet).
"""
from __future__ import annotations

import os

# #11280-alphalete-marketing-inc-rafael-hidalgo — same office channel the
# new-start threads + BG-status posts live in.
CHANNEL_ID = os.environ.get("HEADSHOTS_CHANNEL_ID", "").strip() or "C0AUAS88FGW"

# Finished image geometry. 4:5 portrait is what badge/roadmap headshots use.
PHOTO_W = 1200
PHOTO_H = 1500

# How much empty white to leave around the person, as a fraction of the
# subject's height (breathing room above the head / beside the shoulders).
HEAD_MARGIN = 0.08

# rembg model. "u2net_human_seg" is trained on people — cleaner hair edges
# than the generic model. The model file downloads once to ~/.u2net/.
REMBG_MODEL = "u2net_human_seg"

# Phase 2: after processing, upload the clean headshot to the rep's
# OwnerVille profile (Onboard -> View Progress -> Edit; see ov_upload.py).
# The in-thread photo post NEVER blocks on this — an OV failure is reported
# in the same reply so an admin can do that one by hand.
OV_UPLOAD_ENABLED = True

# Archive of processed headshots (clean + named), grouped by date.
OUTPUT_DIR = os.path.join("output", "headshots")

# Phase 3 (Megan 2026-08-24): after a successful OV upload, tick the rep's
# "Headshot Photo" checkbox on that week's D2D OBCL tab and tint it green —
# the same marking blueink_docs does for its own column. See sheet_log.py.
SHEET_LOG_ENABLED = True

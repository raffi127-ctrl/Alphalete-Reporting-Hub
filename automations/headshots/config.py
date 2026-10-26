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
from dataclasses import dataclass

# #rafs-office-recruiting-11280 — same office channel the
# new-start threads + BG-status posts live in.
from automations.shared.new_start_steps import SLACK_CHANNEL_ID

CHANNEL_ID = (os.environ.get("HEADSHOTS_CHANNEL_ID", "").strip()
              or SLACK_CHANNEL_ID)

# ---- WHICH OFFICES (Megan 2026-10-26: "scale this to other ICDs") -----------
# One row per office. Lucy 3 posts the Monday thread in `channel`, reads the
# replies and makes the headshot for all of them; WHO UPLOADS differs:
#
#   uploader="lucy" -- Lucy 3 uploads with its own OwnerVille login. Raf's
#                      office only (his login is the one Lucy 3 holds), and
#                      only Raf's has an OBCL sheet to tick.
#   uploader="eco"  -- the office's OWN computer uploads with the office's
#                      own login, via the relay (icd_alerts/headshot_jobs.py).
#                      Every other ICD. `eco_key` is the office's LucyEco
#                      office key (the 'Relay Keys' tab) -- jobs go to the
#                      computer holding that key and no other.
#
# mode:
#   "dry"  -- NOTHING in the office's Slack: no Monday thread, no replies.
#             Test the computer side with a read-only job by hand:
#               python -m automations.headshots.eco --test-job --office <key>
#                   --name "First Last" --file <photo.png>
#   "live" -- Monday thread goes up, headshots are made and uploaded.
# A LIVE "eco" office with a blank eco_key is allowed: the thread and the
# headshots run, and each post says to upload to OwnerVille by hand until the
# office's computer is enrolled.
# Switching an office on = adding its row, "dry" first, "live" after the test
# job comes back right. No release to the office's computer is needed: it
# already asks the relay for headshot work.
@dataclass(frozen=True)
class Office:
    key: str
    owner: str
    channel: str
    uploader: str = "eco"         # "lucy" | "eco"
    eco_key: str = ""             # LucyEco office key (uploader="eco")
    mode: str = "dry"             # "dry" | "live"
    sheet_log: bool = False       # tick the OBCL sheet (Raf's only)


OFFICES = {
    "raf": Office(key="raf", owner="Rafael Hidalgo", channel=CHANNEL_ID,
                  uploader="lucy", mode="live", sheet_log=True),
    # Omar Mohamad, Kalkan Marketing (24153), in his recruiting room (Slack
    # Connect, Lucy Reporting is in it). LIVE 2026-10-26 BEFORE his LucyEco
    # enrollment (5:30pm that day), Megan: "let's do it for him for today" --
    # so eco_key is blank and his team uploads to OwnerVille by hand (the
    # post says so). Once enrolled: fill eco_key from 'Relay Keys', run a
    # --test-job, and the uploads move to his computer.
    "omar": Office(key="omar", owner="Omar Mohamad", channel="C0C6HKZ63EK",
                   uploader="eco", eco_key="", mode="live"),
}


def live_offices():
    return [o for o in OFFICES.values() if o.mode == "live" and o.channel]


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

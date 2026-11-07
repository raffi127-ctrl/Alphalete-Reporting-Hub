"""Owner Knocks Hourly — settings.

Ask (Raf, Slack 2026-10-29): "Once an hour, can we get a report of the owners
knocking numbers please? We can do guys on LucyECHO only if that helps with not
slowing anything else down. [his Total Knocks board, CHAN PARK TOTAL over
OFFICE TOTAL] ... but now it be the owners in the org. This can be posted in
the alphalete owners iMessage Chat."

SOURCE: the Lucy ECO knocks relay ('Lucy Access App' workbook -> 'ICD Knocks'
tab, one row per office per day: the office's own TeleMapper grid). Nothing is
scraped here, so it puts no load on any Lucy beyond one Sheet read and one
picture. An owner whose Mac is not on Lucy ECO has no row and is not on the
board -- except offices a Lucy already pulls for their own boards (Raf on
Lucy 1, Carlos's NDS crew on Lucy 2), shared through share.py (Eve
2026-10-29).

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

from pathlib import Path

# The same chat owner_sales_hourly texts every hour ("Alphalete Owners 🔥 -
# Real"). resolve_group raises on 0 or 2+ hits, so a renamed chat fails loud.
from automations.owner_chat_texts.config import GROUP_OWNERS_REAL as TEXT_GROUP

# Field hours, Central. weekday(): (first hour, last hour) inclusive. The plist
# fires at :20 (off owner_sales_hourly's :15/:45 so the two texts don't land
# together); this is the guard the code applies, so a stray hand run at 9am
# texts nothing. 2 PM is the first hour with knocks on the board (1:30 starts).
# Carlos 2026-11-06: one more text an hour after the old last one (9:20 ->
# 10:20 PM), so the window runs to the 10 PM hour.
WINDOW = {
    0: (14, 22), 1: (14, 22), 2: (14, 22), 3: (14, 22), 4: (14, 22),
    5: (14, 22),
}

# Carlos Hidalgo 2026-11-06 (Slack): the board in his "NEW A Players" and
# "ATT B2B Leaders" chats too -- same picture, same :20 cadence, sent right
# after the owners chat. Names live in b2b_dispositions.config like every
# other text to those chats. A failed extra chat doesn't stop the others.
from automations.b2b_dispositions.config import TEXT_GROUP_ALL, TEXT_GROUP_ATT
EXTRA_GROUPS = (TEXT_GROUP_ALL, TEXT_GROUP_ATT)

# Offices one of OUR Lucys pulls instead of the owner's Mac -- shared on the
# relay workbook's 'Lucy Knocks' tab (share.py). gap_alerts shares these keys
# (Raf, Lucy 1, every 30 min); nds_oof shares Carlos's NDS crew (Lucy 2,
# every 30 min). Older than LUCY_STALE_MINUTES = that pull stopped, left off.
GAP_ALERTS_SHARED = {"rafael"}
CARLOS_NDS_KEY = "carlos-nds"
CARLOS_NAME = "Carlos Hidalgo"
LUCY_STALE_MINUTES = 45

BOARD_TITLE = "ALPHALETE OWNERS"
TOTAL_LABEL = "ORG TOTAL"

# D2D and B2B apart (Raf 2026-11-03: "distinguish between d2d and b2b guys ...
# the averages at the bottom should be based off of d2d / b2b but different
# time zones shouldn't negatively impact the avg knock times"). This replaces
# the Eastern/Central totals of 10/29: every knock time is on its office's own
# clock, so a 1:30 Eastern start and a 1:30 Central start average as the same
# time and no zone total is needed. B2B = an office whose campaign starts
# "b2b" (icd_alerts.offices); the shared Lucy offices are D2D. By OFFICE, not
# by owner: an owner with both gets a line in each group.
SEGMENT_FIELD = "_segment"
D2D, B2B = "D2D", "B2B"
SEGMENTS = (D2D, B2B)            # top to bottom

# Chan's comparison line (Raf 2026-11-03: "add chans here for comparison").
# Teal, on top, in no total: he is not in our org. This job pulls his rows
# itself, on Lucy 1, right before it texts: gap_alerts used to have them in
# hand under Raf's board, but Raf's board left Lucy 1 on 11/3, so nothing there
# pulls him during the day any more. If the OwnerVille session is taken for
# longer than this, the board goes out without his line rather than late.
CHAN_NAME = "Chan Park"
CHAN_SESSION_WAIT_S = 120

# Last numbers sent per day — an hour where no owner's knocks moved is skipped.
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "owner_knocks_hourly"

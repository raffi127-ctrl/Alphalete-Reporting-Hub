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
# fires at :20 (off owner_sales_hourly's :50 so the two texts don't land
# together); this is the guard the code applies, so a stray hand run at 9am
# texts nothing. 2 PM is the first hour with knocks on the board (1:30 starts).
WINDOW = {
    0: (14, 21), 1: (14, 21), 2: (14, 21), 3: (14, 21), 4: (14, 21),
    5: (14, 21),
}

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

# Last numbers sent per day — an hour where no owner's knocks moved is skipped.
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "owner_knocks_hourly"

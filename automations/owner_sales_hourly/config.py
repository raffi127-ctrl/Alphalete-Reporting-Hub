"""Owner Sales Hourly — settings.

Ask (Raf, Slack 2026-10-24, to Megan + Eve + Carlos): "Since a lot of owners
are getting their total units. On our 'alphalete owners' iMessage chat, once an
hour. Can we get an update on how many sales each owner is at please?"

SOURCE: the Lucy ECO relay ('Lucy Access App' workbook -> 'ICD Relay' tab ->
'Sales JSON', one row per office per day), read through
icd_sales_board.relay_read. It is the only place every office's live,
same-day sales land — the Org board only carries completed days. An owner whose
laptop agent is not installed has no row and is simply not on the list.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

from pathlib import Path

# The same chat owner_chat_texts sends the trackers into from Lucy 1
# ("Alphalete Owners 🔥 - Real"). Needle stops before the emoji; resolve_group
# raises on 0 or 2+ hits, so a renamed chat fails loud instead of texting the
# wrong room.
from automations.owner_chat_texts.config import GROUP_OWNERS_REAL as TEXT_GROUP
from automations.owner_chat_texts.config import GROUP_SOUTHSHORE_ORG
from automations.b2b_dispositions.config import TEXT_GROUP_ATT

# Colten Wright 2026-10-24 (Slack): the same list in his "SOUTHSHORE ORG" chat
# too, "we could just do SSO owners". Lucy 1 already texts that chat the board
# every morning. Its owners = the South Shore group on the Recruiting
# Dashboard (funnel_board.roster.SOUTH_SHORE_NAMES) — one list, so a South
# Shore add there lands here too. Each chat keeps its own "nothing changed"
# skip (`key` = the last-sent file name).
SSO_GROUP = GROUP_SOUTHSHORE_ORG

# Jairo Ruiz 2026-10-26 (Slack DM with Megan): the lines in his own
# "A PLAYERSSS" chat -- only A-Players and AMs are in it. Lucy 1 is a member
# (find_group 2026-10-26: exactly one chat, 16 people). The full name, not
# "A PLAYERS": that needle hits 6 chats. Eve the same day: the owners on
# Jairo's campaign, NDS -- so this chat gets NDS offices' sales for the owners
# on our Org board, not the South Shore list.
JAIRO_GROUP = "A PLAYERSSS"
JAIRO_CAMPAIGN = "nds"

# Carlos Hidalgo 2026-11-04 (Slack): the owners text in his "ATT B2B Leaders"
# chain once an hour, starting when the owners chat starts, titled with
# Alphalete in front. Same list as the owners chat, own "nothing changed" skip.
# The name lives in b2b_dispositions.config, like every other text to that chat.
CARLOS_GROUP = TEXT_GROUP_ATT
CARLOS_TITLE = "Alphalete Owner Sales Today"

# South Shore owners who text into the SSO chat but are NOT on the Recruiting
# Dashboard's South Shore group (no AppStream office there), so they can't ride
# SOUTH_SHORE_NAMES. Colten 2026-10-30: "make sure Samuel is added to Southshore
# org owners post ... moving forward".
SSO_EXTRA = ["Samuel Acay"]

# Listed and ranked in the SSO chat but NOT counted in its TOTAL. Raf 2026-11-04:
# "Can my sales be added here so I can compete in their chat? But don't add my
# sales to the total sales please." Not on SOUTH_SHORE_NAMES: he isn't South
# Shore, and that list also feeds the Recruiting Dashboard.
SSO_NOT_IN_TOTAL = ["Rafael Hidalgo"]

# Relay office keys that are not in the alert-office table (icd_alerts.offices)
# but do relay sales. Raf's own office relays as `rafael_hidalgo`.
OWNER_FALLBACK = {
    "rafael_hidalgo": "Rafael Hidalgo",
    "samuel": "Samuel Acay",
}

# ONE OFFICE RELAYING UNDER TWO KEYS. Since 2026-11-03 Raf's own MacBook (Lucy
# ECO, key `raf`) relays the same SaraPlus his Lucy 1 sweep relays as
# `rafael_hidalgo`; summed, the 9:50 PM text showed him at 52 for a 26-sale
# day (Megan: "Raf's sales are being doubled"). The old key is skipped for any
# day the new one has a reading; with no `raf` row the old row still counts.
SUPERSEDED_BY = {"rafael_hidalgo": "raf"}

# Raf 2026-11-04 (LUCY OWNERS CHAT): "an update every 30minutes" of the owners
# text. Only that chat: the plist fires at :15 and :45, and these chats -- which
# nobody asked to speed up -- still get one text an hour, on the :45.
HOURLY_CHATS = ("sso", "jairo")
# One an hour too, but on the :15: the owners chat's first text of the day is
# 12:15, and Carlos asked to start when it starts.
HOURLY_ON_THE_15 = ("carlos",)

# The selling day, Central. This is the guard the code applies, so a stray hand
# run at 9am texts nothing. weekday(): (first hour, last hour) inclusive.
WINDOW = {
    0: (12, 21), 1: (12, 21), 2: (12, 21), 3: (12, 21), 4: (12, 21),
    5: (12, 21),
}

# What went out last, per day — a send with exactly the same numbers as the
# previous one is skipped (an unchanged list every hour is noise).
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "owner_sales_hourly"

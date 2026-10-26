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

# Colten Wright 2026-10-24 (Slack): the same list in his "SOUTHSHORE ORG" chat
# too, "we could just do SSO owners". Lucy 1 already texts that chat the board
# every morning. Its owners = the South Shore group on the Recruiting
# Dashboard (funnel_board.roster.SOUTH_SHORE_NAMES) — one list, so a South
# Shore add there lands here too. Each chat keeps its own "nothing changed"
# skip (`key` = the last-sent file name).
SSO_GROUP = GROUP_SOUTHSHORE_ORG

<<<<<<< Updated upstream
# Jairo Ruiz 2026-10-26 (Slack DM with Megan): the same South Shore list in his
# own "A PLAYERSSS" chat. Lucy 1 is a member (find_group 2026-10-26: exactly one
# chat, 16 people). The full name, not "A PLAYERS": that needle hits 6 chats.
JAIRO_GROUP = "A PLAYERSSS"
=======
# Jairo Ruiz 2026-10-26 (Slack): the lines in his "A PLAYERSSS" chat too --
# only A-Players and AMs are in it. Eve: the owners on Jairo's campaign, NDS,
# so this chat gets NDS offices' sales for the owners on our Org board (not the
# South Shore list). Same name his ICD standings already go
# to (ICD Relay -> 'Office Channels' -> row `jairo15` -> 'Texts Approved JSON');
# resolve_group raises on 0 or 2+ hits, so a renamed chat fails loud.
JAIRO_GROUP = "A PLAYERSSS"
JAIRO_CAMPAIGN = "nds"
>>>>>>> Stashed changes

# Relay office keys that are not in the alert-office table (icd_alerts.offices)
# but do relay sales. Raf's own office relays as `rafael_hidalgo`.
OWNER_FALLBACK = {
    "rafael_hidalgo": "Rafael Hidalgo",
}

# The selling day, Central. The plist fires at :50 (after most offices' relay
# has caught the hour); this is the guard the code applies, so a stray hand run
# at 9am texts nothing. weekday(): (first hour, last hour) inclusive.
WINDOW = {
    0: (12, 21), 1: (12, 21), 2: (12, 21), 3: (12, 21), 4: (12, 21),
    5: (12, 21),
}

# What went out last, per day — a send with exactly the same numbers as the
# previous one is skipped (an unchanged list every hour is noise).
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "owner_sales_hourly"

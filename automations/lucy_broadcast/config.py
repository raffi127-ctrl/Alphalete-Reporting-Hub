"""Wiring for Lucy Broadcast — a member posts in ONE Slack channel and Lucy
re-sends that post (text, pictures, files) to a set list of Slack channels and
iMessage groups.

No secrets here: Slack uses the shared Lucy token (slack_metrics_post._client),
iMessage uses Lucy 1's Messages app (b2b_dispositions.text_post).

STATUS (2026-10-18): built, NOT live. Source = #lucy-broadcast; destinations are
blank until Raf/Megan send them. With blanks a live run refuses with a clear
message; --dry-run always works.
"""
from __future__ import annotations

import os

# --- 1) The Slack channel people post INTO ------------------------------------
# Paste the channel ID (Slack: channel name -> About -> bottom of the panel).
# Lucy Reporting must be a MEMBER if the channel is private (else Slack says
# channel_not_found). Channel membership is the allow-list — anyone in it can
# broadcast, so keep it to the people who should.
# #lucy-broadcast (private, 2026-10-18).
SOURCE_CHANNEL_ID = os.environ.get("LUCY_BROADCAST_CHANNEL_ID", "C0CA97W54D7")

# --- 2) Where every post goes -------------------------------------------------
# Slack: channel IDs (C…/G…), one per line. Lucy must be in each private one.
SLACK_DESTINATIONS: tuple[str, ...] = (
)

# iMessage: the group chat NAMES exactly as they show in Messages on Lucy 1.
# Resolved by name on every send (never a stored id — ids change when
# someone is added to the group).
IMESSAGE_GROUPS: tuple[str, ...] = (
)

# --- Optional lock-down -------------------------------------------------------
# Empty = anyone in the source channel can broadcast. To limit it, list Slack
# user ids (look one up with:  python -m automations.lucy_broadcast.run --whois EMAIL).
APPROVED_POSTERS: tuple[str, ...] = ()

# --- Timing -------------------------------------------------------------------
# A post is only sent once it's this old, so someone who hits Enter and then
# fixes a typo (edit) gets the FIXED version sent out.
SETTLE_SECONDS = 60

# How many recent channel messages to look at each run.
SCAN_LIMIT = 20

# Retry a failed destination on each 5-min tick, up to this many tries
# (6 = ~30 min), then give up and say so in the post's thread.
MAX_ATTEMPTS = 6

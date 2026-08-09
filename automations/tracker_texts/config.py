"""Which trackers text where.

The routing is deliberately the SAME groups b2b_dispositions already texts, so
the group NAMES live in one place — b2b_dispositions.config — and are imported
here, never re-typed. If Carlos renames a group or Lucy is re-added under a new
chat id, text_post.resolve_group() re-resolves by name on every send, so nothing
here has to change (see that module's docstring on why we never store a GUID).

To stop texting a tracker: empty its list (or delete the key). To add one: add a
tableau_screenshots pages.py id -> [group names]. Nothing else.
"""
from __future__ import annotations

from pathlib import Path

from automations.b2b_dispositions import config as b2b

# Reuse the exact group-name constants b2b_dispositions resolves against, so the
# two reports can never drift to slightly-different spellings of the same chat.
GROUP_ATT = b2b.TEXT_GROUP_ATT      # "ATT B2B Leaders" (trailing-space name; substring match)
GROUP_BOX = b2b.TEXT_GROUP_BOX      # "Box B2B"
GROUP_ALL = b2b.TEXT_GROUP_ALL      # "NEW A Players"

# tableau_screenshots pages.py id -> the iMessage groups that get its image.
# Carlos 2026-08-09:
#   "B2B ATT tracker (the first one posted) in the 'ATT B2B leaders' text chain &
#    'New A Players' text chain"     -> b2b_att_country
#   "B2B Box Tracker in the 'New A Players' & the 'Box B2B' chat" -> b2b_box
ROUTES = {
    "b2b_att_country": [GROUP_ATT, GROUP_ALL],
    "b2b_box":         [GROUP_BOX, GROUP_ALL],
}

# The only tracker ids this report ever touches — used by the mini-side trigger to
# decide whether a just-posted board should queue a text.
TARGET_IDS = tuple(ROUTES.keys())

# Captured PNGs + the per-(id, day) `.sent` idempotency markers live here on
# Lucy 2. Separate from tableau_screenshots' own output dir so a text re-capture
# can never be mistaken for (or clobber) the mini's posted image cache.
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "tracker_texts"


def route_for(tracker_id: str):
    """The groups a tracker id texts to, or [] if it isn't routed."""
    return list(ROUTES.get(tracker_id, []))


def caption(spec: dict, day) -> str:
    """The text that leads each send — mirrors the Slack reply caption
    ('B2B AT&T — Aug 9') so the groups read the same label the channel does.

    Builds the date by hand (no %-d / %-m): this only ever runs on Lucy 2 (macOS),
    but the house rule is no platform-specific strftime, and it costs nothing."""
    title = spec.get("title") or spec.get("id") or "Tracker"
    return f"{title} — {day.strftime('%b')} {day.day}"

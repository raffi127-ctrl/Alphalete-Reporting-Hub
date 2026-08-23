"""Which images text into which OWNER iMessage chats — Raf's 2026-08-23 ask.

    Alphalete owners - Real CHAT : all the trackers + the Org WOW sales board
    Alphalete A-Team chat        : the Org WOW sales board only

RUNS ON LUCY 1 — Messages there is signed in as alphaletereporting@gmail.com
(Megan 2026-08-23). This is a THIRD iMessage machine: Lucy 2 texts the B2B
tracker/disposition groups from `alphletegp`; do not merge the two — different
accounts, different chats.

Group names are resolved FRESH by name on every send (b2b_dispositions.
text_post.resolve_group — substring match, raises on 0 or 2+ hits, never stores
a GUID; see that module's docstring for why). The names below are exactly what
Raf typed; if the real chat names differ on Lucy 1, the first dry-run's
resolution error says so and this file is the one place to fix.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

from pathlib import Path

# The two chats, needles for resolve_group's substring match (AppleScript
# `contains`, case-insensitive). Real names per Megan's screenshots 2026-08-23:
#
#   "Alphalete Owners 🔥 - Real"    (NOT Raf's "…- Real CHAT" wording)
#   "Alphalete A-Team Chat🔥 🔥"
#
# The flame emojis are deliberately left OUT of the needles — emoji in an
# AppleScript literal is one more thing to escape — and the needles stop
# BEFORE the emoji so they match the real names as substrings. resolve_group
# raises on 2+ hits, so if a needle ever turns ambiguous the dry-run says so
# rather than texting the wrong room.
GROUP_OWNERS_REAL = "Alphalete Owners"
GROUP_A_TEAM = "Alphalete A-Team Chat"

# Routing.
TRACKER_GROUPS = [GROUP_OWNERS_REAL]
BOARD_GROUPS = [GROUP_OWNERS_REAL, GROUP_A_TEAM]

# "All the Trackers" = exactly what #alphalete-sales carries each morning: the
# default org-wide set, in post order. Read from tableau_screenshots so a
# tracker added/retired there is added/retired here with no second list.
SOURCE_ORG = "alphalete"


def source_channel() -> str:
    """#alphalete-sales — the channel whose posted PNGs we forward."""
    from automations.tableau_screenshots.slack_post import ORG_CHANNELS
    return ORG_CHANNELS[SOURCE_ORG][0]


def tracker_specs() -> list:
    """The tracker specs to forward, in the channel's post order."""
    from automations.tableau_screenshots import pages as pages_mod
    from automations.tableau_screenshots.slack_post import tracker_ids_for
    ids = tracker_ids_for(SOURCE_ORG, pages_mod.PAGES)
    return [pages_mod.by_id(i) for i in ids if pages_mod.by_id(i)]


# Downloaded PNGs + per-(item, day) `.sent` idempotency markers live here on
# Lucy 1. Own dir so nothing here can collide with tracker_texts (Lucy 2) or
# the mini's image caches.
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "owner_chat_texts"


def tracker_caption(spec: dict, day) -> str:
    """Same label the Slack thread reply carries, minus the *bold* markers
    (iMessage would show literal asterisks)."""
    title = spec.get("title") or spec.get("id") or "Tracker"
    return "%s - %s %d" % (title, day.strftime("%b"), day.day)


# The 7:30 pass sends ONE PDF (Raf 8/23: "so it's not a bunch of messages").
# It waits for every routed tracker to be in the Slack thread; from this time
# (CST) on it stops waiting and sends what's there, naming the gaps in the
# caption — a broken tracker must not hold the post hostage all day.
PDF_PARTIAL_AFTER = "09:00"


def trackers_pdf_caption(day, missing) -> str:
    cap = "Country Trackers — %s %d" % (day.strftime("%b"), day.day)
    if missing:
        cap += "  (not posted yet: %s)" % ", ".join(missing)
    return cap


def board_caption(day) -> str:
    """Dated for the day the numbers are FOR — yesterday, same rule as the
    board email's subject (the board only carries completed days)."""
    import datetime as dt
    d = day - dt.timedelta(days=1)
    return "Alphalete Org WOW Sales Board %d/%d" % (d.month, d.day)

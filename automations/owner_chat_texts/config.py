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

# The two chats, as Raf named them (2026-08-23, #claudecorrections-and-requests).
GROUP_OWNERS_REAL = "Alphalete owners - Real CHAT"
GROUP_A_TEAM = "Alphalete A-Team"

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


def board_caption(day) -> str:
    """Dated for the day the numbers are FOR — yesterday, same rule as the
    board email's subject (the board only carries completed days)."""
    import datetime as dt
    d = day - dt.timedelta(days=1)
    return "Alphalete Org WOW Sales Board %d/%d" % (d.month, d.day)

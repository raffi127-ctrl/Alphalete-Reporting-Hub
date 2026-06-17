"""Social presence collector.

HONEST SCOPE: every major platform (IG, FB, LinkedIn, X) blocks scraping and
gates real numbers behind their API. So for v1 this reports the *presence* of
each channel (from intake) and leaves follower/engagement metrics as
"needs API". That's deliberate — fake or guessed social numbers would be worse
than an honest "connect a source to unlock this". The engagement metrics that
matter arrive when we add the Meta API / a posting-API aggregator (deferred per
Megan, 2026-06-17).

It also surfaces which channels exist, and respects the posting blocklist
(Raf's personal LinkedIn is never treated as an Alphalete channel).
"""
from __future__ import annotations

from automations.brand_audit.collectors.base import CollectorResult, INFO
from automations.brand_audit.config import POSTING_BLOCKLIST

SOURCE = "social_public"

_CHANNELS = [
    ("instagram", "Instagram"),
    ("facebook", "Facebook"),
    ("linkedin", "LinkedIn"),
    ("twitter", "X / Twitter"),
]


def _blocked(url: str) -> bool:
    u = (url or "").lower()
    return any(b in u for b in POSTING_BLOCKLIST)


def collect(company) -> CollectorResult:
    res = CollectorResult(source=SOURCE)
    present = {}
    for field, label in _CHANNELS:
        url = getattr(company, field, "")
        present[field] = {
            "label": label,
            "url": url,
            "connected": bool(url),
            "postable": bool(url) and not _blocked(url),
            # populated only once a platform API / aggregator is connected:
            "followers": None,
            "engagement_rate": None,
        }

    connected = [p["label"] for p in present.values() if p["connected"]]
    res.metrics = {
        "channels_connected": len(connected),
        "channels": connected,
        # all None until an API source is added — see module docstring
        "followers_total": None,
        "avg_engagement_rate": None,
    }
    res.evidence["channels"] = present
    res.flag(INFO,
             "Follower/engagement numbers need a platform API (Meta) or a "
             "posting-API aggregator — not available from public pages. "
             f"Channels on file: {', '.join(connected) or 'none'}.")
    return res

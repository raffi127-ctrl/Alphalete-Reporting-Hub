"""Who already has a packet -- according to BLUE INK, not just our own log.

The ledger only knows what this tool sent. The team also sends by hand, all the
time: on 2026-08-24 they hand-sent 54 of this week's 58 in the morning, and a
--limit 1 test that trusted the (empty) ledger duplicated one of them. A person
with a live packet must never get a second one, no matter who sent the first.

So before sending, every candidate is checked against Blue Ink's OWN bundle
history by email. Reads don't touch the send quota, so this is free.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from automations.blueink_docs import blueink
from automations.blueink_docs.roster import NewStart

# A packet from a previous WEEK shouldn't block this week's send, but "sent 3
# days ago" always should. New starts run Monday-to-Monday, so a fortnight is a
# safe window: long enough to catch anything for this cohort, short enough that
# a rehire months later still gets docs.
LOOKBACK_DAYS = 14

# Statuses that mean "they have a live or finished packet" -- don't send again.
# A cancelled/declined/expired one is NOT blocking: that person genuinely needs
# a fresh packet.
BLOCKING = {"new", "ready", "pending", "sent", "started", "complete"}


def _recent_cutoff() -> dt.datetime:
    return dt.datetime.utcnow() - dt.timedelta(days=LOOKBACK_DAYS)


def already_has_packet(email: str) -> str:
    """Bundle id of a recent, live packet for this address, or "" if none.

    Uses Blue Ink's own search, which matches on signer email.
    """
    email = (email or "").strip().lower()
    if not email:
        return ""
    try:
        r = blueink._request("GET", "/bundles/",
                             params={"page": 1, "per_page": 50, "search": email})
    except Exception:
        # Fail CLOSED-ish: we can't prove they're clear, so say so loudly rather
        # than silently sending a possible duplicate.
        raise
    rows = r.get("results") if isinstance(r, dict) else r
    cutoff = _recent_cutoff()
    for b in rows or []:
        created = str(b.get("created", ""))[:19]
        try:
            when = dt.datetime.strptime(created, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
        if when < cutoff:
            continue
        status = blueink.BUNDLE_STATUS.get(str(b.get("status")), "")
        if status == "draft":
            continue                     # a draft was never delivered
        if status in BLOCKING:
            return str(b.get("id", "")) or "unknown"
    return ""


def screen(people: List[NewStart]) -> Dict[str, str]:
    """{email: blocking bundle id} for everyone who already has a packet."""
    out: Dict[str, str] = {}
    for p in people:
        bid = already_has_packet(p.email)
        if bid:
            out[p.email.strip().lower()] = bid
    return out

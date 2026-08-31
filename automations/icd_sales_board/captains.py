"""The 13 captains, read from the roster that already exists.

Captains are the people who get the daily Captainship Report email, so the
list and the brand colours come from captainship_drafts.config rather than a
second copy here — a captain added there appears on the site with no edit.

A captain is NOT a board owner. The 12 per-owner sales boards belong to
different people (Jackie LeRoy, Kinsey Guenther, George Hipolito…); only Atef
appears on both lists. Which owners sit under which captain is still an open
question, so nothing here pretends to know it: `owners` stays empty until
somebody tells us the mapping, and the site says so rather than inventing one.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Captain:
    key: str
    name: str
    flavor: str            # rafael | fiber | b2b | nds
    color: str             # their own brand colour, from the email drafts
    owners: tuple = ()     # board owners under them — UNKNOWN, see above


def _from_drafts() -> list:
    """The live roster. Falls back to nothing rather than a stale copy: a
    hand-maintained duplicate that drifts is worse than an empty list, because
    it looks right."""
    try:
        from automations.captainship_drafts import config as CD
    except Exception:
        return []
    out = []
    for c in getattr(CD, "CAPTAINS", []):
        out.append(Captain(key=c.key, name=c.display_name,
                           flavor=getattr(c, "flavor", ""),
                           color=getattr(c, "title_bg", "#444444")))
    return out


CAPTAINS = _from_drafts()
BY_KEY = {c.key: c for c in CAPTAINS}


def get(key: str):
    return BY_KEY.get((key or "").strip().lower())


def names() -> list:
    return [c.name for c in CAPTAINS]

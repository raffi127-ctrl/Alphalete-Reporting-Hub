"""Knock-board names that are ONE ownerville office, not a person.

Everywhere else the ownerville impersonation finds an office by its OWNER's
name on the Office Access list (`_find_owner_and_impersonate`), and the first
row with that name wins. That breaks when:

  * the owner has TWO offices — Angel Padilla holds 22400 (Azul Connections
    Inc) and 23858 (Azul Connections Inc 2nd); a name search takes whichever
    row comes first, and
  * the board is for the person who RUNS one of them, not for the owner.

Rafael, 2026-09-23 (mail "daily knocks"): Shealey Miller manages under Angel
Padilla; she gets her own knocks board in his and Chan's captainship reports
plus the 9 PM mail. Shealey, 2026-09-24: "It's would be Azul connections 2nd"
-> office 23858.

A name listed here is searched by OFFICE NUMBER on the Office Access list, and
the identity check accepts the session only if it landed on that number — the
owner's other office is refused, same as any other wrong office.

Keys are the board spelling (EXTRA_KNOCK_OWNERS, owners.py, zones.py all use
it). Matching is case- and spacing-insensitive.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# board name -> ownerville office number
OFFICE_PINS: Dict[str, str] = {
    "Shealey Miller": "23858",   # Azul Connections Inc 2nd (owner: Angel Padilla)
}


def _key(name) -> str:
    return " ".join(str(name or "").lower().split())


_BY_KEY = {_key(k): v for k, v in OFFICE_PINS.items()}


def pinned_office(name) -> Optional[str]:
    """The office number `name` is pinned to, or None for a normal owner."""
    return _BY_KEY.get(_key(name))


def label_is_office(label, office_id: str) -> bool:
    """True when ownerville's office label ("Angel Padilla (23858 - Azul
    Connections Inc 2nd)") is on `office_id` — the number, as a whole token."""
    return bool(office_id) and re.search(
        r"(?<!\d)%s(?!\d)" % re.escape(office_id), str(label or "")) is not None

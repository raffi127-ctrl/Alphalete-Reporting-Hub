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


# --- account-number FALLBACK for onboarded offices -------------------------
# A pin above REPLACES the name search. This only kicks in AFTER every name
# spelling has missed. Three new offices failed their first 9 PM knock board on
# a name the Office Access table spells differently — Jairo 9/29, Drew 9/28,
# Omar 10/26 ("Omar Mohammad" typed at onboarding, "Omar Mohamad" in
# ownerville) — and each one needed a code fix pushed to Lucy 3 while the board
# sat dark. Every onboarded office already carries its ownerville account
# number (`ov_account`, the Office Access table's first column), and a number
# does not have spellings. So a name that misses gets one more try by number
# before the board is given up, and the identity check accepts that number.
_ONBOARDED_FILES = (
    "automations/office_metrics/onboarded_offices.json",
    "automations/b2b_metrics/onboarded_offices.json",
)
_FALLBACK: Optional[Dict[str, str]] = None


def _digits(value) -> str:
    m = re.search(r"\d+", str(value or ""))
    return m.group(0) if m else ""


def _load_fallback(rows=None) -> Dict[str, str]:
    """{normalized name: account} from the onboarded offices. A name that maps
    to two DIFFERENT numbers is dropped — a guess between two offices is the
    exact mistake the identity check exists to stop."""
    if rows is None:
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        rows = []
        for rel in _ONBOARDED_FILES:
            try:
                data = json.loads((root / rel).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.extend(r for r in (data or []) if isinstance(r, dict))
    seen: Dict[str, set] = {}
    for r in rows:
        acct = _digits(r.get("ov_account"))
        if not acct:
            continue
        for field in ("knocks_office", "owner"):
            k = _key(r.get(field))
            if k:
                seen.setdefault(k, set()).add(acct)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def account_fallback(name) -> Optional[str]:
    """The onboarded ownerville account number for `name`, or None. Used only
    once the name search has failed — never instead of it."""
    global _FALLBACK
    if _FALLBACK is None:
        _FALLBACK = _load_fallback()
    return _FALLBACK.get(_key(name))


def label_is_office(label, office_id: str) -> bool:
    """True when ownerville's office label ("Angel Padilla (23858 - Azul
    Connections Inc 2nd)") is on `office_id` — the number, as a whole token."""
    return bool(office_id) and re.search(
        r"(?<!\d)%s(?!\d)" % re.escape(office_id), str(label or "")) is not None

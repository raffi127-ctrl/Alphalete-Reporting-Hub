"""Which LucyECO feeds belong to which ICD, and what each one sells.

The relay tab is keyed by the ECO feed's own key ('ryan', 'carlos-b2batt'),
and the board is keyed by ICD. For the first offices those happened to agree —
the office-metrics key for Cyrus is 'cyrus' — so nothing mapped between them,
and every self-signed-up office (Ryan, Carlos, Roshan) relayed live into a
board that could not find them (2026-09-22).

The map comes from the ICD Signup tab, which the sign-up flow writes with the
owner AND the campaign for every key it mints. One ICD can own more than one
feed: Carlos has 'carlos' (Box) and 'carlos-b2batt' (AT&T B2B).

Owners are matched on letters only — 'Roshan Amin  ahmad' is 'Roshan Amin
Ahmad', 'Aya Alkhafaji' is 'Aya Al-Khafaji' — because the sign-up form takes a
name as typed and the org's list spells it its own way.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

# How each campaign reads on the board. `family` decides which columns the
# board draws; the label is what an owner recognises.
CAMPAIGNS = {
    "att": ("AT&T Fiber", "att"),
    "att_fiber": ("AT&T Fiber", "att"),
    "b2b_att": ("AT&T B2B", "att"),
    "b2b_box": ("Box", "box"),
    "box": ("Box", "box"),
    "nds": ("NDS Wireless", "att"),
    "att_nds": ("NDS Wireless", "att"),
}

_CACHE: dict = {"at": 0.0, "feeds": None}
_TTL = 300


@dataclass(frozen=True)
class Feed:
    key: str          # the relay's office key
    owner: str        # as the sign-up recorded it
    campaign: str     # 'att', 'b2b_box', ...

    @property
    def label(self) -> str:
        return CAMPAIGNS.get(self.campaign, (self.campaign or "Sales", ""))[0]

    @property
    def family(self) -> str:
        """'att' or 'box' — which set of columns the board draws."""
        return CAMPAIGNS.get(self.campaign, ("", "att"))[1]


def norm(name: str) -> str:
    """Letters only, lower case. The only comparison two spellings survive."""
    return re.sub(r"[^a-z]", "", (name or "").lower())


def _signups() -> list:
    try:
        from automations.icd_signup import store as S
        return list(S.all_signups())
    except Exception:   # noqa: BLE001 — no sign-up tab is not an error here
        return []


def feeds(force: bool = False) -> dict:
    """{relay key: Feed} for every feed we know an owner for."""
    if (not force and _CACHE["feeds"] is not None
            and time.time() - _CACHE["at"] < _TTL):
        return _CACHE["feeds"]
    out: dict = {}
    for s in _signups():
        key = (s.office_key or "").strip().lower()
        if key and s.owner:
            out[key] = Feed(key, s.owner.strip(),
                            (getattr(s, "campaign", "") or "att").strip())
    # The pilots predate the sign-up form, so they are only in the office
    # metrics registry — whose key is the relay key for exactly these offices.
    # ONLY a key that has actually RELAYED counts: every office with a metrics
    # thread has a registry key, and treating those as ECO feeds listed Cody,
    # Haytham, Rashad, Salik and Isaiah as "signed up, not reporting" when none
    # of them ever signed up (2026-09-22).
    try:
        from automations.icd_sales_board import profiles as P
        from automations.icd_sales_board import relay_read as RR
        relayed = set(RR.offices())
        for name, p in P.load().items():
            if (p.office_key and p.office_key not in out
                    and p.office_key in relayed):
                out[p.office_key] = Feed(p.office_key, name,
                                         p.primary_campaign or "att")
    except Exception:   # noqa: BLE001
        pass
    _CACHE.update(at=time.time(), feeds=out)
    return out


def for_icd(icd: str) -> list:
    """Every feed this ICD owns, relaying ones first. [] when none."""
    want = norm(icd)
    mine = [f for f in feeds().values() if norm(f.owner) == want]
    try:
        from automations.icd_sales_board import relay_read as RR
        live = set(RR.offices())
    except Exception:   # noqa: BLE001
        live = set()
    # A test row ('ztest') never matches a real ICD, so it cannot leak in.
    return sorted(mine, key=lambda f: (f.key not in live, f.key))


def names_for(feed) -> list:
    """Every spelling this feed's owner goes by: the sign-up's, the org list's
    and the ICD Aliases sheet's.

    Tableau's Box view calls Roshan 'Roshan Ahmad'; his sign-up says 'Roshan
    Amin Ahmad'. Letters-only matching cannot bridge a dropped middle name,
    and the alias sheet is where that mapping already lives — so it is asked,
    rather than a spelling being patched in here."""
    out = [feed.owner]
    try:
        from automations.icd_sales_board import profiles as P
        want = norm(feed.owner)
        out += [n for n in P.load() if norm(n) == want]
        from automations.focus_office_att import aliases as A
        raw = A.load_aliases()
        for n in list(out):
            out += A.get_search_candidates(n, raw)
    except Exception:   # noqa: BLE001 — the sign-up spelling still works
        pass
    return list(dict.fromkeys(n for n in out if n))

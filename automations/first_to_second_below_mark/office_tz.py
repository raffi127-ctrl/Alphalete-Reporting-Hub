"""Which clock each office runs on, and which offices are due for an update now.

Rafael, 2026-09-21: every office is in a different time zone, and the point of
this report is catching a market that is slipping while there is still time to
fix it. So each office gets its update at ITS OWN 11:00 AM and 6:30 PM:

    11:00 AM local   the morning after: yesterday's callbacks are in, so the
                     earlier days of the week have moved (Friday's number is
                     re-checked Monday at 11)
     6:30 PM local   the day closed: today's number

Seen from Central that is eight passes a day, one per zone and slot:

             11:00 local    6:30 PM local
    Eastern  10:00 CT       5:30 PM CT
    Central  11:00 CT       6:30 PM CT
    Mountain 12:00 CT       7:30 PM CT
    Pacific   1:00 PM CT    8:30 PM CT

The launchd agent fires at all eight; each pass works out from the clock which
offices are due (`due`) and pulls only those. Deciding from the clock, not from
a --zone argument, is what keeps daylight saving and Arizona right with one
fixed agent: an office in America/Phoenix simply lands in whichever CT pass
matches its local 11:00 that season.

WHERE THE ZONES COME FROM: `captainship_night_knocks.zones`, the table the
night-knocks send uses (addresses read off ownerville, checked by a person).
Owners that table cannot place are put on the CENTRAL clock -- the company's
own, and what this report ran on before -- and every run names them, so the
list of offices still missing a real zone never goes quiet.
"""
from __future__ import annotations

import datetime as dt
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from automations.captainship_night_knocks import zones as _zones

SLOTS: Tuple[Tuple[int, int], ...] = ((11, 0), (18, 30))
# How late a pass may start and still count as that slot. launchd can hold a
# job behind the Chrome profile lock, and a pass that starts 20 minutes late
# must still pick up its offices -- but never reach into the NEXT zone's slot,
# which is 60 minutes away.
LATE_OK_MIN = 45
FALLBACK_ZONE = "America/Chicago"

# Offices whose owner name the zones table spells differently. Only spellings
# the ICD Aliases sheet does not already bridge belong here.
SPELLINGS = {
    "max aden": "Maxamad Aden",
    "jose velazques": "Jose Velasquez",
}


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split()).lower()


_ALIASES_RAW: Optional[dict] = None


def _alias_candidates(owner: str) -> List[str]:
    global _ALIASES_RAW
    try:
        from automations.focus_office_att.aliases import (get_search_candidates,
                                                          load_aliases)
        if _ALIASES_RAW is None:
            _ALIASES_RAW = load_aliases()
        return list(get_search_candidates(owner, _ALIASES_RAW))
    except Exception:                                     # noqa: BLE001
        return []                     # no alias sheet: the direct lookups still run


def zone_for(owner: str, *, use_aliases: bool = True) -> Optional[str]:
    """The owner's IANA zone, or None when nobody has placed that office."""
    tries = [owner, _plain(owner)]
    if _plain(owner) in SPELLINGS:
        tries.append(SPELLINGS[_plain(owner)])
    if use_aliases:
        tries += _alias_candidates(owner)
    for name in tries:
        z = _zones.zone_for(name)
        if z:
            return z
    return None


def zone_or_fallback(owner: str, **kw) -> Tuple[str, bool]:
    """(zone, known). Unknown offices run on the Central clock."""
    z = zone_for(owner, **kw)
    return (z, True) if z else (FALLBACK_ZONE, False)


def label(zone: str) -> str:
    return _zones.ZONE_LABEL.get(zone, zone)


def slot_text(slot: Tuple[int, int]) -> str:
    h, m = slot
    return dt.time(h, m).strftime("%I:%M %p").lstrip("0")


def due_slot(zone: str, now: dt.datetime) -> Optional[Tuple[int, int]]:
    """The slot an office in `zone` is due for at `now`, if any."""
    local = now.astimezone(ZoneInfo(zone))
    for h, m in SLOTS:
        start = local.replace(hour=h, minute=m, second=0, microsecond=0)
        if dt.timedelta(0) <= local - start <= dt.timedelta(minutes=LATE_OK_MIN):
            return (h, m)
    return None


def due(owners: Iterable[str], now: dt.datetime, **kw
        ) -> Tuple[List[str], Optional[Tuple[int, int]], List[str]]:
    """(owners due now, the slot they are due for, the zone labels in this pass).

    Every zone's 11:00 and 6:30 PM fall on different CT hours, so one pass
    only ever holds one slot."""
    picked: List[str] = []
    slot = None
    labels: List[str] = []
    for o in owners:
        z, _ = zone_or_fallback(o, **kw)
        s = due_slot(z, now)
        if s is None:
            continue
        picked.append(o)
        slot = slot or s
        if label(z) not in labels:
            labels.append(label(z))
    return picked, slot, labels


def unknown(owners: Iterable[str], **kw) -> List[str]:
    return [o for o in owners if zone_for(o, **kw) is None]


def by_label(owners: Iterable[str], **kw) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for o in owners:
        out.setdefault(label(zone_or_fallback(o, **kw)[0]), []).append(o)
    return out

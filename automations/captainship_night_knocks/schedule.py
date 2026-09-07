"""WHEN each captain's next wave is owed, in the clock that actually decides it.

Pure arithmetic. Nothing here opens a browser, reads a Sheet or sends a mail:
`due()` takes `now` as a parameter and returns decisions, so the whole schedule
is testable at 3 AM in July without waiting for 9 PM anywhere. Same split as
knocks_intraday.schedule, and for the same reason.

THE FIRING UNIT IS THE IANA ZONE, NOT THE WAVE NAME. "Mountain" looks like one
wave and is two for most of the year: Phoenix does not observe DST, so from
March to November 9 PM in Phoenix and 9 PM in Denver are an hour apart. Firing
on a label would hand one of them a board an hour off its own evening — the
exact failure office-local scheduling exists to prevent. So each zone is
evaluated on its own, and zones that land on the SAME INSTANT are merged into
one email afterwards (Eastern's three zones always merge; Mountain's two merge
in winter and split in summer, correctly, with no code change).

MON-SAT, like the 9 PM Slack board it mirrors (Megan 2026-08-25). Sunday has no
knocking day to close.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set
from zoneinfo import ZoneInfo

from automations.captainship_night_knocks import zones as Z

# 9:00 PM in the office's own clock. Raf's ask, verbatim: "at 9:00pm local
# time". This is a moment in a rep's day — the day is finished — which is why
# it is local and not one org-wide fire.
HOUR, MINUTE = 21, 0

# How late a wave may still go out. Covers the scheduler tick plus a busy box.
# MUST be >= the tick or a wave can fall between two passes and never fire.
# Deliberately smaller than knocks_intraday's sibling constant is NOT the case:
# keep them equal, because both are sized against the same launchd interval.
GRACE_MIN = 15

# Python weekday(): Mon=0 … Sun=6.
WORKING_WEEKDAYS = frozenset({0, 1, 2, 3, 4, 5})


@dataclass(frozen=True)
class Due:
    """One email to send: this captain, these ICDs, this wave, tonight."""
    captain_key: str
    label: str                 # "Eastern" / "Central" / …
    zones: Sequence[str]       # the IANA zones that fired together
    icds: Sequence[str]
    local_date: dt.date        # the day these ICDs just finished knocking
    fire_local: dt.datetime

    @property
    def marker(self) -> str:
        """Idempotency key. The DATE IS THE ICDs' OWN, never the runner's: at
        9 PM Eastern it is already tomorrow in UTC, and "has this captain had
        his Eastern wave" is a question about their calendar, not the mini's.

        The zones are in the key, not the label, so a summer Mountain split
        cannot collide two different sends onto one marker.
        """
        return (f"{self.captain_key}:{'+'.join(sorted(self.zones))}:"
                f"{self.local_date.isoformat()}")


def _fire_instant(zone: str, local_date: dt.date) -> dt.datetime:
    """The UTC instant at which `zone` hits 9 PM on `local_date`."""
    tz = ZoneInfo(zone)
    return dt.datetime.combine(
        local_date, dt.time(HOUR, MINUTE), tzinfo=tz
    ).astimezone(dt.timezone.utc)


def _zone_is_due(zone: str, now_utc: dt.datetime):
    """(local_date, fire_local) if `zone` is inside its window, else None.

    Checks the zone's own TODAY and YESTERDAY. Yesterday matters at the edges:
    just after midnight UTC it is still the previous local day in the west, and
    a run that starts a few minutes late must still find the wave it missed
    rather than skipping to tomorrow.
    """
    tz = ZoneInfo(zone)
    local_now = now_utc.astimezone(tz)
    for day in (local_now.date(), local_now.date() - dt.timedelta(days=1)):
        if day.weekday() not in WORKING_WEEKDAYS:
            continue
        fire = _fire_instant(zone, day)
        age = (now_utc - fire).total_seconds() / 60.0
        if 0 <= age <= GRACE_MIN:
            return day, fire.astimezone(tz)
    return None


def due(now_utc: dt.datetime, rosters: Dict[str, Iterable[str]],
        done: Optional[Set[str]] = None) -> List[Due]:
    """Every (captain, wave) owed an email right now.

    `rosters` is {captain_key: [ICD name, …]} — the Org Sales Board roster, which
    is truth. ICDs whose zone is unknown are not scheduled at all; the caller
    reports them via `zones.unconfirmed()` rather than guessing them into a wave.

    `done` is the marker set already sent tonight. Passing it is what makes a
    second tick in the same window a no-op instead of a duplicate reply landing
    in the captain's thread.
    """
    done = done or set()
    out: List[Due] = []
    for captain_key in sorted(rosters):
        icds = [i for i in rosters[captain_key] if Z.zone_for(i)]
        by_zone: Dict[str, List[str]] = {}
        for icd in icds:
            by_zone.setdefault(Z.zone_for(icd), []).append(icd)

        # Evaluate each zone alone, then merge the ones that fired on the same
        # instant into a single email — see the module docstring.
        fired = {}
        for zone, members in by_zone.items():
            hit = _zone_is_due(zone, now_utc)
            if hit is None:
                continue
            local_date, fire_local = hit
            key = _fire_instant(zone, local_date)
            grp = fired.setdefault(key, {"zones": [], "icds": [],
                                         "date": local_date,
                                         "local": fire_local})
            grp["zones"].append(zone)
            grp["icds"].extend(members)

        for _instant, grp in sorted(fired.items()):
            labels = {Z.ZONE_LABEL.get(z, z) for z in grp["zones"]}
            label = "/".join(sorted(labels))
            d = Due(captain_key=captain_key, label=label,
                    zones=tuple(sorted(grp["zones"])),
                    icds=tuple(grp["icds"]), local_date=grp["date"],
                    fire_local=grp["local"])
            if d.marker in done:
                continue
            out.append(d)
    return out

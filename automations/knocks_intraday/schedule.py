"""WHICH office is due for WHICH slot, right now — in that office's own clock.

Cody Cannon, Slack DM 2026-08-24: "Posting the knock metrics for the day in the
slack every day at specific times! 2pm to track first knocks / 5:15 to track
knocks into the start of money lap / 9pm to track eod knocks." Raf, the next
morning, asked for the 9 PM board org-wide. Megan settled the clock question on
2026-08-25: **each office's own local time**, all three slots, Mon-Sat.

THE THREE TIMES ARE MOMENTS IN A REP'S DAY, NOT A REPORTING SCHEDULE. That is
why they are local. 2 PM is "did we get out the door"; 5:15 is the money lap
starting; 9 PM is the day finished. Fired on one org-wide clock, an Eastern
office would get its "first knocks" board at 3 PM — an hour into the afternoon
it was meant to be checking on. Four of the eleven enrolled offices are Eastern
(aya, hammad, salik, nii), so this is not a hypothetical.

NOTHING HERE TOUCHES THE NETWORK OR THE CLOCK IT DOESN'T OWN. `due()` takes
`now` as a parameter and returns decisions; the caller supplies the time, does
the pulling and the posting, and owns the marker store. That split is what lets
the whole schedule be tested at 3 AM in July without waiting for 5:15 PM.

    from automations.knocks_intraday import schedule
    for d in schedule.due(dt.datetime.now(dt.timezone.utc), offices, done):
        ...  # d.office, d.slot.label, d.local_date
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Slot:
    key: str        # stable id used in markers + the CLI. never re-spell it.
    hour: int
    minute: int
    label: str      # what the post calls this moment


# The three moments, in office-local time. Every one of them is a partial day —
# even EOD, which is why the morning board must still re-collect the date (see
# run.py's no-morning-reuse note).
SLOTS = (
    Slot("first", 14, 0,  "First Knocks"),
    Slot("money", 17, 15, "Money Lap"),
    Slot("eod",   21, 0,  "End of Day"),
)

SLOTS_BY_KEY = {s.key: s for s in SLOTS}

# How late a slot may still fire. Covers the launchd tick interval plus a busy
# box. MUST be >= the tick, or a slot can fall between two passes and never run
# — the same trap card_scheduler's GRACE_MIN guards against.
GRACE_MIN = 15

# Mon-Sat (Megan 2026-08-25). Python weekday(): Mon=0 … Sun=6.
WORKING_WEEKDAYS = frozenset({0, 1, 2, 3, 4, 5})


@dataclass(frozen=True)
class Due:
    """One board to produce: this office, this slot, this office-local date."""
    office: object          # office_metrics.offices.Office
    slot: Slot
    local_date: dt.date
    local_now: dt.datetime

    @property
    def marker(self) -> str:
        """Idempotency key. The DATE IS THE OFFICE'S OWN, never the runner's:
        at 9 PM Eastern it is already the next day in some clocks and still the
        same day in others, and 'has this office had its 9 PM board' is a
        question about the office's calendar, not the mini's."""
        return marker_for(getattr(self.office, "key", "?"), self.slot,
                          self.local_date)


def marker_for(office_key: str, slot: Slot, local_date: dt.date) -> str:
    return f"{office_key}:{slot.key}:{local_date.isoformat()}"


def office_zone(office) -> ZoneInfo:
    """The office's own zone. Falls back to the registry default rather than
    raising: a missing timezone should cost an hour of accuracy for one office,
    never the whole slot for everyone. `unconfirmed_timezones()` is how that
    fallback gets surfaced instead of hidden."""
    from automations.office_metrics.offices import DEFAULT_TIMEZONE
    return ZoneInfo(getattr(office, "timezone", "") or DEFAULT_TIMEZONE)


def local_now(office, now: dt.datetime) -> dt.datetime:
    """`now` (any aware datetime) as this office reads it off the wall."""
    if now.tzinfo is None:
        raise ValueError(
            "now must be timezone-aware — a naive datetime silently means "
            "'whatever tz this machine happens to run in', which is the bug "
            "this module exists to prevent.")
    return now.astimezone(office_zone(office))


def slot_window(office, slot: Slot, now: dt.datetime) -> tuple:
    """(fire_time, deadline) for `slot` on the office-local day containing
    `now`. Both are aware datetimes in the office's zone."""
    here = local_now(office, now)
    fire = here.replace(hour=slot.hour, minute=slot.minute,
                        second=0, microsecond=0)
    return fire, fire + dt.timedelta(minutes=GRACE_MIN)


def is_due(office, slot: Slot, now: dt.datetime,
           done: Optional[Set[str]] = None) -> bool:
    """Is this office owed this slot's board at `now`?

    Four ways to be not-due, all of them silent and all of them correct:
      * it is Sunday where the office is,
      * the moment hasn't arrived yet in the office's own clock,
      * the grace window has closed (a missed slot is NOT posted hours late —
        a 2 PM 'first knocks' board landing at 6 PM is worse than nothing),
      * this office already got this slot today.
    """
    here = local_now(office, now)
    if here.weekday() not in WORKING_WEEKDAYS:
        return False
    fire, deadline = slot_window(office, slot, now)
    if not (fire <= here < deadline):
        return False
    if done and marker_for(getattr(office, "key", "?"), slot,
                           here.date()) in done:
        return False
    return True


def due(now: dt.datetime, offices: Iterable, done: Optional[Set[str]] = None
        ) -> List[Due]:
    """Every (office, slot) owed a board at `now`, in registry order.

    Returns [] most of the time, which is the normal answer for a job that
    ticks every few minutes — the caller should do nothing at all, not open a
    browser to discover there is nothing to do."""
    out: List[Due] = []
    for office in offices:
        for slot in SLOTS:
            if is_due(office, slot, now, done):
                here = local_now(office, now)
                out.append(Due(office=office, slot=slot,
                               local_date=here.date(), local_now=here))
    return out


def next_fire(office, now: dt.datetime, slots=None) -> Optional[dt.datetime]:
    """The office's next slot time at or after `now`, skipping Sundays. Used to
    print a human-readable 'nothing until …' line in the run log, so a quiet
    tick is visibly quiet-on-purpose rather than quiet-because-broken.

    `slots` is the slots THIS office is actually enrolled for — pass it, or the
    log promises an office a 2 PM board it is not on the roster for."""
    slots = SLOTS if slots is None else tuple(slots)
    if not slots:
        return None
    here = local_now(office, now)
    for day_offset in range(0, 8):
        day = here + dt.timedelta(days=day_offset)
        if day.weekday() not in WORKING_WEEKDAYS:
            continue
        for slot in slots:
            fire = day.replace(hour=slot.hour, minute=slot.minute,
                               second=0, microsecond=0)
            if fire >= here:
                return fire
    return None


def describe(now: dt.datetime, offices: Iterable, slots_for=None) -> List[str]:
    """One line per office: its local time and what it is next owed. The run
    log prints this on an idle tick so a silent night is auditable.

    `slots_for(office) -> slots` scopes each line to what that office is
    enrolled for; without it every office is described against all three."""
    lines = []
    for office in offices:
        here = local_now(office, now)
        slots = SLOTS if slots_for is None else tuple(slots_for(office))
        nxt = next_fire(office, now, slots)
        key = getattr(office, "key", "?")
        tz = getattr(office, "timezone", "?")
        if nxt is None:
            lines.append(f"{key:10} {tz:30} local {here:%a %H:%M}  "
                         "no upcoming slot")
            continue
        which = next((s.label for s in slots
                      if (s.hour, s.minute) == (nxt.hour, nxt.minute)), "?")
        lines.append(f"{key:10} {tz:30} local {here:%a %H:%M}  "
                     f"next {nxt:%a %H:%M} ({which})")
    return lines

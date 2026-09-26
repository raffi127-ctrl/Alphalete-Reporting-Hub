"""Which D2D OBCL tab is which week — one parser, four choice policies.

Four modules used to carry their own "read the date out of the tab title", and
comparing them on the same inputs (2026-09-26) found two real faults, not just
duplication:

    title               today        blueink      headshots    followup  apex
    D2D OBCL 9.28       2026-09-26   2026-09-28   2026-09-28   9.28      ok
    D2D OBCL 9/28       2026-09-26   2026-09-28   2026-09-28   None      None
    D2D OBCL 9.28.26    2026-09-26   2026-09-28   2026-09-28   28.26     None
    D2D OBCL 1.4        2026-12-21   2027-01-04   2026-01-04   1.4       None
    D2D OBCL WEEK 9.28  2026-09-26   2026-09-28   2026-09-28   9.28      None

  * `headshots` inferred the year in ONE direction only — it could pull a date
    back a year but never push it forward. So the January tab the team builds in
    late December resolved to January of the year just gone, which sorts as the
    OLDEST tab in the book: `find_week_tab` takes the newest, so it would
    quietly pick a different tab and tick rows on the wrong week. A late-December
    fault, which is exactly the kind that ships.
  * `new_start_followup` matched on (month, day) with no year and a '.'-only
    separator, so "9.28.26" parsed as month 28 / day 26. It never misfired only
    because no month is 28 — the tab simply went invisible, and the Saturday
    roll call raises "No OBCL tab for the week of ...". The day Aisha puts the
    year in a tab name, that report stops.

WHAT IS SHARED AND WHAT IS NOT. The PARSE is shared; the CHOICE is not. Each
caller wants a different tab and the difference is load-bearing:

    blueink / headshots   the NEWEST dated tab — the one the team just built
    new_start_followup    the tab for an EXACT Monday, or an error. Falling back
                          to the newest would text last week's leaders about
                          last week's new starts.
    apex_new_starts       the tab falling inside a given board week
    headshots (2nd)       newest dated tabs, THEN the rolling stack, because a
                          headshot often arrives after that week's tab is gone

STRICT ON PURPOSE. The title must be the prefix and then nothing but the date.
The looser `search`-to-end that two of the four used also accepts
"D2D OBCL WEEK 9.28", and the two failure modes are not equals: missing a tab is
loud (the report refuses and says no dated tab was found), while picking the
WRONG tab is silent and writes over somebody's good rows. So: reject what we do
not recognise and let the caller shout.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Iterable, List, Optional, Tuple

from automations.shared.new_start_steps import DATED_TAB_PREFIX

# The remainder after the prefix, and NOTHING else: m.d, m.d.yy or m.d.yyyy,
# with '.' or '/' as the separator ("9/28" has been seen).
_DATE_ONLY = re.compile(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$")


def _remainder(title: str) -> Optional[str]:
    """What follows the 'D2D OBCL' prefix, or None if the prefix isn't there."""
    t = " ".join((title or "").split())
    if not t.lower().startswith(DATED_TAB_PREFIX.lower()):
        return None
    return t[len(DATED_TAB_PREFIX):].strip()


def is_rolling(title: str) -> bool:
    """The undated all-weeks stack — exactly "D2D OBCL", no date after it."""
    return _remainder(title) == ""


def tab_date(title: str, today: Optional[dt.date] = None) -> Optional[dt.date]:
    """'D2D OBCL 8.24' -> date(2026, 8, 24). None if it isn't a dated OBCL tab.

    With no year in the title the nearest one is inferred, in BOTH directions:
    "12.28" read in January is the December just gone, and "1.4" read in
    December is the January coming. Getting the second of those wrong is the
    headshots fault described above.
    """
    rest = _remainder(title)
    if not rest:
        return None
    m = _DATE_ONLY.match(rest)
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
    today = today or dt.date.today()
    if year:
        year = int(year)
        if year < 100:
            year += 2000
    else:
        year = today.year
        # Month numbers, not day counts: a tab is named for a Monday within a
        # few weeks either way, so a gap over six MONTHS means the year rolled.
        if month - today.month > 6:
            year -= 1
        elif today.month - month > 6:
            year += 1
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None          # 2.30, 13.1 — a typo, not a week


def dated(titles: Iterable[str],
          today: Optional[dt.date] = None) -> List[Tuple[dt.date, str]]:
    """[(date, title)] for every dated tab, NEWEST FIRST. Rolling tab excluded."""
    out = [(d, t) for t in titles for d in (tab_date(t, today),) if d]
    return sorted(out, key=lambda p: p[0], reverse=True)


def newest(titles: Iterable[str],
           today: Optional[dt.date] = None) -> Optional[Tuple[dt.date, str]]:
    """The newest dated tab outright — not the newest in the past.

    The team keeps one dated tab and rolls it forward: on 2026-08-30 the only
    dated tab was "D2D OBCL 8.31", next week's. An "on or before today" rule
    would have skipped it.
    """
    found = dated(titles, today)
    return found[0] if found else None


def for_week(titles: Iterable[str], monday: dt.date,
             today: Optional[dt.date] = None) -> Optional[str]:
    """The tab dated exactly `monday`, or None. Never a near miss."""
    for d, title in dated(titles, today or monday):
        if d == monday:
            return title
    return None


def in_week(titles: Iterable[str], week_start: dt.date,
            today: Optional[dt.date] = None) -> Optional[str]:
    """The tab whose date falls inside week_start .. week_start+6, earliest win.

    A board week, not a single Monday: apex matches a tab to the week it is
    reconciling.
    """
    best = None
    for d, title in dated(titles, today or week_start):
        if week_start <= d <= week_start + dt.timedelta(days=6):
            if best is None or d < best[0]:
                best = (d, title)
    return best[1] if best else None

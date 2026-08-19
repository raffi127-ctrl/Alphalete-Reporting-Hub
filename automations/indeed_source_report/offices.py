"""Which offices this report pulls — derived from the funnel board's roster.

Deliberately NOT a second hand-maintained list. `funnel_board/roster.py` already
carries the org's 17 and Carlos's captainship of 13 (they overlap on Carlos and
Atef, so the union is 28), it already holds the AppStream office ids, and it
already uses the AppStream spelling of each name. A second copy here would drift
the first time someone gets an office.

roster's `owner` field (what AppStream's own switcher calls them) is why name
lookup alone is not enough: Salik Mallick's office is listed under "Muhammad UI
Haque" and Kash Rai's under "Akashdeep Rai".
"""
from __future__ import annotations

import datetime as dt

from automations.funnel_board.roster import ORG, CAPTAINSHIP


def _dedupe():
    seen, out = set(), []
    for name, oid, _owner in list(ORG) + list(CAPTAINSHIP):
        if oid is None or oid in seen:
            continue          # no office yet, or already counted via the other list
        seen.add(oid)
        out.append((oid, name))
    return out


OFFICES = _dedupe()

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def month_window(tag=None, today=None):
    """(period label, range label, start, end) for a YYYY-MM tag, mm-dd-yyyy.

    The CURRENT month ends today, not at month end — a partial month is the point
    of refreshing it three times a day.
    """
    today = today or dt.date.today()
    y, mo = (int(x) for x in tag.split("-")) if tag else (today.year, today.month)
    start = dt.date(y, mo, 1)
    if (y, mo) == (today.year, today.month):
        end = today
    else:
        nxt = dt.date(y + (mo == 12), (mo % 12) + 1, 1)
        end = nxt - dt.timedelta(days=1)
    f = "%m-%d-%Y"
    return ("%s %d" % (MONTH_NAMES[mo - 1], y),
            "%s to %s" % (start.strftime(f), end.strftime(f)),
            start.strftime(f), end.strftime(f))

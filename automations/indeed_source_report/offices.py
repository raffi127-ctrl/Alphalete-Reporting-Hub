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

# The roster is the source of truth WHEN IT IS PRESENT. It arrived on a branch
# that had not reached main yet, and a plain import made this whole report a
# ModuleNotFoundError on any runner that pulled main — so fall back to a frozen
# copy rather than fail. Once roster.py lands on main this stops being used and
# the two can never drift, because the import wins.
try:
    from automations.funnel_board.roster import ORG, CAPTAINSHIP
    _SOURCE = "funnel_board.roster"
except ImportError:                                   # roster not on this checkout
    _SOURCE = "frozen fallback (funnel_board.roster absent)"
    # (name, office id, AppStream owner) — resolved from the #searchMC picker
    # 2026-08-19. The owner column is why name lookup alone is not enough:
    # Salik Mallick's office is listed under "Muhammad UI Haque".
    ORG = [
        ("Atef Choudhury", "23467", "Atef Choudhury"),
        ("Aya Al-Khafaji", "22992", "Aya Al-Khafaji"),
        ("Carlos Hidalgo", "11580", "CARLOS HIDALGO"),
        ("Cody Cannon", "21151", "Cody Cannon"),
        ("Cyrus Wade", "22815", "Cyrus Wade"),
        ("Drew Tepper", "22583", "Drew Tepper"),
        ("Haytham Nagi", "22524", "Haytham Nagi"),
        ("Isaiah Revelle", "19717", "Isaiah Revelle"),
        ("Jacob Dover", "23607", "Jacob Dover"),
        ("Kash Rai", "22177", "Akashdeep Rai"),
        ("Khalil Mansour", "11901", "KHALIL MANSOUR"),
        ("Maxamad-Amin Aden", "23066", "Maxamad Aden"),
        ("Rafael Hidalgo", "11280", "Rafael Hidalgo"),
        ("Rashad Reed", "23411", "Rashad Reed"),
        ("Roshan Amin", "19833", "Roshan Amin Ahmad"),
        ("Ryan McSpadden", "22820", "Ryan McSpadden"),
        ("Salik Mallick", "21328", "Muhammad UI Haque"),
    ]
    CAPTAINSHIP = [
        ("Carlos Hidalgo", "11580", "CARLOS HIDALGO"),
        ("Atef Choudhury", "23467", "Atef Choudhury"),
        ("Jamis Garay", "19592", "Jamis Garay"),
        ("Jackie LeRoy", "22358", "Jackie LeRoy"),
        ("Noah Dubale", "23356", "Noah Dubale"),
        ("Jeff Starr", "15031", "Jeffrey Starr"),
        ("Kinsey Guenther", "11906", "Kinsey Guenther"),
        ("Vincent Smith", "23318", "Vincent Smith"),
        ("George Hipolito", "11296", "George Hipolito"),
        ("Justin Wood", "22192", "Justin Wood"),
        # Two offices answer to "Joshua Murphy"; Carlos confirmed 21770.
        ("Joshua Murphy", "21770", "Joshua Murphy"),
        ("Joey Ramirez", "23206", "Joey Ramirez"),
        ("Dhyey Patel", "22767", "Dhyey Patel"),
    ]


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

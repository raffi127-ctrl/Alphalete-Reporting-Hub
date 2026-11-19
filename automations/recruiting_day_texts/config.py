"""Recruiting day texts (Megan 2026-11-13): two iMessages to an ICD's group.

    ~7:30 AM  Good morning -- today's 1st rounds and 2nd rounds BY TIME SLOT,
              plus the new starts by name. A picture laid out like
              AppStream's Calendar > "Timeslot Count" page.
    ~4:00 PM  Only if the office had new starts today: "#/# new starts
              showed -- x% retention" + the names of those who showed.

Everything is read off the office's Retention Details report (p=701) for
TODAY's column. The detail pages give each person's interview date/time,
which is what the time slots are built from -- checked 2026-11-13 on Raf's
office against the Timeslot Count page: 76 1st rounds / 29 2nd rounds, every
slot the same. Timeslot Count alone could not be used: it has no new-start
names.

Adding an office: one entry in OFFICES. `mode` is "dry" until Megan says
go -- a dry office renders and logs, it never texts.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict


@dataclass(frozen=True)
class Office:
    key: str              # LucyEco office key -> its approved iMessage groups
    appstream_id: str     # ApplicantStream office id
    owner: str            # full name
    team: str             # the ICD's company: "Good Morning <team> Team". REQUIRED --
                          # a missing one must not silently read "Alphalete".
    group: str = ""       # WHICH of the office's approved groups gets these (one
                          # per ICD, Megan 2026-11-13). Must be on the relay's
                          # Office Channels tab -- found by its pinned people.
    tz: str = "America/Chicago"   # office local time (from their ECO sign-up)
    mode: str = "dry"     # "dry" = read + log only | "live" = texts | "hold" = skip

    @property
    def first_name(self) -> str:
        return (self.owner.split() or [""])[0]


# Office-local send times. The read starts at the trigger and the picture lands
# a few minutes later (Lucy 1 sends it).
MORNING_LOCAL = (7, 0)       # trigger; text lands ~7:15-7:30
SHOWED_LOCAL = (15, 45)      # trigger; text lands ~4:00
DUE_WINDOW_MIN = 45          # a trigger this late still counts (never reaches the next zone)

# RED ALERT: today's 1st or 2nd rounds below this share of the same weekday's
# 7am count over the last LOOKBACK_WEEKS weeks (morning vs morning -- see
# read.morning_usual for why never vs a full day) (Megan 2026-11-13: "lower than your
# typical number scheduled ... reach out to your recruiting team"). Past days are
# FINAL counts and the morning read is before same-day bookings land, so the bar
# is set below 100% on purpose.
LOW_SHARE = 0.75
LOW_MIN_AVG = 5              # an office that usually has <5 is never "low"
LOOKBACK_WEEKS = 4
MIN_HISTORY = 2              # mornings on record before the * can show

# Every ECO office with an approved iMessage group AND an AppStream account
# Lucy's login can see (mapped 2026-11-13 from the relay's Office Channels tab
# + the 'AppStream Offices' list; zones from each sign-up). Team names come
# from the AppStream office name with Inc/Management/Marketing/... dropped.
# EVERY OFFICE STARTS "dry". Flip one to "live" to start texting it.
OFFICES: Dict[str, Office] = {
    # LEFT OUT: nicolas / Nico Murrugarra -- no AppStream account Lucy's login can see
    "aiden": Office(key="aiden", appstream_id="18903", owner="Aiden Atoori",
                  team="Atoori", group="JDS meet Lucy",
                  tz="America/Los_Angeles"),
    "atef": Office(key="atef", appstream_id="23467", owner="Atef Choudhury",
                  team="Domin8", group="Domin8 A Players",
                  tz="America/Denver"),
    "aya": Office(key="aya", appstream_id="22992", owner="Aya Alkhafaji",
                  team="Indelible", group="Indelible Lvl 1🔥",
                  tz="America/New_York"),
    # NEW A Players (Carlos 2026-11-19: "can you do that on my aplayers text
    # chain as well?"). It was "Box B2B", the first of his three groups, and
    # every send there failed: "Can not send message to a chat you are not a
    # member of!" -- Lucy 1 is no longer in that chat (Box went off 10/28).
    # Other approved group: ATT B2B Leaders.
    "carlos": Office(key="carlos", appstream_id="11580", owner="Carlos Hidalgo",
                  team="Alphalete", group="NEW A Players",
                  tz="America/Chicago"),
    "cody": Office(key="cody", appstream_id="21151", owner="Cody Cannon",
                  team="Aeon", group="ASC A-Players",
                  tz="America/Chicago"),
    # group is scoreboard-only for Lucy's other texts; Megan 11/15 turned these on here too
    "colten": Office(key="colten", appstream_id="14733", owner="Colten Wright",
                  team="South Shore", group="A Players",
                  tz="America/New_York"),
    "cyrus": Office(key="cyrus", appstream_id="22815", owner="Cyrus Wade",
                  team="Ambient", group="Ambient Managing Partners",
                  tz="America/Chicago"),
    # group is scoreboard-only for Lucy's other texts; Megan 11/15 turned these on here too
    "drew": Office(key="drew", appstream_id="22583", owner="Drew Tepper",
                  team="Precision", group="Precision Mastermind",
                  tz="America/New_York"),
    "emiliano": Office(key="emiliano", appstream_id="22001", owner="Emiliano Villagrana",
                  team="Vincere", group="A Players",
                  tz="America/Los_Angeles"),
    "eveliz": Office(key="eveliz", appstream_id="18404", owner="Eveliz Wright",
                  team="South Shore", group="A Players B2B",
                  tz="America/New_York"),
    "frank": Office(key="frank", appstream_id="23221", owner="Frank Matos",
                  team="Peak", group="PEAK A PLAYERS",
                  tz="America/New_York"),
    "hasani": Office(key="hasani", appstream_id="23701", owner="Hasani Lynch",
                  team="Covenant United", group="A PLAYERS",
                  tz="America/Chicago"),
    "haytham": Office(key="haytham", appstream_id="22524", owner="Haytham Nagi",
                  team="Horizon Edge", group="Haytham A-Players",
                  tz="America/Chicago"),
    "jacob": Office(key="jacob", appstream_id="23607", owner="Jacob Dover",
                  team="Rockstar", group="RSW A-players",
                  tz="America/Chicago"),
    # group is scoreboard-only for Lucy's other texts; Megan 11/15 turned these on here too
    "jairo15": Office(key="jairo15", appstream_id="21270", owner="Jairo Ruiz",
                  team="Profits", group="A PLAYERSSS",
                  tz="America/New_York"),
    "jamis": Office(key="jamis", appstream_id="19592", owner="Jamis Garay",
                  team="Midspire", group="Leaders chat",
                  tz="America/Chicago"),
    "jennifer-att": Office(key="jennifer-att", appstream_id="23132", owner="Jennifer Figueroa",
                  team="Figspire", group="FIGSPIRE A-TEAM",
                  tz="America/New_York"),
    "jose": Office(key="jose", appstream_id="22434", owner="Jose Velasquez",
                  team="Legacy Shore", group="A players chat!",
                  tz="America/Los_Angeles"),
    "joseph": Office(key="joseph", appstream_id="20788", owner="Joseph Delgado",
                  team="Golden View", group="A players",
                  tz="America/New_York"),
    "khalil": Office(key="khalil", appstream_id="11901", owner="Khalil Mansour",
                  team="Alphalete", group="Reporting",
                  tz="America/Chicago"),
    "luke": Office(key="luke", appstream_id="20958", owner="Luke Baldwin",
                  team="Takeoff", group="A Players B2B",
                  tz="America/Los_Angeles"),
    "maxamad": Office(key="maxamad", appstream_id="23066", owner="Maxamad Aden",
                  team="Maximal", group="Maximal Leaders ♾️",
                  tz="America/Chicago"),
    "natalia": Office(key="natalia", appstream_id="23431", owner="Natalia Gwarda",
                  team="Zora", group="Lucy Reporting",
                  tz="America/Los_Angeles"),
    "nigel": Office(key="nigel", appstream_id="20034", owner="Nigel Marshall",
                  team="VP Executives", group="Top Leaders",
                  tz="America/Denver"),
    "omar": Office(key="omar", appstream_id="24232", owner="Omar Mohamad",
                  team="Kalkan", group="KALKAN- A PLAYERS(REPORTING)",
                  tz="America/New_York"),
    "oren": Office(key="oren", appstream_id="22536", owner="Oren Shezaf",
                  team="Omnia", group="A-Players",
                  tz="America/Chicago"),
    "raf": Office(key="raf", appstream_id="11280", owner="Rafael Hidalgo",  # PILOT
                  team="Alphalete", group="Knocking Chat A-Players",
                  tz="America/Chicago"),
    "rashad": Office(key="rashad", appstream_id="23411", owner="Rashad Reed",
                  team="Elevate", group="A PLAYER CHAT",
                  tz="America/Chicago"),
    "ryan": Office(key="ryan", appstream_id="22820", owner="Ryan McSpadden",
                  team="Highline", group="Highline Partners 🔥",
                  tz="America/Chicago"),
    "sahil": Office(key="sahil", appstream_id="20490", owner="Sahil Multani",
                  team="M Coast", group="Mcoast-A Players",
                  tz="America/New_York"),
    "samuel": Office(key="samuel", appstream_id="23751", owner="Samuel Acay",
                  team="Dynasty", group="A Players Orlando",
                  tz="America/New_York"),
    "starr": Office(key="starr", appstream_id="17573", owner="Starr Rodenhurst",
                  team="Nova", group="A leaders knocking report",
                  tz="America/Los_Angeles"),
    "steve": Office(key="steve", appstream_id="23160", owner="Steve McElwee",
                  team="Luxe", group="Luxe A-Players",
                  tz="America/Chicago"),
    "trang": Office(key="trang", appstream_id="6564", owner="Trang Canavan",
                  team="Fresh Success", group="The Freshest",
                  tz="America/Chicago"),
    "tre": Office(key="tre", appstream_id="21182", owner="Tre Mitchell",
                  team="Mission III", group="LEADERS CHAT‼️",
                  tz="America/Chicago"),
    "valeria": Office(key="valeria", appstream_id="22850", owner="Valeria Tristan",
                  team="Altura", group="LEADERS⬆️",
                  tz="America/New_York"),
    "zaid": Office(key="zaid", appstream_id="19018", owner="Zaid Arabyat",
                  team="Aces", group="A Players",
                  tz="America/New_York"),
}

# LIVE from Mon 2026-11-16 (Megan 11/15: "All 34 offices", then Colten, Drew
# and Jairo too -- all 37). Only these text;
# an office added later stays "dry" until its key goes on this list.
LIVE = frozenset({
    "colten", "drew", "jairo15",
    "aiden", "atef", "aya", "carlos", "cody", "cyrus", "emiliano", "eveliz",
    "frank", "hasani", "haytham", "jacob", "jamis", "jennifer-att", "jose",
    "joseph", "khalil", "luke", "maxamad", "natalia", "nigel", "omar",
    "oren", "raf", "rashad", "ryan", "sahil", "samuel", "starr", "steve",
    "trang", "tre", "valeria", "zaid",
})
OFFICES = {k: (replace(o, mode="live") if k in LIVE and o.mode == "dry" else o)
           for k, o in OFFICES.items()}

# Retention Details row labels (matched by label, never by position).
L_FIRST = "Total First Interviews"
L_SECOND = "Total Second Interviews"
L_NS_SCHED = "Total New Starts Scheduled"
L_NS_SHOWED = "New Starts Showed Up"
LABELS = (L_FIRST, L_SECOND, L_NS_SCHED, L_NS_SHOWED)

# 4pm "Hired By": how many days (Sundays skipped) before the first day to look
# for the new start's 2nd round. Stops early once everyone is found.
HIRED_BY_LOOK_BACK = 14


def office(key: str) -> Office:
    k = (key or "").strip().lower()
    for o in OFFICES.values():
        if k in (o.key, o.appstream_id):
            return o
    raise KeyError("no office %r in recruiting_day_texts.config.OFFICES" % key)

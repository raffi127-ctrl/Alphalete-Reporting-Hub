"""One office's request to join Lucy Eco.

EVERYTHING HERE IS SOMETHING ONLY THEY KNOW. Their selling hours, how their
name is spelled in OwnerVille, whether they are on a Mac or a PC -- we were
asking for all of it over Slack and getting it in pieces. The form asks once,
and the answers arrive with the request instead of after it.

Deliberately NOT here: any password, and any channel id. The login never
leaves their laptop, and where alerts post is approved by a human afterwards.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, NamedTuple, Optional

PLATFORMS = ("mac", "windows")

# WHICH CAMPAIGN AN OFFICE RUNS DECIDES WHAT THE AGENT CAN EVEN READ.
#
# AT&T is the only campaign on SaraPlus (Megan 2026-09-15). Credit checks and
# sales come from SaraPlus, so they exist for AT&T offices and for nobody
# else -- an Energy or NDS or Box office has no SaraPlus account to sign into,
# and asking one for a login it does not have is how an install dies at step 6
# with the owner certain they typed it right.
#
# Knocks and dispositions come from OwnerVille, which every campaign uses. So
# a non-AT&T office gets a knocks board and nothing else, and is never asked
# for a SaraPlus login at all.
#
# The keys and OwnerVille ids match disposition_signup.CAMPAIGNS deliberately:
# the two intake forms must not disagree about what this company sells.
CAMPAIGNS = (
    ("att", "AT&T Fiber — Internet & Phones", True),
    ("nds", "NDS — Wireless & Phones", False),
    ("energy", "Energy Wells", False),
    ("b2b_att", "B2B — AT&T", True),
    ("b2b_box", "B2B — Box Energy", False),
)
CAMPAIGN_LABEL = {k: label for k, label, _sara in CAMPAIGNS}
_SARAPLUS = {k for k, _label, sara in CAMPAIGNS if sara}


def uses_saraplus(campaign_key: str) -> bool:
    """True when this campaign has a SaraPlus account behind it.

    Unknown campaigns say True. A new campaign nobody has told this module
    about should ask for the login and be TOLD it does not work, rather than
    silently never collecting credit checks that were supposed to arrive.
    """
    key = (campaign_key or "").strip().lower()
    return key not in {k for k, _l, sara in CAMPAIGNS if not sara}


def campaign_label(campaign_key: str) -> str:
    return CAMPAIGN_LABEL.get((campaign_key or "").strip().lower(),
                              campaign_key or "(not said)")
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DECLINED = "declined"
# A HUMAN HAS CLICKED APPROVE, and the work has not happened yet.
#
# The click cannot do the work itself: approving means resolving Slack
# channels, checking Lucy is in each one and writing the sign-off, and the
# form runs on Streamlit Cloud with a token that is a stranger to that
# workspace -- which is exactly how the sign-up ping failed. So the click
# leaves this, and the poster on Lucy 3 -- which already reads this tab every
# couple of minutes and already holds the right token -- does the real thing
# and reports back.
STATUS_APPROVE_REQUESTED = "approve_requested"

# The same picker the installer shows, so the answer means the same thing in
# both places and nobody has to translate it later.
KNOCKS_CHOICES = (
    (15, "Every 15 minutes"),
    (30, "Every 30 minutes"),
    (60, "Once an hour"),
    (0,  "Set times — 2:00 PM, 5:15 PM and 9:00 PM"),
    (-1, "No knocks board, thanks"),
)

# HOW OFFICES SAY IT, not how a computer does (Megan 2026-09-13). "Chicago"
# is the zone's name, not the thing anybody calls their own timezone -- an
# owner in Tyler, Texas does not live in Chicago and has to stop and work out
# which line is theirs.
#
# The stored VALUE is still the IANA zone, which is what handles daylight
# saving, so the label being the everyday "standard time" wording costs
# nothing: America/Chicago is CST in January and CDT in July either way.
TIMEZONES = (
    ("America/Chicago", "Central Standard Time (CST)"),
    ("America/New_York", "Eastern Standard Time (EST)"),
    ("America/Denver", "Mountain Standard Time (MST)"),
    ("America/Los_Angeles", "Pacific Standard Time (PST)"),
)

TZ_LABEL = dict(TIMEZONES)


def tz_label(zone: str) -> str:
    """The everyday name, falling back to the city if we ever add a zone here
    without a label -- an unlabelled option is better than a missing one."""
    return TZ_LABEL.get(zone) or str(zone).split("/")[-1].replace("_", " ")

_TIME = re.compile(r"^\d{1,2}:\d{2}$")

# EVERY QUARTER HOUR FROM 6 AM TO 11.45 PM. Wide enough for an office that
# starts early or runs late, and a list rather than a text box because
# "1:30pm", "1.30", "130" and "13:30" are all things a person types into a
# time field -- and the value has to come out as HH:MM or the field-hours
# check silently never matches.
TIME_CHOICES = tuple("%02d:%02d" % (h, m)
                     for h in range(6, 24) for m in (0, 15, 30, 45))


def time_label(hhmm: str) -> str:
    """'13:30' -> '1:30 PM'. Built by hand rather than strftime: %-I is
    glibc-only and every part of this has to run on Windows too."""
    try:
        h, m = [int(x) for x in str(hhmm).split(":")[:2]]
    except Exception:  # noqa: BLE001
        return str(hhmm)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


class IcdSignup(NamedTuple):
    owner: str
    office_label: str
    platform: str
    timezone: str
    day_start: str
    day_end: str
    saturday: bool
    sat_start: str
    sat_end: str
    ov_name: str
    knocks_cadence: int
    # A SUMMARY FOR HUMANS reading the sheet. The real answers are the two
    # JSON fields below -- an office can want alerts in the owners' room AND
    # the rep channel, and a knocks board in each at a DIFFERENT cadence, and
    # none of that fits in one line of text.
    wanted_channels: str
    contact: str
    # DEFAULTS TO AT&T, deliberately. Every office enrolled before campaigns
    # existed was on AT&T, and a record that arrives without one -- an older
    # row, a caller that has not been updated -- must not lose its credit
    # checks to a field that was added afterwards.
    campaign: str = "att"
    # ["Box Team 🔥"] -- iMessage GROUP CHAT NAMES, exactly as they appear in
    # Messages. Resolved by name on every send, so a renamed chat stops being
    # found and a near-miss finds nothing.
    text_groups_json: str = "[]"
    # ["C09AVM17PAR", "#palace-sales"] -- ids preferred, names accepted.
    alert_channels_json: str = "[]"
    # [{"channel": "...", "cadence_min": 30, "label": "Every 30 minutes"}]
    knocks_json: str = "[]"
    status: str = STATUS_PENDING
    submitted_at: str = ""
    office_key: str = ""
    note: str = ""

    def problems(self) -> List[str]:
        """What is wrong with this, in the words of the person who typed it."""
        out = []
        if not self.owner.strip() or len(self.owner.split()) < 2:
            out.append("Please give your first and last name.")
        if not self.contact.strip():
            out.append("Please leave an email or phone number so we can reach "
                       "you with your setup link.")
        if self.platform not in PLATFORMS:
            out.append("Please say whether this is a Mac or a Windows PC.")
        for label, value in (("start", self.day_start), ("end", self.day_end)):
            if not _TIME.match(value or ""):
                out.append("The weekday %s time should look like 13:30." % label)
        if self.saturday:
            for label, value in (("start", self.sat_start), ("end", self.sat_end)):
                if not _TIME.match(value or ""):
                    out.append("The Saturday %s time should look like 10:45."
                               % label)
        return out

    @property
    def text_groups(self) -> List:
        """Each entry is {"group", "cadence_min", "label"} -- or a bare string
        for an office that enrolled before the form asked how often."""
        return _loads_list(self.text_groups_json)

    @property
    def alert_channels(self) -> List[str]:
        return _loads_list(self.alert_channels_json)

    @property
    def knocks_destinations(self) -> List[Dict]:
        return _loads_list(self.knocks_json)

    def as_row(self) -> Dict:
        return {k: ("" if v is None else v) for k, v in self._asdict().items()}

    @classmethod
    def from_row(cls, row: Dict) -> "IcdSignup":
        def b(v):
            return str(v).strip().upper() in ("TRUE", "YES", "Y", "1")

        def i(v, default=30):
            try:
                return int(str(v).strip())
            except (TypeError, ValueError):
                return default

        return cls(
            owner=str(row.get("owner") or "").strip(),
            office_label=str(row.get("office_label") or "").strip(),
            platform=str(row.get("platform") or "mac").strip().lower(),
            timezone=str(row.get("timezone") or "America/Chicago").strip(),
            day_start=str(row.get("day_start") or "").strip(),
            day_end=str(row.get("day_end") or "").strip(),
            saturday=b(row.get("saturday")),
            sat_start=str(row.get("sat_start") or "").strip(),
            sat_end=str(row.get("sat_end") or "").strip(),
            ov_name=str(row.get("ov_name") or "").strip(),
            campaign=str(row.get("campaign") or "att").strip().lower(),
            knocks_cadence=i(row.get("knocks_cadence")),
            wanted_channels=str(row.get("wanted_channels") or "").strip(),
            contact=str(row.get("contact") or "").strip(),
            status=str(row.get("status") or STATUS_PENDING).strip().lower(),
            submitted_at=str(row.get("submitted_at") or "").strip(),
            office_key=str(row.get("office_key") or "").strip().lower(),
            note=str(row.get("note") or "").strip(),
            text_groups_json=str(row.get("text_groups_json") or "[]"),
            alert_channels_json=str(row.get("alert_channels_json") or "[]"),
            knocks_json=str(row.get("knocks_json") or "[]"),
        )


def _loads_list(text) -> List:
    """A list, whatever the sheet hands back. A cell can come through as an
    empty string, as None, or as text that is not JSON at all -- and a sign-up
    must not be lost to any of those."""
    import json
    try:
        out = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return out if isinstance(out, list) else []


def stamp() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# WHO THEY HAVE TO ADD TO THE GROUP CHAT. Lucy sends from the reporting
# account, so a chat she is not in cannot receive anything -- and unlike a
# Slack channel, nobody on our side can add her to somebody's group text.
def group_name(g) -> str:
    """The chat name, whether the entry is a dict or a bare string.

    Offices that enrolled before the form asked for a cadence stored just the
    name, and their rows are still on the tab.
    """
    if isinstance(g, dict):
        return str(g.get("group") or "").strip()
    return str(g or "").strip()


def group_cadence(g) -> int:
    """Minutes, or 0 meaning "nobody said" -- which the poster reads as
    "follow the board this is a copy of"."""
    if isinstance(g, dict):
        try:
            return int(g.get("cadence_min") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


LUCY_IMESSAGE = "alphaletereporting@gmail.com"

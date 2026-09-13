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
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DECLINED = "declined"

# The same picker the installer shows, so the answer means the same thing in
# both places and nobody has to translate it later.
KNOCKS_CHOICES = (
    (15, "Every 15 minutes"),
    (30, "Every 30 minutes"),
    (60, "Once an hour"),
    (0,  "Set times — 2:00 PM, 5:15 PM and 9:00 PM"),
    (-1, "No knocks board, thanks"),
)

TIMEZONES = (
    "America/Chicago", "America/New_York",
    "America/Denver", "America/Los_Angeles",
)

_TIME = re.compile(r"^\d{1,2}:\d{2}$")


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
    wanted_channels: str
    contact: str
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
            knocks_cadence=i(row.get("knocks_cadence")),
            wanted_channels=str(row.get("wanted_channels") or "").strip(),
            contact=str(row.get("contact") or "").strip(),
            status=str(row.get("status") or STATUS_PENDING).strip().lower(),
            submitted_at=str(row.get("submitted_at") or "").strip(),
            office_key=str(row.get("office_key") or "").strip().lower(),
            note=str(row.get("note") or "").strip(),
        )


def stamp() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")

"""The shape of one disposition-signup office, plus the rules the form and the
apply CLI both check.

Pure data (no network), mirroring tracker_onboarding.schema. One record here
becomes one row in gap_alerts.config.OFFICES — the module that already pulls
OwnerVille and sends the KNOCKS & DISPOSITIONS board — so every field maps
onto something that module already understands, or onto something added
alongside it (cadence_min, email_to, slack_channel).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

# Raf's question 4, exactly as he wrote it: "every 15 minutes, 30 minutes, or
# 1 hour". Nothing else is offered, and 15 is the floor for a reason — the
# board takes 1-4 minutes to build and the wrapper only fires on the quarter
# hour, so a 5-minute option would promise a cadence the pipe cannot hold.
#
# Every value MUST divide 60 and be a multiple of the 15-minute tick, or the
# per-office due-check in gap_alerts.run drifts across the hour.
CADENCE_CHOICES = [15, 30, 60]
CADENCE_LABELS = {15: "Every 15 minutes", 30: "Every 30 minutes",
                  60: "Once an hour"}
DEFAULT_CADENCE = 60

# Question 3. "Both" is not a third value — it is both boxes checked, so the
# record carries a LIST and the runner asks "is email in here?" rather than
# unpacking a mode string.
DELIVERY_CHOICES = ["imessage", "email"]
DELIVERY_LABELS = {"imessage": "iMessage text", "email": "Email"}

# The campaign the board is pulled for. The campaign is a STICKY session-global
# in OwnerVille that any other job on the box can move, so gap_alerts re-pins it
# on every pull — which means an enrollment has to say WHICH one. Owners do not
# know the id, so the form asks in their words and this maps it.
# invD2DClientId values: 3 = RES AT&T, 40 = RES-ENERGYWELL (both read off the
# live URL — see gap_alerts.config).
CAMPAIGNS = [
    {"id": "3", "key": "att", "label": "AT&T", "name": "AT&T (residential fiber)"},
    {"id": "40", "key": "energy", "label": "EnergyWell",
     "name": "Energy Wells"},
]
DEFAULT_CAMPAIGN = "att"


def campaign(key: str) -> "Optional[dict]":
    for c in CAMPAIGNS:
        if c["key"] == (key or "").strip().lower():
            return c
    return None


# The zones the job can actually serve. NOT a full tz list: the wrapper's hour
# gate (deploy/gap_alerts_5min.sh) exits before Python runs, and its envelope
# covers Eastern..Mountain field hours in Central terms. Pacific's 10pm would
# land at midnight Central — a different calendar day — so it is not offered
# rather than silently clipped. Four offices in this company are Eastern
# (project_cody_knocks_intraday), which is why this is asked at all.
TIMEZONES = [
    {"tz": "America/Chicago", "label": "Central (Texas)"},
    {"tz": "America/New_York", "label": "Eastern"},
    {"tz": "America/Denver", "label": "Mountain"},
    {"tz": "America/Phoenix", "label": "Arizona (no daylight saving)"},
]
DEFAULT_TZ = "America/Chicago"

# The org default field hours, in the office's OWN clock — what Raf's office
# runs and what every new office starts from unless it says otherwise.
DEFAULT_HOURS = {"day_start": "13:30", "day_end": "22:00",
                 "sat_start": "10:45", "sat_end": "18:30"}

_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def tz_label(tz: str) -> str:
    for z in TIMEZONES:
        if z["tz"] == tz:
            return z["label"]
    return tz or DEFAULT_TZ


@dataclass
class DispositionRecord:
    key: str                       # office key, e.g. "cody" (CLI/dict handle)
    owner: str = ""                # ICD name EXACTLY as OwnerVille spells it
    requested_by: str = ""         # what they go by (who filled the form)
    # Question 2, the OwnerVille account number — "in case we don't have them
    # already". Optional on purpose:
    # the name is what impersonation actually resolves through (via the ICD
    # alias sheet), and a blocking id field would stall every owner who does
    # not know theirs. It rides along so Megan can settle an ambiguous name
    # without a second message.
    ov_account: str = ""
    cadence_min: int = DEFAULT_CADENCE                  # question 4
    deliver: List[str] = field(default_factory=list)    # question 3
    email_to: List[str] = field(default_factory=list)
    imessage_group: str = ""       # the iMessage GROUP NAME, never a chat id:
                                   # a group's GUID is reminted on every
                                   # membership change and a stale one "sends"
                                   # into a dead thread without erroring.
    # Question 5. Recommended hourly regardless of the text/email cadence — a
    # channel of reps reading a leaderboard does not need it four times an hour.
    slack_hourly: bool = False
    slack_channel_id: str = ""
    slack_channel_name: str = ""
    campaign_key: str = DEFAULT_CAMPAIGN
    label: str = ""                # first name on the card; blank = no label
    # The office as OWNERVILLE spells it, when that differs from the owner's
    # own name — the same split office_onboarding carries as `knocks_office`.
    # Impersonation resolves through this, so a mismatch here is the difference
    # between a board and a failed tick.
    knocks_office: str = ""
    # When and where the field actually is. Absent = the org default (Central,
    # Mon-Fri 1:30pm-10pm, Sat 10:45am-6:30pm). Hours are in the OFFICE'S clock.
    tz: str = DEFAULT_TZ
    day_start: str = DEFAULT_HOURS["day_start"]
    day_end: str = DEFAULT_HOURS["day_end"]
    sat_start: str = DEFAULT_HOURS["sat_start"]
    sat_end: str = DEFAULT_HOURS["sat_end"]
    saturday: bool = True          # False = Mon-Fri only
    submitted_at: str = ""
    submitted_by: str = ""
    # An owner's own submission lands "pending" and is NEVER wired until Megan
    # confirms it in the form. Confirming flips it to "wired".
    status: str = "pending"
    # Set at confirm, not by the owner: impersonating an office needs Office
    # Access granted first, and a live row we cannot impersonate fails every
    # tick and opens incidents instead of posting. So a confirmed office is
    # wired but switched OFF until Megan ticks this.
    enabled: bool = False
    notes: str = ""                # anything the owner wants Megan to know

    def campaign(self) -> "Optional[dict]":
        return campaign(self.campaign_key)

    def campaign_id(self) -> str:
        c = self.campaign()
        return c["id"] if c else ""

    def display(self) -> str:
        return self.owner.strip() or self.key

    def cadence_label(self) -> str:
        return CADENCE_LABELS.get(int(self.cadence_min or 0),
                                  "every %s minutes" % self.cadence_min)

    def office_name(self) -> str:
        """What impersonation looks for: the OwnerVille office name if it
        differs, else the owner's own name."""
        return self.knocks_office.strip() or self.owner.strip()

    def hours_label(self) -> str:
        sat = ("Sat %s-%s" % (_ampm(self.sat_start), _ampm(self.sat_end))
               if self.saturday else "no Saturday")
        return "Mon-Fri %s-%s, %s (%s)" % (
            _ampm(self.day_start), _ampm(self.day_end), sat, tz_label(self.tz))

    def routes(self) -> "List[str]":
        """Human list of everywhere this office's board goes."""
        out = []
        if "imessage" in self.deliver:
            out.append("iMessage: %s" % (self.imessage_group or "?"))
        if "email" in self.deliver:
            out.append("Email: %s" % (", ".join(self.email_to) or "?"))
        if self.slack_hourly:
            out.append("Slack (hourly): %s"
                       % (self.slack_channel_name or self.slack_channel_id or "?"))
        return out

    def to_json(self) -> dict:
        d = asdict(self)
        d["_derived"] = {"display": self.display(),
                         "cadence": self.cadence_label(),
                         "hours": self.hours_label(),
                         "routes": self.routes()}
        return d


def _ampm(hhmm: str) -> str:
    """'13:30' -> '1:30 PM'. No %-I: Windows has no such format code."""
    try:
        h, m = [int(x) for x in str(hhmm).split(":")]
    except Exception:                                # noqa: BLE001
        return str(hhmm)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def slug_from(name: str) -> str:
    """First word, lowercased, a-z0-9 only — the conventional office key."""
    first = (name or "").strip().split()[0] if (name or "").strip() else ""
    return re.sub(r"[^a-z0-9]", "", first.lower())


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def parse_emails(raw: str) -> "List[str]":
    """'a@b.com, c@d.com' (or one per line) -> ['a@b.com', 'c@d.com']."""
    parts = re.split(r"[,;\s]+", raw or "")
    return [p.strip() for p in parts if p.strip()]


def bad_emails(addrs: "List[str]") -> "List[str]":
    return [a for a in addrs if not _EMAIL_RE.match(a)]


def existing_office_keys() -> "List[str]":
    """Office keys gap_alerts already sends for — hardcoded rows AND rows an
    earlier enrollment materialized. Best-effort: a failed import contributes
    nothing rather than blocking a submission."""
    try:
        from automations.gap_alerts import config as C
        return [o.get("key", "") for o in C.OFFICES if o.get("key")]
    except Exception:                                # noqa: BLE001
        return []


def _common(rec: DispositionRecord, problems: "List[str]") -> None:
    """Checks that hold for BOTH the owner's request and Megan's confirm."""
    if int(rec.cadence_min or 0) not in CADENCE_CHOICES:
        problems.append("Pick how often you want it: every 15 minutes, "
                        "30 minutes, or once an hour.")
    routes = [d for d in rec.deliver if d in DELIVERY_CHOICES]
    if not routes and not rec.slack_hourly:
        problems.append("Pick at least one way to get it — email, iMessage, "
                        "or your team's Slack channel.")
    if "imessage" in routes and not rec.imessage_group.strip():
        problems.append("For iMessage, tell us the name of the group chat to "
                        "text (exactly as it shows on your phone).")
    if "email" in routes:
        if not rec.email_to:
            problems.append("For email, add at least one email address.")
        else:
            bad = bad_emails(rec.email_to)
            if bad:
                problems.append("That doesn't look like an email address: "
                                + ", ".join(bad))
    if rec.slack_hourly and not (rec.slack_channel_name.strip()
                                 or rec.slack_channel_id.strip()):
        problems.append("For the Slack post, tell us the channel name.")
    if not rec.campaign():
        problems.append("Pick which campaign these dispositions are for.")
    if rec.tz not in [z["tz"] for z in TIMEZONES]:
        problems.append("Pick the time zone your office is in.")
    for lo, hi, what in ((rec.day_start, rec.day_end, "Monday-Friday"),
                         (rec.sat_start, rec.sat_end, "Saturday")):
        if not (_HHMM_RE.match(str(lo)) and _HHMM_RE.match(str(hi))):
            problems.append("Those %s hours don't look like times." % what)
        elif lo >= hi:
            # String compare is safe on zero-padded HH:MM and says the thing
            # that matters: an end before its start is an empty day, and an
            # empty day is a report that silently never sends.
            problems.append("Your %s end time has to be after the start time."
                            % what)


def validate_request(rec: DispositionRecord, *,
                     existing_keys: "Optional[List[str]]" = None) -> "List[str]":
    """The lighter check for an OWNER's submission. The Slack channel id and
    the OwnerVille account number may still be missing — Megan fills those at
    confirm — but identity, cadence and at least one delivery route are not
    optional, or there is nothing to wire."""
    existing_keys = existing_keys or []
    problems: List[str] = []
    if not rec.requested_by.strip():
        problems.append("Please enter your name.")
    if not rec.owner.strip():
        problems.append("Please enter your ICD name as it appears in "
                        "OwnerVille.")
    if not rec.key.strip():
        problems.append("Couldn't make an office id from that name — please "
                        "use your real OwnerVille name.")
    elif rec.key in existing_keys:
        problems.append("An office under that name already gets the daily "
                        "dispositions. If something about it needs to change "
                        "— a different time, a different chat — message Megan "
                        "Hidalgo instead of signing up twice.")
    _common(rec, problems)
    return problems


def validate(rec: DispositionRecord, *,
             existing_keys: "Optional[List[str]]" = None,
             existing_groups: "Optional[Dict[str, str]]" = None
             ) -> "List[str]":
    """[] when safe to wire, else problems. Stricter than the request check:
    the key has to be a legal dict handle, and one iMessage group must not be
    claimed by two offices — that is the mistake that texts one owner's board
    into another owner's room."""
    existing_keys = existing_keys or []
    existing_groups = existing_groups or {}
    problems: List[str] = []

    if not rec.key.strip():
        problems.append("Office key is empty.")
    elif not re.match(r"^[a-z0-9_]+$", rec.key):
        problems.append("Office key %r must be lowercase letters/digits/"
                        "underscore only." % rec.key)
    if rec.key in existing_keys:
        problems.append("Office key %r already gets dispositions — pick a "
                        "unique handle." % rec.key)
    if not rec.owner.strip():
        problems.append("ICD name (as OwnerVille spells it) is empty — "
                        "impersonation resolves through that name.")
    _common(rec, problems)
    return problems


def warnings(rec: DispositionRecord, *,
             existing_groups: "Optional[Dict[str, str]]" = None) -> "List[str]":
    """Things worth Megan's eye at confirm time that must NOT block the wire.

    A shared iMessage room is the main one, and it is a warning rather than an
    error because sharing one is sometimes the point: Calvin and Jay both text
    ENERGY WELLS DOMINATION on purpose. It is also how one owner's numbers end
    up in another owner's room by accident, so it gets said out loud.
    """
    existing_groups = existing_groups or {}
    out: List[str] = []
    grp = rec.imessage_group.strip()
    if "imessage" in rec.deliver and grp:
        owner_of = existing_groups.get(grp.lower())
        if owner_of and owner_of != rec.key:
            out.append("iMessage group %r already receives %r's board — both "
                       "offices' numbers will land in that one room. Fine if "
                       "that's deliberate (Calvin + Jay share one); otherwise "
                       "use a different chat." % (grp, owner_of))
    if not rec.enabled:
        out.append("This office is wired but switched OFF until 'Office Access "
                   "granted' is ticked — impersonation fails every tick "
                   "without it, and a failing office opens incidents instead "
                   "of posting.")
    return out

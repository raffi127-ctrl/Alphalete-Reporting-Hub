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

# A destination can also run on FIXED TIMES instead of an interval — Cody
# Cannon's setup (Megan 2026-09-01), the same three moments knocks_intraday
# already posts: "2pm to track first knocks / 5:15 to track knocks into the
# start of money lap / 9pm to track eod knocks" (Cody's DM, 2026-08-24).
#
# cadence_min == SLOT_CADENCE means "read `slots`, ignore the interval".
SLOT_CADENCE = 0


def _cody_slots():
    """[(hh:mm, label)] — READ FROM knocks_intraday so the two cannot drift.
    That module is the one that already posts these boards; if Cody ever moves
    his money lap, this follows. Falls back to the known three if the import
    fails (a Cloud deploy missing the package should not break the form)."""
    try:
        from automations.knocks_intraday.schedule import SLOTS
        return [("%02d:%02d" % (s.hour, s.minute), s.label) for s in SLOTS]
    except Exception:                                # noqa: BLE001
        return [("14:00", "First Knocks"), ("17:15", "Money Lap"),
                ("21:00", "End of Day")]


CODY_SLOTS = [t for t, _ in _cody_slots()]
CODY_SLOT_LABELS = dict(_cody_slots())


def slots_label(slots: "Optional[List[str]]" = None) -> str:
    """'1st knock 2:00 PM · money lap 5:15 PM · last knock 9:00 PM'."""
    slots = slots or CODY_SLOTS
    # Title Case, the way knocks_intraday already titles these moments on the
    # board itself ("First Knocks" / "Money Lap" / "End of Day"). They are the
    # names of the moments, not a description of them.
    return " · ".join("%s %s" % (CODY_SLOT_LABELS.get(t, t), _ampm(t))
                      for t in slots)


# What the "How often?" picker offers. SLOT_CADENCE last: an interval is what
# most offices want, and the fixed-times option is the considered choice.
CADENCE_PICKER = CADENCE_CHOICES + [SLOT_CADENCE]


def cadence_picker_label(minutes: int) -> str:
    if int(minutes) == SLOT_CADENCE:
        return "Set times — %s" % slots_label()
    return CADENCE_LABELS.get(int(minutes), "every %s minutes" % minutes)

# Question 3. "Both" is not a third value — it is both boxes checked, so the
# record carries a LIST and the runner asks "is email in here?" rather than
# unpacking a mode string.
# An office can have MANY places it wants the board, each on its own clock
# (Megan 2026-09-01) — the owners' room every 15 minutes, the rep channel once
# an hour. So the record carries a LIST OF DESTINATIONS, not a set of flags
# plus one shared cadence.
#
# One destination = {kind, name, channel_id, emails, cadence_min}:
#   kind        "imessage" | "slack" | "email"
#   name        the iMessage group's name / "#channel" / "" for email
#   channel_id  Slack only ("C..."), may be blank until Megan confirms
#   emails      email only
#   cadence_min this destination's own 15 / 30 / 60
DELIVERY_CHOICES = ["imessage", "slack", "email"]
DELIVERY_LABELS = {"imessage": "iMessage text", "slack": "Slack channel",
                   "email": "Email"}

# WHAT THE FORM OFFERS — a strict subset of what the RUNNER can deliver.
# Megan 2026-09-02: "take the option they have of getting an imessage out of
# this form. it's only slack and email so my number can also be removed."
#
# `imessage` stays in DELIVERY_CHOICES above because it is not dead: every
# hardcoded gap_alerts office texts (Raf -> Alphalete Partners, Calvin and Jay
# -> ENERGY WELLS DOMINATION), the runner's send loop still has that leg, and a
# sign-up taken before today may still carry one — the confirm view has to be
# able to render and keep those. What changed is only what an OWNER can create:
# nothing filled in on the form can produce a texting route, which is why the
# form no longer asks for a group-chat name and no longer prints Megan's phone
# number.
FORM_DELIVERY_CHOICES = ["slack", "email"]


def destination(kind: str, *, name: str = "", channel_id: str = "",
                emails=None, cadence_min: int = DEFAULT_CADENCE,
                slots=None) -> dict:
    d = {"kind": kind, "name": (name or "").strip(),
         "channel_id": (channel_id or "").strip(),
         "emails": list(emails or []), "cadence_min": int(cadence_min)}
    if int(cadence_min) == SLOT_CADENCE:
        d["slots"] = list(slots or CODY_SLOTS)
    return d


def dest_label(d: dict) -> str:
    """'iMessage text — Alphalete Partners, every 15 minutes'."""
    kind = d.get("kind", "")
    if kind == "email":
        where = ", ".join(d.get("emails") or []) or "?"
    else:
        where = d.get("name") or d.get("channel_id") or "?"
    if int(d.get("cadence_min") or 0) == SLOT_CADENCE:
        when = "at " + slots_label(d.get("slots"))
    else:
        when = CADENCE_LABELS.get(int(d.get("cadence_min") or 0), "?").lower()
    return "%s — %s, %s" % (DELIVERY_LABELS.get(kind, kind), where, when)

# The campaign the board is pulled for. The campaign is a STICKY session-global
# in OwnerVille that any other job on the box can move, so gap_alerts re-pins it
# on every pull — which means an enrollment has to say WHICH one. Owners do not
# know the id, so the form asks in their words and this maps it.
# invD2DClientId values: 3 = RES AT&T, 40 = RES-ENERGYWELL (both read off the
# live URL — see gap_alerts.config).
# EVERY campaign, because NDS and B2B access is being extended to us
# (Megan 2026-09-01) — an office that runs B2B should not have to be told this
# form is not for them.
#
# The ids are the ones this repo has PROVEN live, not guesses:
#   3   RES AT&T          — the id gap_alerts pins for Raf's office
#   40  RES-ENERGYWELL    — read off the live URL, 2026-08-29
#   2   B2B AT&T SBS      — b2b_dispositions --probe-campaigns, 2026-07-29
#   16  B2B-BOX-Energy    — same probe; car_rides proved it 2026-07-15
# The B2B two are spelled the way the OwnerVille dropdown spells them on
# Carlos's screen, so an owner is picking the words they already see.
#
# NDS PINS 3 (RES AT&T), the same id as fiber, and it used to carry no id at
# all. Both halves of that were wrong (fixed 2026-09-02):
#
#   * "NDS has no campaign" conflated the BUSINESS with the campaign. Megan read
#     Isaiah Revelle's own OwnerVille picker on 2026-08-25: it offers BASE
#     Energy / RES AT&T / RES-ENERGYWELL, and his reps knock RES AT&T like
#     everyone else. knocks_pull.campaign_for_office carries the same finding
#     and the same default — "the campaign all current knocks offices (fiber
#     D2D and NDS wireless) knock under".
#   * An EMPTY id does not mean "this office's own campaign". The campaign is a
#     sticky session-global, so no pin means "whatever the office before it in
#     the batch left it on" — the exact silent-drift failure that returned
#     Calvin zero rows for days and blanked Chan's comparison line.
#
# What an NDS office actually gets is a smaller board, not no board: NDS reps
# clock in and knock without dispositioning, so p=89 can come back empty. When
# it does, knocks_pull builds the rows from the Time Tracker instead and the
# renderer draws the Time Gaps board alone (render.SHAPE_GAPS_ONLY). That is
# the half gap_alerts exists for anyway, so the enrollment is real either way.
CAMPAIGNS = [
    # --- D2D ---------------------------------------------------------------
    {"id": "3", "key": "att", "family": "D2D", "label": "AT&T",
     "name": "AT&T Fiber (Internet & Phones)", "live": True},
    {"id": "40", "key": "energy", "family": "D2D", "label": "EnergyWell",
     "name": "Energy Wells", "live": True},
    # LIVE since 2026-09-02, pinned to RES AT&T like every other knocks office
    # (see the note above). An NDS office whose reps don't disposition gets the
    # Time Gaps half of the board, which is the half this report is named for.
    {"id": "3", "key": "nds", "family": "D2D", "label": "NDS",
     # "Wireless" alone: on NDS the phones ARE the wireless (Megan 2026-09-01).
     # office_onboarding spells it "Wireless & Phones"; that reads as two
     # products to an owner picking one.
     "name": "NDS Wireless", "live": True,
     # Said on the form, at the moment they pick it: an NDS board can be gaps
     # only, and an owner expecting a disposition breakdown should hear that
     # from us before the first one lands, not after.
     "note": "Most NDS offices knock without dispositioning — when that's the "
             "case your board shows who's out and who's gone quiet (the Time "
             "Gaps half), and fills in the disposition columns automatically "
             "if your reps start using them."},
    # --- B2B ---------------------------------------------------------------
    # NOT "B2B AT&T SBS" / "B2B-BOX-Energy" — those are OwnerVille's own
    # dropdown strings, and "SBS" means nothing to the person filling this in
    # (Megan 2026-09-01: "idk what SBS is"). The family prefix already says
    # B2B, so the name does not repeat it either. `label` keeps the short tag
    # that goes on the board itself.
    {"id": "2", "key": "b2b_att", "family": "B2B", "label": "B2B AT&T",
     "name": "AT&T", "live": True},
    {"id": "16", "key": "b2b_box", "family": "B2B", "label": "B2B Box",
     "name": "Box Energy", "live": True},
]

# Grouped the way an owner thinks about it, and the same four families
# office_onboarding.CAMPAIGNS uses — the two intake forms should not disagree
# about what this company sells.
FAMILIES = ["D2D", "B2B"]

# WHICH BOX RUNS AN OFFICE, decided by its campaign — not a preference, a
# constraint. An office can only be impersonated from the machine whose
# OwnerVille login has access to it: Lucy 1 is Raf's (D2D), Lucy 2 is Carlos's
# (B2B). Both boxes have iMessage, each under its own Apple ID, so the texts
# follow the pull. Same split office_onboarding.FAMILY_DEFAULT_MACHINE uses.
FAMILY_MACHINE = {"D2D": "Lucy 1", "B2B": "Lucy 2"}
DEFAULT_MACHINE = "Lucy 1"


def campaign_machine(key: str) -> str:
    c = campaign(key) or {}
    return FAMILY_MACHINE.get(c.get("family", ""), DEFAULT_MACHINE)


def campaigns_in(family: str) -> "List[dict]":
    return [c for c in CAMPAIGNS if c["family"] == family]


def campaign_live(key: str) -> bool:
    """False = we cannot pull dispositions for it YET. The sign-up is still
    taken and still lands in front of Megan; it just goes on the waiting list
    instead of being wired, and apply refuses to materialize it."""
    c = campaign(key)
    return bool(c and c.get("live"))


def campaign_choice_label(key: str) -> str:
    c = campaign(key) or {}
    return "%s — %s%s" % (c.get("family", "?"), c.get("name", key),
                          "" if c.get("live") else "  (coming soon)")


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
    # Every place this office wants the board, each with its own cadence.
    # iMessage destinations carry the group's NAME, never a chat id: a group's
    # GUID is reminted on every membership change and a stale one "sends" into
    # a dead thread without erroring.
    destinations: List[Dict] = field(default_factory=list)
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

    def of_kind(self, kind: str) -> "List[Dict]":
        return [d for d in self.destinations if d.get("kind") == kind]

    def cadence_label(self) -> str:
        """The cadences in play. Destinations each carry their own now, so this
        describes the setup rather than being the setting."""
        mins = sorted({int(d.get("cadence_min") or 0)
                       for d in self.destinations})
        if not mins:
            return "no cadence set"
        if mins == [SLOT_CADENCE]:
            return "at set times"
        if len(mins) == 1:
            return CADENCE_LABELS.get(mins[0], "every %d minutes" % mins[0])
        return " / ".join(("at set times" if m == SLOT_CADENCE
                           else CADENCE_LABELS.get(m, "every %d min" % m).lower())
                          for m in mins)

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
        return [dest_label(d) for d in self.destinations]

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
    if not rec.destinations:
        problems.append("Pick at least one place to send it — an iMessage "
                        "chat, a Slack channel, or email.")
    seen = set()
    for i, d in enumerate(rec.destinations):
        kind = d.get("kind", "")
        tag = " (#%d)" % (i + 1)
        if kind not in DELIVERY_CHOICES:
            problems.append("Unknown destination type %r." % kind)
            continue
        cad = int(d.get("cadence_min") or 0)
        if cad == SLOT_CADENCE:
            slots = d.get("slots") or []
            if not slots:
                problems.append("Pick the times for %s%s."
                                % (DELIVERY_LABELS[kind], tag))
            for t in slots:
                # The job only wakes on the quarter hour, so a 5:20 slot would
                # simply never fire — refuse it rather than promise it.
                if not _HHMM_RE.match(str(t)) or int(str(t)[3:]) % 15:
                    problems.append("%s isn't a time we can send at%s — it has "
                                    "to land on the quarter hour."
                                    % (t, tag))
        elif cad not in CADENCE_CHOICES:
            problems.append("Pick how often for %s%s: every 15 minutes, "
                            "30 minutes, once an hour, or set times."
                            % (DELIVERY_LABELS[kind], tag))
        if kind == "imessage" and not (d.get("name") or "").strip():
            problems.append("Name the group chat to text%s — exactly as it "
                            "shows on your phone." % tag)
        elif kind == "slack" and not ((d.get("name") or "").strip()
                                      or (d.get("channel_id") or "").strip()):
            problems.append("Name the Slack channel to post in%s." % tag)
        elif kind == "email":
            addrs = d.get("emails") or []
            if not addrs:
                problems.append("Add at least one email address%s." % tag)
            else:
                bad = bad_emails(addrs)
                if bad:
                    problems.append("That doesn't look like an email address: "
                                    + ", ".join(bad))
        # The same room listed twice is two identical boards arriving together.
        where = (kind, ((d.get("name") or d.get("channel_id") or "").strip()
                        .lstrip("#").lower()
                        or ",".join(sorted(a.lower()
                                           for a in (d.get("emails") or [])))))
        if where[1] and where in seen:
            problems.append("%s %s is listed twice — it would send the same "
                            "board there twice."
                            % (DELIVERY_LABELS[kind], where[1]))
        seen.add(where)
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
    for d in rec.of_kind("imessage"):
        grp = (d.get("name") or "").strip()
        owner_of = existing_groups.get(grp.lower()) if grp else None
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
    out += b2b_blockers(rec)
    return out


# The B2B half of this run went from "wired but not running" to "built, not yet
# installed" on 2026-09-02. What is left is said here, at the moment Megan
# decides, rather than discovered as silence a week later.
#
# RESOLVED the same day, kept in the record because both were live hazards:
#  * the B2B Disposition grid is MAPPED. Both campaigns were probed live
#    (invD2DClientId 2 and 16) and they are two different vocabularies, not one
#    — knocks_pull carries a column set, a talk-to rule and a board shape for
#    each. Before that a B2B grid satisfied the tolerant wireless scrape and
#    rendered a plausible board with 0 under every disposition.
#  * the LaunchAgent exists (deploy/com.alphalete.gap-alerts-b2b.plist).
B2B_BLOCKERS = [
    "The Lucy 2 agent is BUILT but not installed yet. Until someone runs "
    "`lucy rerun install_gap_alerts_b2b_agent --machine \"Lucy 2\"`, nothing "
    "on that box ticks — a B2B office wired today would sit switched on and "
    "send nothing, silently.",
    "Not every B2B office serves its campaign's grid. Carlos Hidalgo (11580) "
    "pinned to Box returns the AT&T-shaped table holding AT&T's reps, while "
    "Roshan Amin Ahmad (19833) returns the real Box grid — so a campaign is "
    "only as good as the office it is pulled from. `assert_campaign_grid` "
    "refuses that mismatch rather than posting a Box-titled board of AT&T "
    "numbers, but it means an enrolling office still has to be checked against "
    "the campaign it claims.",
    "iMessage cannot send from a LaunchAgent on Lucy 2. macOS granted "
    "\"control Messages\" there to the poller's executable identity "
    "(.venv/bin/python), not to a /bin/bash wrapper — which is why "
    "b2b_dispositions hands its sends to the poller through a manifest. "
    "gap_alerts texts inline, so `config.can_text()` is False on that box and "
    "the send loop skips texting routes out loud. Slack and email are "
    "unaffected; the form is Slack + email only, so this can only bite a row "
    "added by hand.",
]


def b2b_blockers(rec: "DispositionRecord") -> "List[str]":
    """What is still in the way of a B2B office actually posting, [] for D2D.
    Warnings, never errors: confirming a B2B office stores a correct setup, and
    it goes live the day the runner does."""
    camp = rec.campaign() or {}
    if camp.get("family") != "B2B":
        return []
    out = list(B2B_BLOCKERS[:2])
    if rec.of_kind("imessage"):
        out.append(B2B_BLOCKERS[2])
    return ["B2B not running yet — " + b for b in out]

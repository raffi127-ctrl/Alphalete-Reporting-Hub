"""What an office answers on the LucyECO Onboarding enrolment, and where it goes.

WHY THIS EXISTS. The onboarding board and the Apex fill both read per-office
answers off the `Office Settings` tab -- and on 2026-11-19 two of the columns
they read, `Blue Ink` and `Rate of Pay`, DID NOT EXIST on that tab. They were
written into the code and never into the sheet, so `rate_of_pay()` returned
None for every office and every non-Raf person was being held back on a
question nobody had been given a way to answer.

Megan, 2026-11-19: "this should be on the enrollment form so we can have them
enter in what is correct for them" and "sterling would also be on the
onboarding enrollment form".

ONE TAB, BY COLUMN NAME. `Office Settings` already carries State and City for
Sterling's E-Invite ("Location of Job/Position") and is read by header
everywhere, so new answers are new columns rather than a second store that
would immediately disagree with the first. An office's row is found by its
key, never by position: that tab gained an `Owner` column from another session
on 2026-11-06 and a positional read silently returned the wrong cell.
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional

from automations.icd_onboarding import office_steps as OS

# Sterling's own State dropdown, by its visible names -- reused rather than
# retyped, so the form can only offer a value Sterling will accept.
from automations.office_admin.config import US_STATES          # noqa: E402

TAB = OS.TAB                       # "Office Settings"
COL_OFFICE = OS.COL_OFFICE         # "Office"

# STERLING. Already on the tab, because the E-Invite form needs them on every
# invite (Megan 2026-11-03: "we will need to ask the city and state of the
# owner"). On this form so an office answers them once, with everything else.
COL_STATE = "State"
COL_CITY = "City"

COL_UPDATED_BY = "Updated By"
COL_UPDATED_AT = "Updated At"


class Question(NamedTuple):
    """One thing an office is asked."""
    field: str          # what the code calls it
    column: str         # the Office Settings column that holds the answer
    label: str          # what the owner reads
    help: str
    choices: tuple = ()  # empty = free text
    default: str = ""
    required: bool = False
    # "text" | "channel". A channel is not free text: a NAME typed where an id
    # belongs is accepted by every box and then fails hours later when Lucy
    # tries to post (Joseph Logan, 2026-09-11), so it gets the Channel ID box
    # that refuses one on the spot.
    kind: str = "text"


# WHAT STERLING NEEDS. Where the job is, in Sterling's own words.
STERLING: List[Question] = [
    Question("state", COL_STATE, "What state is your office in?",
             "Sterling puts this on every background check invite.",
             US_STATES, "", True),
    Question("city", COL_CITY, "What city is your office in?",
             "Sterling puts this on every background check invite.",
             (), "", True),
]

# WHAT TIME IT IS WHERE THE OFFICE IS (Megan, 2026-11-24: "we'll need to make
# sure that we're reading the calendar in the right time zone").
#
# EVERY START TIME WAS READ AS CENTRAL. It was one hard-coded line, true since
# August because the only tab was Raf's and Lucy 3 is Central too -- so an
# office an hour or three away got its Digi Doc bundle an hour or three wrong,
# and EARLY on the west coast, which is a contract landing before anybody is in
# the room.
#
# A ZONE, NOT AN OFFSET. An offset is wrong twice a year, and the fortnight
# either side of a clock change is exactly when a 30-minute lead quietly
# becomes a 90-minute one. The words are the owner's ("Pacific"), the stored
# value is the zone name, because that is what handles the change itself.
#
# NOT GUESSED FROM THE STATE, even though the office has already given one.
# Six states are split across two zones, and a guessed zone is
# indistinguishable from a right one until a send lands an hour out. Asked,
# with the office's own state as the hint next to it.
COL_TIME_ZONE = "Time Zone"

_ZONES = (
    ("Eastern", "America/New_York"),
    ("Central", "America/Chicago"),
    ("Mountain", "America/Denver"),
    ("Mountain — Arizona (no daylight saving)", "America/Phoenix"),
    ("Pacific", "America/Los_Angeles"),
    ("Alaska", "America/Anchorage"),
    ("Hawaii", "Pacific/Honolulu"),
)
TIME_ZONE_CHOICES = tuple(label for label, _zone in _ZONES)
ZONE_BY_LABEL = {label: zone for label, zone in _ZONES}
LABEL_BY_ZONE = {zone: label for label, zone in _ZONES}

CLOCK: List[Question] = [
    Question("time_zone", COL_TIME_ZONE, "What time zone is your office in?",
             "Your new starts' documents go 30 minutes before each person's "
             "own start time, so this is read off your clock and not ours. "
             "Arizona has its own entry because it does not change twice a "
             "year.",
             TIME_ZONE_CHOICES, "Central", True),
]

# WHAT THE ONBOARDING BOARD NEEDS. Both columns are read today and neither
# existed on the tab until this form created it.
BOARD: List[Question] = [
    Question("blue_ink", OS.COL_BLUEINK, "Do you have a Blue Ink account?",
             "Without one we cannot read a signed packet, so Blue Ink and "
             "Apex are skipped for your office rather than sitting unticked "
             "for ever.",
             ("Yes", "No"), "Yes", True),
    Question("rate", OS.COL_RATE, "What do you pay per hour?",
             "Apex will not save a record without it. Yours, not ours -- "
             "$10.00 is Alphalete's.",
             (), "", True),
]

# WHAT APEX ASKS. The two state fields are separate from the six below because
# they are the ones that must be answered: see OS.APEX_MUST_ASK.
PAY_STATES: List[Question] = [
    Question("pay_state", OS.APEX_COLUMNS["pay_state"],
             "What state do your reps WORK in?",
             "Apex calls this 'State Working In'. Usually the same as your "
             "office's state.", US_STATES, "", True),
    Question("tax_state", OS.APEX_COLUMNS["tax_state"],
             "What state are your reps TAXED in?",
             "Apex calls this 'State to be taxed in'. This one lands on a tax "
             "record, so it is asked rather than assumed.", US_STATES, "", True),
]

# THE ONE THING ON THEIR MACHINE WE CANNOT SET FOR THEM (Megan, 2026-11-22:
# "the enrollment is also where we would add this").
#
# Raf's ask: the office's ApplicantStream calendar has to be on the LIST view
# with Show Notes ticked, not the card view -- the card view does not carry
# what the training-calendar reads need. It is a setting in their own
# ApplicantStream, on their own screen, so nothing here can set it; the only
# way a new office starts right is to be asked while they are setting up.
#
# ApplicantStream were asked on 2026-11-18 to make it the default for
# everyone. Until they do, this is the backstop -- and it stays useful after,
# because it confirms rather than assumes.
COL_CALENDAR_VIEW = "Calendar List View"

CALENDAR: List[Question] = [
    Question("calendar_view", COL_CALENDAR_VIEW,
             "Is your ApplicantStream calendar set to List view with Show "
             "Notes ticked?",
             "Open the calendar in ApplicantStream, switch it from Card to "
             "List, and tick Show Notes. The card view leaves out what Lucy "
             "reads, so new starts go missing from the board.",
             ("Yes", "Not yet"), "", True),
]

# WHAT THEIR ONBOARDING BUNDLE IS CALLED IN BLUE INK (Megan, 2026-11-22:
# "every ICD will have their own blueink account login. that isn't something
# we have to build. we just have to make sure they have their document bundle
# labeled correctly so lucy knows which to send out").
#
# The account and the key are the office's own setup on their own machine.
# The live send finds the template BY NAME on their Envelope Templates page,
# so the name is the only thing that has to be agreed -- and it was a
# constant in our code, Alphalete's.
#
# THE STANDARD LABEL IS THE DEFAULT and the answer for almost everyone:
# telling every ICD to call theirs the same thing is less to get wrong than
# asking each what theirs is called. This exists for the office whose bundle
# already has another name, so they are not made to rename a template their
# documents already hang off.
COL_BUNDLE = "Blue Ink Bundle"

# GO AND LOOK, rather than accept a name we filled in for you (Megan,
# 2026-11-22: "we need to say to go into their blueink and look at the name
# of their doc bundle to map it out").
#
# NO DEFAULT, deliberately. Pre-filling Alphalete's "UNIVERSAL I9 MASTER
# FORM" is the worst option available: it is a real name, so the box looks
# answered, and it does not exist in anybody else's account -- so the first
# send of a new office's first week finds no such template and goes nowhere.
# A blank box is a question somebody answers; a plausible wrong answer is
# one nobody checks.
BLUE_INK_BUNDLE: List[Question] = [
    Question("bundle", COL_BUNDLE,
             "What is your onboarding document bundle called in Blue Ink?",
             "Open Blue Ink, go to Templates, and copy the name of the "
             "bundle your new starts sign — exactly as it reads there, "
             "including capitals. Lucy finds it by that name on your own "
             "account, and sends nothing at all if she cannot find it.",
             (), "", False),
]

# WHERE THEIR OBCL UPDATE GOES, and whether it is Slack or a text group
# (Megan, 2026-11-22: "the channel that these are to go in will need to be
# asked on the enrollment form" and "they also need an option here to send
# to a text group").
#
# BOTH DESTINATIONS WERE ALPHALETE'S, hardcoded: the picture goes to the
# iMessage group "ORIENTATION CREW - Real" (obcl_ov_sweep.snapshot.GROUP),
# and Raf's outstanding ask is to put it in a Slack thread instead. Neither
# was ever a per-office answer, so there was nothing an office could say.
#
# A CHOICE, NOT TWO BOXES TO FILL IN. An office answers where it wants the
# update and then the one detail that goes with it; asking for a channel AND
# a group leaves two answers where only one is used, and the unused one rots.
COL_OBCL_TO = "OBCL Update To"
COL_OBCL_CHANNEL = "OBCL Update Channel"
COL_OBCL_GROUP = "OBCL Update Text Group"

OBCL_SLACK = "Slack channel"
OBCL_TEXT = "Text group"
OBCL_NEITHER = "Not yet"

OBCL_UPDATE: List[Question] = [
    Question("obcl_to", COL_OBCL_TO,
             "Where should your OBCL update go?",
             "The picture of where every new start has got to, posted again "
             "each time it changes.",
             (OBCL_NEITHER, OBCL_SLACK, OBCL_TEXT), OBCL_NEITHER, False),
    Question("obcl_channel", COL_OBCL_CHANNEL,
             "Which Slack channel?",
             "Only if you chose Slack. The channel's ID, not its name.",
             (), "", False, "channel"),
    Question("obcl_group", COL_OBCL_GROUP,
             "Which text group?",
             "Only if you chose a text group. The group's name exactly as it "
             "appears in Messages, so Lucy opens the right conversation.",
             (), "", False),
]

# WHERE THEIR DAILY UPDATE GOES (Megan, 2026-11-22: "the channel they want
# their daily update posted in should also be asked on their enrollment
# form"). It was a line of Python per office in
# raf_daily_update/offices.py -- fine for five, and the reason the other
# three have posted into a holding room since 2026-11-19: nobody had asked
# them where their own room is.
#
# NOT REQUIRED, and blank is a real answer. An office with no room yet, or
# one that has not decided, keeps posting where it posts today, which is the
# holding channel -- the form should not be unanswerable for them.
#
# ANSWERING IT DOES NOT TURN POSTING ON. `posts_in_own_channel` is still what
# decides whether the Daily Update leaves the holding channel, and Megan
# gives each office its go one at a time. This answers WHERE, never WHETHER.
COL_DAILY_CHANNEL = "Daily Update Channel"

DAILY_UPDATE: List[Question] = [
    Question("daily_channel", COL_DAILY_CHANNEL,
             "Which Slack channel should your Daily Update be posted in?",
             "The channel's ID, not its name -- in Slack, click the channel "
             "name at the top, scroll to the bottom of the pop-up and copy "
             "the Channel ID. Leave it blank if you are not ready; it keeps "
             "going to the holding channel until you are.",
             (), "", False, "channel"),
]

# THE SIX THAT USUALLY MATCH. Behind one tick on the form: asking every office
# to retype six answers that are the same for almost all of them is how a form
# stops being filled in honestly ([[feedback_simple_ux]]).
STANDARD = {
    "position": "Sales Rep",
    "pay_basis": "Commissions",
    "pay_frequency": "Weekly",
    "department": "400 Sales",
    "country": "United States",
    "security_role": "Sales Rep",
}

JOB: List[Question] = [
    Question("position", OS.APEX_COLUMNS["position"], "Position",
             "What the role is called on the payroll record.",
             (), STANDARD["position"]),
    Question("pay_basis", OS.APEX_COLUMNS["pay_basis"], "Pay basis",
             "", ("Commissions", "Hourly", "Salary"), STANDARD["pay_basis"]),
    Question("pay_frequency", OS.APEX_COLUMNS["pay_frequency"],
             "Pay frequency", "",
             ("Weekly", "Bi-Weekly", "Semi-Monthly", "Monthly"),
             STANDARD["pay_frequency"]),
    Question("department", OS.APEX_COLUMNS["department"], "Department",
             "Apex's dropdown carries the number as well as the name.",
             ("100 Owner", "200 Admin", "400 Sales", "750 Chips", "900 1099"),
             STANDARD["department"]),
    Question("country", OS.APEX_COLUMNS["country"], "Country", "",
             ("United States",), STANDARD["country"]),
    Question("security_role", OS.APEX_COLUMNS["security_role"],
             "Security role", "What they can see when they sign in to Apex.",
             (), STANDARD["security_role"]),
]

ALL: List[Question] = (STERLING + CLOCK + CALENDAR + BOARD + BLUE_INK_BUNDLE
                       + PAY_STATES + OBCL_UPDATE + DAILY_UPDATE + JOB)


def columns_needed() -> List[str]:
    """Every column this form writes, in the order it asks for them."""
    return [q.column for q in ALL] + [COL_UPDATED_BY, COL_UPDATED_AT]


def missing_columns(headers) -> List[str]:
    """Which of ours the tab does not carry yet.

    `Blue Ink` and `Rate of Pay` were both in this list on 2026-11-19 -- read
    by the code, absent from the sheet. Creating them is the form's job, and
    naming them is how that stays visible rather than being discovered again.
    """
    have = {str(h).strip().lower() for h in (headers or [])}
    return [c for c in columns_needed() if c.strip().lower() not in have]


def problems(answers: Dict[str, str]) -> List[str]:
    """What is still unanswered, in the words of the person filling it in."""
    out = []
    for q in ALL:
        if q.required and not str(answers.get(q.field, "") or "").strip():
            out.append(q.label)
    # A CHANNEL ID, OR NOTHING. The box in the browser refuses a name as it is
    # typed, but `problems` is what the save actually goes through, and a
    # name stored here is a post that fails hours later in front of an owner.
    from automations.shared.onboarding_ui import normalize_channel_id
    for q in ALL:
        if q.kind != "channel":
            continue
        said = str(answers.get(q.field, "") or "").strip()
        if not said:
            continue                      # blank is a real answer here
        clean, trouble = normalize_channel_id(said)
        if trouble:
            out.append("%s (that is the channel's name, not its ID)" % q.label)
    # "NOT YET" IS NOT AN ANSWER TO KEEP. It is a setting on their own
    # screen that takes ten seconds, and left wrong the training calendar
    # reads short -- new starts simply do not appear, which looks like a
    # quiet week rather than a fault.
    if str(answers.get("calendar_view", "") or "").strip() == "Not yet":
        out.append("Set your ApplicantStream calendar to List view with Show "
                   "Notes ticked, then answer Yes — Lucy cannot read the "
                   "card view")
    # NEEDED ONLY BY AN OFFICE THAT HAS BLUE INK. They answer that two
    # questions up, and an office that said No skips Blue Ink entirely --
    # asking them to name a bundle they do not have is how a form stops
    # being answered honestly.
    if (str(answers.get("blue_ink", "") or "").strip().lower() == "yes"
            and not str(answers.get("bundle", "") or "").strip()):
        out.append("What is your onboarding document bundle called in Blue "
                   "Ink? (open Blue Ink -> Templates and copy the name)")
    # A DESTINATION WITH NOWHERE TO GO. Choosing Slack and leaving the
    # channel blank is not "not yet" -- it is an answer that reads as
    # configured and sends nothing, which is the worst of the three states
    # because nobody goes looking for it.
    to = str(answers.get("obcl_to", "") or "").strip()
    if to == OBCL_SLACK and not str(answers.get("obcl_channel", "")).strip():
        out.append("Which Slack channel? (you chose Slack for your OBCL update)")
    if to == OBCL_TEXT and not str(answers.get("obcl_group", "")).strip():
        out.append("Which text group? (you chose a text group for your OBCL "
                   "update)")
    rate = str(answers.get("rate", "") or "").strip().lstrip("$").strip()
    if rate:
        try:
            if float(rate) <= 0:
                out.append("What do you pay per hour? (must be more than 0)")
        except ValueError:
            out.append("What do you pay per hour? (numbers only, like 10.00)")
    return out


def row_for(answers: Dict[str, str], who: str, when: str) -> Dict[str, str]:
    """{column: value} ready to write. Unanswered fields are ABSENT.

    Absent rather than blank on purpose: every reader treats a blank cell as
    "nobody said", and writing "" over an answer somebody already gave would
    turn a real answer back into a question.
    """
    from automations.shared.onboarding_ui import normalize_channel_id

    row: Dict[str, str] = {}
    for q in ALL:
        said = str(answers.get(q.field, "") or "").strip()
        if said and q.kind == "channel":
            # People paste the whole Slack link as often as the bare id.
            # Store the id, so every reader gets one shape.
            said = normalize_channel_id(said)[0] or said
        if said and q.column == COL_TIME_ZONE:
            # THE ZONE, NOT THE WORD. "Pacific" means nothing to a clock, and
            # `America/Los_Angeles` is what handles its own daylight saving --
            # so the sheet holds the usable value and no reader needs this
            # mapping. A word nobody recognises is left as typed rather than
            # dropped, so it is visible on the tab instead of silently absent.
            said = zone_name(said) or said
        if said:
            row[q.column] = said
    row[COL_UPDATED_BY] = who
    row[COL_UPDATED_AT] = when
    return row


def zone_name(answer: str) -> str:
    """The stored zone for what the owner picked, or "" for anything else.

    THE LABEL IS NOT THE ANSWER. "Pacific" means nothing to a clock;
    `America/Los_Angeles` is what handles its own daylight saving. Anything
    unrecognised returns "" so the reader falls back to Central rather than
    acting on a word it cannot use ([[feedback_empty_means_proven_zero]] --
    better the old behaviour than a random hour's drift).
    """
    return ZONE_BY_LABEL.get(str(answer or "").strip(), "")


def zone_label(zone: str) -> str:
    """The owner's words for a stored zone -- for showing an answer back."""
    return LABEL_BY_ZONE.get(str(zone or "").strip(), "")

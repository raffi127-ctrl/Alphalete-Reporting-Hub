"""Everything about this report that a human might want to change.

Nothing here is a row/column index -- columns are found by their header LABEL
and weeks by the date in the tab's header row, so a template edit can't
silently shift what we read (see the no-hardcoded-columns rule in CLAUDE.md).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from automations.shared.workbooks import ALL_IN_ONE_RAF

REPO_ROOT = Path(__file__).resolve().parents[2]

# "All in One Local Office - Raf" -- the same workbook bg_check_sync writes to.
SHEET_ID = ALL_IN_ONE_RAF

# A new tab per week: "D2D OBCL 8.24", "D2D OBCL 8.31", ... The rolling
# undated "D2D OBCL" tab is deliberately NOT used as a source: it stacks every
# week ever, and we only ever want the lineup that is about to start.
DATED_TAB_PREFIX = "D2D OBCL"

# Our own log tab (created on first send). We never write into the OBCL
# columns themselves -- those are hand-maintained by the recruiting team.
LEDGER_TAB = "Blue Ink Log"

# --- Column labels on the OBCL tabs ----------------------------------------
COL_FIRST = "Name"
COL_LAST = "Last Name"
COL_EMAIL = "Email"
COL_PHONE = "Phone"
COL_FINAL_STATUS = "Final Status"
COL_BG_STATUS = "BG Status"          # real header is "BG Status : Last Checked"
COL_FRIDAY = "Friday Confirmation"
# Megan added this column 2026-08-24 (col N at the time, between "Onboarding
# Quizzes" and "Headshot Photo" -- found by LABEL, so it can move). Two states
# live in it: a light-green background the moment we send, and the checkbox
# ticked once Blue Ink shows the packet SIGNED. Note the space: the header
# reads "Blue Ink", not "Blueink".
COL_BLUEINK = "Blue Ink"
COL_TRAINER = "Trainer"

# --- Who does NOT get Blue Ink ---------------------------------------------
# Rule from Megan (2026-08-24): if they aren't going to start, don't send.
#
# Final Status (col J) started as "blank means still in the pipeline", so this
# began as "must be blank". That was wrong: the column carries GOOD outcomes
# too -- "Showed Up To CR" appeared on 8/24 and the blank-only rule silently
# excluded someone who WAS starting. So it's a block-list now (Megan's call,
# 2026-08-24): name the outcomes that stop a send, let everything else through.
#
# THE RULE ITSELF MOVED to automations/shared/new_start_eligibility.py on
# 2026-09-26 -- it is the same question every step on the OBCL tab has to
# answer, and there were three disagreeing copies of it. Re-exported under the
# original names so nothing that reads config.FINAL_STATUS_BLOCK_MARKERS et al
# has to change. Edit the shared module, not this.
#
# Note what did NOT move: the email checks in roster._skip_reason. "No email
# address" is a Blue Ink send problem, not a fact about whether the person is
# starting -- the follow-up report still owes their leader a text.
from automations.shared.new_start_eligibility import (  # noqa: E402
    BG_STATUS_BLOCK,
    FINAL_STATUS_BLOCK_MARKERS,
    FINAL_STATUS_KNOWN_OK,
    FRIDAY_BLOCK,
)

# --- WHEN IT GOES OUT, PER PERSON -------------------------------------------
# Megan, 2026-11-18: "2 days before their start -- Blue Ink, Slack and the
# Skool email, one send, per person, off their own start date rather than one
# time for everybody."
#
# This was a 7:30am daily batch over the whole newest tab (and Mondays only
# before 2026-11-16), so somebody starting Thursday got their contract on
# Monday. The clock is still daily; what changed is WHO is due on it.
#
# The lead is a FLOOR, not an appointment -- see
# automations/shared/new_start_timing.py for why, and for why de-duplication
# stays with the "Blue Ink" column rather than moving into the date maths.
from automations.shared import new_start_timing as _timing  # noqa: E402

SEND_LEAD_DAYS = _timing.DEFAULT_LEAD_DAYS

# How far back to keep looking for somebody who started and still hasn't
# signed. A week: their paperwork does not stop mattering because the day
# passed, but the book is not worth walking forever either.
SEND_LOOK_BACK_DAYS = 7

# --- Blue Ink ---------------------------------------------------------------
# Account: alphaletemarketing@gmail.com. The private API key is read from a
# gitignored file at the repo root (the repo is PUBLIC -- never inline it):
#
#   blueink-creds.json
#   {"blueink_api_key": "...", "envelope_template_id": "T-xxxxxxxxxx"}
#
# or from env BLUEINK_PRIVATE_API_KEY / BLUEINK_TEMPLATE_ID.
#
# PER OFFICE SINCE 2026-11-09 (Megan: "each ICD will have their own blueink
# account"). On an ICD's computer the key is THEIRS and lives under their home
# beside every other ECO credential, NOT in the repo: the ICD app may be
# installed where the user cannot write, and the repo copy is replaced on every
# update -- a key parked inside it is destroyed by a `git pull`. The home copy
# wins when it exists, so Alphalete's own machines are untouched.
ECO_CREDS_PATH = (Path.home() / ".config" / "lucy-reports" / "blueink-creds.json")


def login_creds() -> dict:
    """{'email', 'password'} for THIS machine's Blue Ink account, or {}.

    Blue Ink's sign-in is an email and a password with no second factor
    (screenshot, Megan 2026-11-23) -- "Continue with Google" is an
    alternative on that page, not a requirement. So the sign-in is the same
    shape as OwnerVille's and Sterling's, and is typed the same way.

    WHY THIS IS ALLOWED HERE WHEN session.py SAYS NOTHING TYPES A PASSWORD.
    That rule was written for ONE SHARED ACCOUNT driven from our machines,
    with the reason given as "the repo is public". The credential never goes
    in the repo: it lives beside every other ECO login in the owner's own
    home directory, readable by that user only, on the machine that already
    holds their OwnerVille, Sterling, AppStream and Apex passwords. An ICD's
    Blue Ink password is no different from those.

    Read from the same file as the API key so an office has one Blue Ink
    file, not two:

        ~/.config/lucy-reports/blueink-creds.json
        {"blueink_api_key": "...", "envelope_template_id": "T-...",
         "email": "...", "password": "..."}

    Absent is not an error -- it means this machine signs in by hand, which
    is what every machine did before.
    """
    import json
    import os
    env_user = os.environ.get("BLUEINK_EMAIL")
    env_pass = os.environ.get("BLUEINK_PASSWORD")
    if env_user and env_pass:
        return {"email": env_user, "password": env_pass}
    path = creds_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    email = str(data.get("email") or "").strip()
    password = str(data.get("password") or "")
    if not email or not password:
        return {}
    return {"email": email, "password": password}


def creds_path() -> Path:
    """This machine's Blue Ink key file. The office's own, else the repo's."""
    return ECO_CREDS_PATH if ECO_CREDS_PATH.exists() else REPO_ROOT / "blueink-creds.json"


# Keys that mean "this IS Alphalete", for whom the repo copy is the right one.
ALPHALETE_KEYS = ("raf", "alphalete", "")


def using_own_key() -> bool:
    """True when the key being read is this machine's own, not the repo's."""
    return ECO_CREDS_PATH.exists()


def assert_key_belongs_to(office_key: str) -> None:
    """Refuse to send for an office whose key is not on this machine.

    THE FALLBACK IS SAFE TO READ AND NOT SAFE TO SEND WITH. `creds_path`
    falls back to the repo copy so that Alphalete's own machines keep working
    untouched -- but for anybody else that copy is SOMEBODY ELSE'S ACCOUNT,
    and a Blue Ink bundle launches the moment it is created. The send would
    SUCCEED: the new start gets a real contract, out of Alphalete's account,
    with nothing anywhere reporting that the wrong office sent it. That is the
    worst shape a failure can take, which is why this refuses rather than
    warns.

    `icd_onboarding.launch_check.check_blueink` asks the same question before
    an office goes live. This is the same rule at the moment of sending,
    because a machine can lose its key after it has launched -- and a check
    that only ran once is not a guard.
    """
    key = str(office_key or "").strip().lower()
    if key in ALPHALETE_KEYS or using_own_key():
        return
    raise RuntimeError(
        "Blue Ink refused for office %r: this machine has no key of its own "
        "at %s, so the send would go out of ALPHALETE'S account. Put that "
        "office's own API key and envelope template id there (Blue Ink -> "
        "Settings -> API, on THEIR account). Never in the repo: it is public "
        "and a `git pull` destroys anything parked inside it."
        % (office_key, ECO_CREDS_PATH))


CREDS_PATH = creds_path()

API_BASE = "https://api.blueink.com/api/v2"

# The signer role key on the envelope template. All four templates on this
# account label their one signer 'employee-1'; `--list-templates` prints the
# real keys if a future template differs.
SIGNER_KEY = "employee-1"

# The Envelope Template's NAME as it appears on /dashboard/templates -- the UI
# path finds its row by this text. Keep it in step with envelope_template_id in
# blueink-creds.json (that id is only used by the now-capped API path).
TEMPLATE_NAME = "UNIVERSAL I9 MASTER FORM"


def template_name_for(office_key: str = "") -> str:
    """What this office's onboarding bundle is called in THEIR Blue Ink.

    Megan, 2026-11-22: "every ICD will have their own blueink account login.
    that isn't something we have to build. we just have to make sure they
    have their document bundle labeled correctly so lucy knows which to send
    out."

    Which is the whole of it. The account and the key are the office's own
    setup on their own machine, and the live send already finds the template
    BY NAME on the Envelope Templates page -- the id in the creds file is
    only used by the capped API path. So the one thing that has to travel
    between offices is the NAME, and it was this constant: Alphalete's.

    THE OFFICE LOOKS IT UP, and nothing is filled in for them (Megan,
    2026-11-22: "we need to say to go into their blueink and look at the
    name of their doc bundle to map it out"). Alphalete's name would be the
    worst possible default here: it is real, so the box reads as answered,
    and it exists in no other account -- so the first send of a new office's
    first week finds no such template and goes nowhere.

    AN OFFICE THAT HAS NOT ANSWERED GETS "", not ours. Handing back
    Alphalete's name would have the office's own run hunt for a template
    that cannot be there; "" lets the caller say which office has not
    answered, before a browser is even opened.

    Passing no key is Alphalete itself and keeps the constant, so every
    caller that has not been taught about offices behaves as it did.
    """
    key = str(office_key or "").strip().lower()
    if not key:
        return TEMPLATE_NAME
    try:
        from automations.icd_onboarding import office_steps as OS
        from automations.eco_onboarding import settings as ES
        for row in OS._rows():
            if str(row.get(OS.COL_OFFICE, "")).strip().lower() == key:
                return str(row.get(ES.COL_BUNDLE, "") or "").strip()
    except Exception:      # noqa: BLE001 -- unreadable is not "use ours"
        return ""
    return ""

# --- WHAT THE NEW START ACTUALLY RECEIVES ----------------------------------
# PER OFFICE SINCE 2026-11-15 (Megan: "we need to make sure that it's set up
# correctly for that ICD when we launch"). An ICD's new start opening an email
# that says Alphalete has been sent somebody else's paperwork as far as they
# can tell, on the first thing our company ever sends them.
#
# READ THIS BEFORE CHANGING ANY OF IT. These three strings are used by the API
# path only, and the API path is capped -- the live sends go through
# `ui_send.py` (`--via ui`, the default), which sets the envelope LABEL and
# nothing else. Checked against the account on 2026-11-15: every bundle sent on
# 11/14 carries `email_subject: ''` and `email_message: ''`, so what new starts
# actually get today is Blue Ink's own stock wording, and these words have
# never reached anybody. The envelope template holds no subject or message
# either (its only fields are name, documents and signers), so there is no
# third place this could be coming from.
#
# They are defined per office anyway, because the moment the wizard's message
# step is wired up this is what it will say, and because `preflight.py` reads
# them to tell an office what its new starts WILL get before it launches.
DEFAULT_OFFICE_NAME = "Alphalete"


def office_name(office_key: str = "") -> str:
    """The office's own name for itself, as THEY typed it.

    From the ECO sign-up's `office_label`, which the roster deliberately leaves
    exactly as typed -- it is their wording, and title-casing it mangles things
    like AT&T. Falls back to Alphalete, so Alphalete's own machines and
    anything that does not name an office read exactly as they did before.
    """
    key = str(office_key or "").strip().lower()
    if not key or key in ("raf", "alphalete"):
        return DEFAULT_OFFICE_NAME
    try:
        from automations.icd_alerts import offices as O
        o = O.get(key)
    except Exception:                                       # noqa: BLE001
        o = None
    return (getattr(o, "label", "") or "").strip() or DEFAULT_OFFICE_NAME


def bundle_label(office_key: str = "") -> str:
    return "%s New Start Docs" % office_name(office_key)


def email_subject(office_key: str = "") -> str:
    return "Your %s onboarding documents" % office_name(office_key)


def email_subject_v2(office_key: str = "") -> str:
    """DRAFT, awaiting Megan's sign-off (Raf: "Lets get in agreement with
    email title and body"). Named apart from `email_subject` so approving it
    is one edit here and nothing goes out on a half-made decision."""
    return "Your I-9 and W-4 from %s — please sign before your first day" % \
        office_name(office_key)


def email_message(office_key: str = "") -> str:
    """What the new start reads in the Blue Ink email.

    WRITTEN TO SIT BESIDE THE SKOOL EMAIL, not to stand alone. That one goes
    out Monday 8am from the office's reception Gmail and already promises this
    one in its own words -- "You'll also get a separate email from Blueink with
    your I-9 and W-4. Please fill those out before you come in. It speeds
    everything up on your first day." So this says the same thing in the same
    voice, and does not re-explain orientation or the three apps: a new start
    who gets two emails that each try to be the whole welcome reads neither.

    WHAT IS DELIBERATELY NOT IN IT:
      * no start date, time or address. Those differ per office and per person,
        they are what the recruiter said on the phone, and an email that
        contradicts that call is worse than an email that stays quiet
        ([[feedback_house_rules_per_office]]).
      * no pay, and nothing about who we hire or who the job suits
        ([[feedback_recruiting_copy_compliance]]).
      * no deadline we cannot enforce. "Before your first day" is the real
        requirement; a made-up "within 24 hours" is a threat we never act on.
      * no office name in the BODY. The subject and the sender already carry
        it, and the body is the one part that would be WRONG rather than
        merely generic if an office resolved badly.
    """
    return ("Welcome aboard! These are your I-9 and W-4. Please sign them "
            "before your first day — it saves you doing paperwork when you "
            "could be training. If anything on them looks wrong, tell your "
            "trainer before you sign.")


# The originals, unchanged, for anything still reading them by name.
BUNDLE_LABEL = bundle_label()
EMAIL_SUBJECT = email_subject()
EMAIL_MESSAGE = email_message()


def _creds() -> dict:
    # Resolved per call, not once at import: the ECO setup writes the home copy
    # while the process that will read it is already running.
    try:
        return json.loads(creds_path().read_text())
    except Exception:
        return {}


def api_key() -> str:
    val = str(_creds().get("blueink_api_key")
              or os.environ.get("BLUEINK_PRIVATE_API_KEY", "")).strip()
    if not val:
        raise RuntimeError(
            f"No Blue Ink API key. Create {CREDS_PATH.name} at the repo root "
            '{"blueink_api_key": "...", "envelope_template_id": "T-..."} '
            "(Blue Ink -> Settings -> API, on the alphaletemarketing@gmail.com "
            "account), or set BLUEINK_PRIVATE_API_KEY. That file is gitignored "
            "by the *-creds.json* rule -- never commit it.")
    return val


def template_id() -> str:
    val = str(_creds().get("envelope_template_id")
              or os.environ.get("BLUEINK_TEMPLATE_ID", "")).strip()
    if not val:
        raise RuntimeError(
            "No Blue Ink envelope template set. Run "
            "`python -m automations.blueink_docs.run --list-templates` to see "
            f"the options, then put its id in {CREDS_PATH.name} as "
            '"envelope_template_id" (or set BLUEINK_TEMPLATE_ID).')
    return val

"""Office Admin page: one login per office admin, two buttons.

Raf, Slack DM to Megan 2026-11-01 ("Admin git hub -- top priority"):

    Username and login per admin.
    Button to:
      * send background checks
      * Add 2nd rd contacts to the distro
    Automated message on recruiting chat to accept sending BGC & adding
    contacts. Let's test in Omar's office.

ONE ADMIN PER OFFICE. Each admin signs in with their own username +
password (hashed on the 'Office Admins' tab -- never the password itself)
and only ever sees and acts on their own office.

WHERE EACH BUTTON'S WORK HAPPENS (Megan 2026-11-03: the admin is in a
different location from the office's ECO computer, and only the ECO computer
holds the Sterling login)
  * "Find today's offers" -> on the ADMIN'S computer: its own
    ApplicantStream login, today's calendar, SECOND INTERVIEWS rows marked
    "Offer Position? = Yes" (offered.py).
  * "Send background checks" -> queued from the admin's computer straight
    to the office's ECO computer over the LucyEco relay (relay_client.py).
    The ECO computer signs in to the office's Sterling account -- Sterling
    emails a code; the office forwards those code mails to the reporting
    inbox and Lucy 1 hands the code back, exactly like SaraPlus codes
    (icd_alerts/code_answer.py) -- and sends the e-invites.
  (No "2nd round contacts" button: second_round_contacts already runs on
   its own on Lucy 1 at 12:00 / 15:30 + the 06:00 audit -- Megan 2026-11-04.)

Every press is a row on 'Admin Requests' -- the record of who sent what.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

# The workbook holding both tabs. Default = the Org workbook ('2R Contacts'
# lives there too); the hosted page can point elsewhere with a secret.
SHEET_ID_ENV = "OFFICE_ADMIN_SHEET_ID"

ADMINS_TAB = "Office Admins"
ADMINS_HEADERS = ["Username", "Password Hash", "Office Key", "Admin Name",
                  "Active", "Created", "Last Login", "Notes"]

REQUESTS_TAB = "Admin Requests"
REQUESTS_HEADERS = ["Request ID", "Requested At", "Username", "Office Key",
                    "Action", "Details", "Status", "Result", "Updated At",
                    "Job ID"]

# Per-office answers the Sterling E-Invite form needs every time, asked ONCE
# on the page and kept here (Megan 2026-11-03: "we will need to ask the city
# and state of the owner"). Sterling's "Location of Job/Position".
SETTINGS_TAB = "Office Settings"
SETTINGS_HEADERS = ["Office Key", "State", "City", "Updated By", "Updated At"]

# Sterling's State dropdown, by its visible names.
US_STATES = (
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming")

# Request actions -- one per button.
FIND_BGC = "find_bgc"
SEND_BGC = "send_bgc"
# New starts -> Apex, in two presses. The LOOK UP press opens nothing and
# saves nothing: it comes back with the week's names and the gender that
# would be used, which is what the admin is shown before they send (Megan,
# 2026-11-24: "we should pop up the names and gender we assume - then the
# admin/icd sending can change if they want before hitting send"). The SEND
# press carries their answers.
APEX_LOOK = "apex_look"
APEX_SEND = "apex_send"
# The week-3 drug test, in the same two presses. NOT part of the background
# check (Rafael Hidalgo, 2026-11-24: "If we send the drug test with the
# background check, it'll cause confusion, it'll need resent because the
# applicant won't find it / if they're new and they take it, the owner gets
# charged more money. we like doing the drug test on WK3 of starting / so I
# think a button to send it would be great"). FIND reads the training week
# three weeks back; SEND places the Sterling order for the people ticked.
FIND_DRUG = "find_drug"
SEND_DRUG = "send_drug"
ACTIONS = (FIND_BGC, SEND_BGC, APEX_LOOK, APEX_SEND, FIND_DRUG, SEND_DRUG)

# Request statuses, in the order a row moves through them.
QUEUED = "queued"
WORKING = "working"
AT_OFFICE = "at office computer"   # send_bgc: waiting on the ECO machine
DONE = "done"
FAILED = "failed"
OPEN_STATUSES = (QUEUED, WORKING, AT_OFFICE)

# Who needs a background check: ApplicantStream Calendar -> SECOND
# INTERVIEWS -> "Offer Position?" = Yes, today (Megan 2026-11-03). Read by
# offered.py. ARS "BOB Process" step 2: BGCs go to those we WANT to BOB,
# before the BOB call.

# A request older than this that never left 'queued'/'working' is reported
# failed, so the page never spins forever.
STALE_MINUTES = 90


@dataclass(frozen=True)
class Office:
    key: str              # LucyEco office key (relay) -- also the page's key
    owner: str            # as on the '2R Contacts' tab
    appstream_id: str     # ApplicantStream office id (the office's own)
    channel: str = ""     # office recruiting channel (the 6pm "not sent yet" alert)
    tz: str = "America/Chicago"   # office local time
    # The "not sent yet" alert, office-local HH:MM, Mon-Fri. 30 min BEFORE the
    # office's 2nd Round Daily Update (Lucy 2, 5:00 PM CT -- Megan 11/04: the
    # Daily Update is what results from this, so the alert goes first).
    alert_at: str = "16:30"
    # "dry": the office computer signs in and reports who it WOULD invite,
    # sends nothing. "live": sends. Set here, never on the office computer.
    bgc_mode: str = "dry"
    # The week-3 drug test. Its OWN switch, not bgc_mode's: the two orders are
    # billed separately and go out three weeks apart, so an office can be live
    # on background checks long before anybody has watched a drug order place.
    # Sharing one switch would arm this the moment BGC went live, which is
    # exactly the surprise that makes an owner's first drug bill a mystery.
    drug_mode: str = "dry"
    # New starts -> Apex. "off" means the office's computer refuses the job
    # outright. Default off, and OFF IS THE POINT: this one creates payroll
    # records, and Megan 2026-11-08: "we should only test on Raf's".
    # "dry" reads the calendar and the packets and reports who it would add;
    # "live" fills Apex. Set here, never on the office computer.
    apex_mode: str = "off"
    # Which OwnerVille programme this office's people are in. Alphalete is
    # RES-AT&T; ICDs are in different ones (Megan 2026-11-09: "ICDs are in
    # different programs so it won't always be RES for these"), and a wrong one
    # selects nothing and reads an empty table, which looks exactly like nobody
    # having done anything. Blank means "ask OwnerVille what it offers and
    # tell me" rather than guessing at Alphalete's.
    ov_program: str = ""
    # OTHER ApplicantStream accounts whose new starts onboard HERE.
    #
    # A NEW LAUNCH RECRUITS ON ITS OWN FUNNEL AND ONBOARDS UNDER SOMEBODY
    # ELSE'S (Megan 2026-11-20: "Al is a new launch so his reps are being
    # onboarded under Raf, which is why they are in Raf's OV account"). So
    # "which office recruited them" and "which OwnerVille onboards them" are
    # two different questions, and one id cannot answer both: the board seeded
    # from 11280 while the Owner Submit press walked Raf's OwnerVille, where
    # Algemar's people were sitting ready. Jaime Molina was fully complete and
    # invisible to the board for exactly this reason -- 7 of them that week,
    # 16 more scheduled for the next.
    #
    # ONLY THE SEED READS THESE. Everything else about the office -- its
    # reception inbox, its no-show calendar, its Sterling settings -- still
    # belongs to `appstream_id`, because those are the OFFICE's, not the
    # funnel's.
    # Each entry is an id, or ("id", "What to call it on the board") -- the
    # board draws a labelled divider per funnel, so the name is worth giving.
    extra_appstream_ids: tuple = ()


# Omar first (Raf: "Let's test in Omar's office").
OFFICES: Dict[str, Office] = {
    # AppStream 24232: eStream closed 24153 on 2026-11-04.
    "omar": Office(key="omar", owner="Omar Mohamad", appstream_id="24232",
                   channel="C0CEZ64FYM6", bgc_mode="dry", tz="America/Detroit",
                   alert_at="17:30"),   # = 4:30 PM CT
    # Raf's MacBook (ECO key raf, enrolled 11/03) is the FIRST test machine
    # (Megan 2026-11-04): his Sterling account is rahidalgo, codes to raffi127.
    "raf": Office(key="raf", owner="Rafael Hidalgo", appstream_id="11280",
                  channel="C06881A7WLV", bgc_mode="dry", tz="America/Chicago",
                  # ARMED 2026-11-25, RAF ONLY, to watch the first real drug
                  # order go in. His office asked for the test and supplied
                  # the names. Nobody else is live: `drug_mode` defaults to
                  # "dry", and it is a per-office switch precisely so this
                  # line does not arm forty owners' billing at once.
                  drug_mode="live",
                  alert_at="16:30", apex_mode="dry", ov_program="RES-AT&T",
                  # 23965 = Algemar Kennel El Paso, a new launch onboarding
                  # under Raf (Megan 2026-11-20).
                  extra_appstream_ids=(("23965", "Algemar Kennel El Paso"),)),
}


def office(key: str) -> Optional[Office]:
    return OFFICES.get((key or "").strip().lower())


def sheet_id(override: str = "") -> str:
    """The workbook the admin page's tabs live in.

    THE LAST RESORT IS A HUB IMPORT, and this file ships to office machines as
    part of the Apex job -- where `org_sales_board` does not exist. Guarded so
    that a machine without it gets a sentence naming the environment variable
    instead of ModuleNotFoundError from three frames down. Nothing on an
    office's own computer opens this workbook: the job carries what it needs.
    """
    if override:
        return override
    env = os.environ.get(SHEET_ID_ENV, "").strip()
    if env:
        return env
    try:
        from automations.org_sales_board.run import SHEET_ID
    except ImportError:
        raise RuntimeError(
            "this machine has no %s set and cannot reach the Hub's copy of "
            "the id, so there is no admin workbook to open. Set %s if this "
            "box really is meant to read it."
            % (SHEET_ID_ENV, SHEET_ID_ENV))
    return SHEET_ID

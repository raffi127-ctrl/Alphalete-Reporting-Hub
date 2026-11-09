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
ACTIONS = (FIND_BGC, SEND_BGC)

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
    appstream_id: str     # ApplicantStream office id
    channel: str = ""     # office recruiting channel (the 6pm "not sent yet" alert)
    tz: str = "America/Chicago"   # office local time
    # The "not sent yet" alert, office-local HH:MM, Mon-Fri. 30 min BEFORE the
    # office's 2nd Round Daily Update (Lucy 2, 5:00 PM CT -- Megan 11/04: the
    # Daily Update is what results from this, so the alert goes first).
    alert_at: str = "16:30"
    # "dry": the office computer signs in and reports who it WOULD invite,
    # sends nothing. "live": sends. Set here, never on the office computer.
    bgc_mode: str = "dry"
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
                  alert_at="16:30", apex_mode="dry", ov_program="RES-AT&T"),
}


def office(key: str) -> Optional[Office]:
    return OFFICES.get((key or "").strip().lower())


def sheet_id(override: str = "") -> str:
    if override:
        return override
    env = os.environ.get(SHEET_ID_ENV, "").strip()
    if env:
        return env
    from automations.org_sales_board.run import SHEET_ID
    return SHEET_ID

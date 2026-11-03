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
  * "Add 2nd round contacts" -> Lucy 1 (it holds the Contacts tokens):
    the page writes a row on 'Admin Requests', worker.py runs it.

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

# Request actions -- one per button.
FIND_BGC = "find_bgc"
SEND_BGC = "send_bgc"
ADD_CONTACTS = "add_contacts"
ACTIONS = (FIND_BGC, SEND_BGC, ADD_CONTACTS)

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
    channel: str = ""     # office recruiting channel (phase 2 accept message)
    # "dry": the office computer signs in and reports who it WOULD invite,
    # sends nothing. "live": sends. Set here, never on the office computer.
    bgc_mode: str = "dry"


# Omar first (Raf: "Let's test in Omar's office").
OFFICES: Dict[str, Office] = {
    "omar": Office(key="omar", owner="Omar Mohamad", appstream_id="24153",
                   channel="C0C6HKZ63EK", bgc_mode="dry"),
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

"""Send Sterling background-check e-invites from this office's own computer.

Called by office_jobs for a 'bgc_send' job. The people come from the office
admin's ticks on the office admin page (read off ApplicantStream on the
admin's own computer).

WHY HERE (Megan 2026-11-03): the office admin is somewhere else; THIS is the
computer that holds the office's Sterling login. The admin's page queues the
job (office_admin/relay_client.py); office_jobs.py hands it to us.

THE SIGN-IN: Sterling emails a code on every login (noreply@us.fadv.co,
"Authentication Request", "Your authentication code is 966828."). Same road
as SaraPlus codes: the office's Gmail filter forwards ONLY those code mails
to the reporting inbox, the office's address goes on the relay workbook's
'Sterling Code Mail' tab, and at the code screen this calls code() below --
Lucy 1 (code_answer, service "sterling") finds the code and hands it back.

NOT WIRED YET: the Sterling portal's own click path (login page, code screen,
the "send e-invite" form and which package to pick) has never been automated
here -- bg_check_sync only ever read Sterling's EMAILS. Until it is mapped
from a real signed-in session:
  * dry  -> answers who it WOULD invite (nothing is sent, nothing signed in)
  * live -> refuses, so no admin ever believes invites went out that didn't.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

WIRED = False

# --- the E-Invite form's Order Information (Megan 2026-11-03, screenshots;
# resources/sterling/portal-map.md section 4) ---------------------------------
# Bill To, WFD Workflow and Charge Type come prefilled on each ICD's own
# account and are never touched. These three are picked:
# Job Position: each ICD account lists ~3; the right one is whichever says
# "Elite" -- "Sterling - Elite" on some, "Sterling Elite / Extra" on others
# (Megan 2026-11-04). pick_elite: exactly one, else stop.
# Screening Package: same rule (Megan 2026-11-04) -- the one saying Elite.
JOB_POSITION = "Sterling - Elite"
SCREENING_PACKAGE = "Sterling - Elite"
# Bill Code: "just the only option that pops up for that office" -- 1658411
# on Raf's account. Anything but exactly one real option is a stop, never a
# guess (pick_bill_code).
_PLACEHOLDER_PREFIX = "<"


def pick_bill_code(options: List[str]) -> str:
    """The office's one Bill Code, off the dropdown's visible options.
    Raises ValueError unless there is exactly one real (non-placeholder)."""
    real = [o.strip() for o in options or []
            if o and o.strip() and not o.strip().startswith(_PLACEHOLDER_PREFIX)]
    if len(real) != 1:
        raise ValueError("expected exactly one Bill Code for this office, found %d (%s)"
                         % (len(real), ", ".join(real) or "none"))
    return real[0]


def pick_elite(options: List[str]) -> str:
    """The Job Position / Screening Package option that says Elite. Raises ValueError unless
    exactly one (non-placeholder) option does."""
    hits = [o.strip() for o in options or []
            if o and not o.strip().startswith(_PLACEHOLDER_PREFIX)
            and "elite" in o.lower()]
    if len(hits) != 1:
        raise ValueError("expected exactly one Elite job position, found %d (%s)"
                         % (len(hits), ", ".join(hits) or "none"))
    return hits[0]


def pick_option(options: List[str], want: str) -> str:
    """`want` among the dropdown's options, ignoring case/spacing. Raises
    ValueError when this account doesn't offer it."""
    norm = lambda x: " ".join((x or "").split()).lower()  # noqa: E731
    for o in options or []:
        if norm(o) == norm(want):
            return o
    raise ValueError("this Sterling account has no %r option" % want)


# --- THE WAY WE SEND: Client Hub bulk upload (Megan 2026-11-04, from Raf's
# Loom e7aecd44b6c84d1c8889a2b5f996d780) ---------------------------------------
# Old portal home -> "Click Here to access Client Hub" -> Invite Candidate ->
# Workflow Consent Plus -> Position (Elite) -> Package (Elite) -> Location
# (office state + city) -> Next -> Bulk upload: Sterling's CSV template is
# three columns. One upload sends the whole list.
# The three Position/Package options are "Drug Screen", "NBR" and the Elite
# one ("Elite" or "Elite / Extra") -- pick_elite.
# HEADERS ARE THE REAL TEMPLATE'S (Client Hub "CSV Template" button, downloaded
# 2026-11-04, copy at resources/sterling/client-hub-template.csv): exactly
# "First,Last,Email" + CRLF. The video said "First Name, Last Name, Email
# Address" -- that was wrong.
CSV_HEADERS = ("First", "Last", "Email")


# Client Hub's "Location of Job/Position" is ONE box that ends up reading
# "Plano, TX, USA" (Megan screenshot 2026-11-04) -- city, two-letter state,
# USA. The office's saved State is the full name, so it's shortened here.
STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}


def location_text(location: Dict) -> str:
    """What the Location box should read: 'Plano, TX, USA'. Raises
    ValueError on a state we can't shorten (never a guess)."""
    city = " ".join(str((location or {}).get("city") or "").split())
    state = str((location or {}).get("state") or "").strip()
    code = STATE_CODES.get(state)
    if not (city and code):
        raise ValueError("no usable office location (%r, %r)" % (city, state))
    return "%s, %s, USA" % (city, code)


def location_matches(shown: str, location: Dict) -> bool:
    """Does the box's text (or a suggestion) name the office's city + state?
    Case and spacing don't matter; 'USA' may or may not be there."""
    norm = lambda x: " ".join((x or "").replace(",", " , ").split()).lower()  # noqa: E731
    want = norm(location_text(location))
    got = norm(shown)
    return got == want or got == norm(location_text(location)[:-len(", USA")])


def pick_location_suggestion(suggestions: List[str], location: Dict) -> str:
    """The Location box is a type-ahead: type the city, a list pops up, click
    one (Megan 2026-11-04). Returns the suggestion naming the office's city +
    state; raises ValueError when none does -- never the first Plano listed."""
    for s in suggestions or []:
        if location_matches(s, location):
            return s
    raise ValueError("no location suggestion for %s among %d shown"
                     % (location_text(location), len(suggestions or [])))


# After the file is attached the card reads "Bulk candidates uploaded: N found";
# after Send Invites a pop-up "Your Bulk Upload is Processing" / "Your file has
# been submitted. A confirmation email will be sent momentarily." [OK]
# (Megan screenshots 2026-11-04). The pop-up is the proof it was submitted.
SUBMITTED_TITLE = "Your Bulk Upload is Processing"


def found_count(text: str) -> int:
    """N out of 'Bulk candidates uploaded: N found'; -1 when not shown."""
    import re
    m = re.search(r"uploaded:\s*([\d,]+)\s*found", text or "", re.I)
    return int(m.group(1).replace(",", "")) if m else -1


def check_found(text: str, expected: int) -> None:
    """Before Send Invites: Sterling must have read exactly the rows we wrote.
    Raises ValueError otherwise -- a short read is never sent."""
    n = found_count(text)
    if n != expected:
        raise ValueError("Sterling read %s candidate(s) from the file, expected %d"
                         % ("no" if n < 0 else n, expected))


def build_csv(people: List[Dict]) -> str:
    """The bulk-upload file for `people`. One row per person, de-duplicated
    by email (Sterling refuses a second invite to the same address anyway)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_HEADERS)
    seen = set()
    for p in people or []:
        first = " ".join(str(p.get("first_name") or "").split())
        last = " ".join(str(p.get("last_name") or "").split())
        email = str(p.get("email") or "").strip()
        if not (first and last and "@" in email) or email.lower() in seen:
            continue
        seen.add(email.lower())
        w.writerow((first, last, email))
    return buf.getvalue()


def code(since: dt.datetime, office_key: str = "", log=print) -> str:
    """The Sterling code mailed after `since`, via Lucy 1. Raises
    sara_code.NoCode when none comes (no forward set up, or too slow)."""
    from automations.icd_alerts import sara_code
    return sara_code.code_from_relay(since, office_key=office_key, log=log,
                                     service="sterling")


def _name(p: Dict) -> str:
    return ("%s %s" % (p.get("first_name") or "", p.get("last_name") or "")).strip()


def send_invites(people: List[Dict], *, live: bool, office_key: str = "",
                 log=print, location: Dict = None) -> Dict:
    """-> {'status': 'sent'|'dry_run'|'error', 'sent': [...], 'failed': [...],
    'would_send': [...], 'error': str}."""
    people = [p for p in people or [] if _name(p) and "@" in str(p.get("email") or "")]
    if not people:
        return {"status": "error", "error": "nobody to invite"}
    # Sterling's "Location of Job/Position" -- the office's, set once on the
    # admin page. Without it the form cannot be submitted.
    location = location or {}
    if not (location.get("state") and location.get("city")):
        return {"status": "error", "error": "the office's city and state aren't set"}
    if not live:
        return {"status": "dry_run", "would_send": [_name(p) for p in people],
                "location": "%s, %s" % (location["city"], location["state"]),
                "signed_in": False,
                "note": "test run -- Sterling sign-in not wired yet, nothing sent"}
    if not WIRED:
        return {"status": "error",
                "error": "sending from this computer isn't switched on yet -- send these in Sterling by hand",
                "failed": [_name(p) for p in people]}
    raise NotImplementedError  # pragma: no cover -- replaced when wired

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


# WHAT STERLING NEEDS. Where the job is, in Sterling's own words.
STERLING: List[Question] = [
    Question("state", COL_STATE, "What state is your office in?",
             "Sterling puts this on every background check invite.",
             US_STATES, "", True),
    Question("city", COL_CITY, "What city is your office in?",
             "Sterling puts this on every background check invite.",
             (), "", True),
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

ALL: List[Question] = STERLING + BOARD + PAY_STATES + JOB


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
    row: Dict[str, str] = {}
    for q in ALL:
        said = str(answers.get(q.field, "") or "").strip()
        if said:
            row[q.column] = said
    row[COL_UPDATED_BY] = who
    row[COL_UPDATED_AT] = when
    return row

"""What goes into Apex for one person — and nothing about where it came from.

Lifted out of run.py unchanged so the OFFICE computers can use it. run.py
imports the sales board, which imports the terminated-reps reader, which needs
Google Sheets: an office Mac has no business pulling any of that in just to
reuse one pure function, and shipping it would have dragged the whole Hub onto
machines that only ever read a calendar (2026-11-08).

run.py still exposes `apex_values` by importing it from here, so every existing
caller and every test is unchanged.
"""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:          # annotations only -- never imported at run time, so
    from automations.apex_new_starts import board as BRD        # noqa: F401
    from automations.apex_new_starts import blueink_data as BID  # noqa: F401


def apex_values(c: BRD.Candidate, hire: BID.NewHire) -> dict:
    """Everything that goes into Apex for one person, from three sources.

      the I-9        who they are   -- name, address, DOB, email, phone
      the board      when they started -- the date of their CR (classroom)
                     cell -- and their gender, from the column Megan added
      DEFAULTS       how this office hires -- Sales Rep, $10/hr, Texas,
                     Commissions, Weekly. Same for everyone, so they are
                     settings rather than data.
      the W-4        what the tax tab needs -- what they claim for dependents,
                     in dollars, and their filing status.

    The three pages are filled from ONE dict: whichever page is on screen,
    plan_fill matches what belongs to it and reports the rest as absent.

    Anything missing is simply absent from the dict; nothing is invented. The
    caller reports the gap and skips rather than typing a placeholder into
    somebody's payroll record.
    """
    from automations.apex_new_starts import apex as AX
    v = dict(hire.fillable())               # SSN cannot be in here -- see
                                            # NewHire.fillable
    v.update(AX.DEFAULTS)
    v.update(AX.TAX_DEFAULTS)
    email = v.pop("email", "")
    if email:
        v["account_email"] = email
        # Only needed for somebody being CREATED: the ones already on the
        # Pending tab have an account and it is not ours to change.
        #
        # THE FULL EMAIL, lower-cased (Megan, 2026-11-10: "use the full
        # email"). This REPLACES her 2026-09-09 "just use their email but
        # leave off the @gmail.com part" -- the live roster settled it. David
        # Flores's existing record is `dflore1381@gmail.com`, so the old rule
        # would have created people under a different convention from everyone
        # already in Apex, and a username is what somebody signs in with.
        # Lower-cased because that record is, while the signed packet spells
        # his address with a capital D.
        v["username"] = email.strip().lower()
        # NOT the user name. The new starts are ALREADY in Apex, sitting on the
        # Pending tab with their account created (Megan, 2026-09-09) -- which is
        # also why Apex rejected the email as "already being used": it was this
        # company's own existing record. The job is completing those profiles,
        # so the account fields are left exactly as they are.
    if c.hire_date:
        # Kept for the preview and the Slack thread. It is NOT typed: on a
        # Pending record the Hire Date is already set and shown as plain text.
        v["hire_date"] = c.hire_date.strftime("%m/%d/%Y")

    # The I-9 does not speak Apex. Two values need converting, and both fail
    # SILENTLY if they aren't -- a dropdown handed something it doesn't have
    # simply stays on 'Select', with no error anywhere.
    st = (v.get("state") or "").strip().upper()
    if st in AX.STATE_NAMES:
        v["state"] = AX.STATE_NAMES[st]     # 'TX' -> 'Texas'
    elif st:
        v.pop("state")                      # unrecognised: report, don't guess
    dob = _us_date(v.get("dob"))
    if dob:
        v["dob"] = dob
    else:
        v.pop("dob", None)

    phone = v.pop("phone", "")
    if phone:
        v[AX.PHONE_FIELD] = phone

    # Gender comes off the board's own column (Megan added it 2026-09-03).
    # Blank stays blank: an empty cell means nobody has said, and a name is not
    # evidence. The operator fills it, and the preview says who needs it.
    gender = _gender(c.gender)
    if gender:
        v["gender"] = gender

    # --- the tax tab, off the W-4 -------------------------------------------
    # Apex's 'Claim Dependents' wants DOLLARS, which is what the W-4 already
    # states -- no converting to a count. Prefer the form's own total; fall
    # back to 3a + 3b when whoever filled it left the total blank.
    dep = _dollars(hire.values.get("dep_total"))
    if dep is None:
        a = _dollars(hire.values.get("child_credit"))
        b = _dollars(hire.values.get("other_dep_credit"))
        dep = None if a is None and b is None else (a or 0) + (b or 0)
    # Apex REQUIRES Claim Dependants, and a blank W-4 Step 3 means they claim
    # nothing -- which is $0, not "unknown". Leaving it empty made Apex refuse
    # the tax page for everyone who didn't fill Step 3, which is most people.
    v["claim_dependents"] = f"{dep or 0:.2f}"

    # All three filing-status boxes are identified now (see MARITAL_BY_FLAG).
    ticked = [flag for flag in AX.MARITAL_BY_FLAG
              if str(hire.values.get(flag) or "").strip().lower() == "true"]
    if len(ticked) == 1:
        v["marital_status"] = AX.MARITAL_BY_FLAG[ticked[0]]
    elif not ticked:
        # NOBODY ticked is an answer now, not a gap: "Assume single and no
        # dependents if they don't fill out" (2026-09-10, via Megan). It is
        # still reported as an assumption -- filled AND flagged -- because it
        # is our reading of a blank box, not something they stated.
        v["marital_status"] = AX.MARITAL_SINGLE
        v["claim_dependents"] = f"{dep or 0:.2f}"
    # More than one ticked is left alone. That is a contradiction on a signed
    # form, and picking one of them would be inventing the answer.
    return v


def _dollars(value):
    """'4,000' -> 4000.0, or None when the box was left empty."""
    raw = str(value or "").replace(",", "").replace("$", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _gender(value) -> str:
    """The board's value as Apex's dropdown spells it, or '' if unrecognised."""
    raw = str(value or "").strip().lower()
    if raw in ("f", "female", "woman"):
        return "Female"
    if raw in ("m", "male", "man"):
        return "Male"
    return str(value or "").strip()


def _us_date(value) -> str:
    """A date the way Apex's boxes write one: M/D/YYYY, no leading zeros.

    The I-9 hands back whatever the person typed, and Apex's own records read
    '6/28/2004'. Anything unparseable comes back empty so the caller drops it --
    a birthday is not a field to approximate.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            d = dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        return f"{d.month}/{d.day}/{d.year}"
    return ""



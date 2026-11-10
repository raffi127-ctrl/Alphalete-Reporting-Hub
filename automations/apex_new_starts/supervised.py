"""The one supervised Apex run the automated save is waiting on.

    PYTHONPATH=. .venv/bin/python -m automations.apex_new_starts.supervised \
        --office raf --person "David Flores"

WHY THIS EXISTS. `eco_run.fill_one` refuses to save:

    "the Save step is the one thing still unproven -- it wants its
     supervised first run."

Filling was proved against the live form on 2026-11-08; pressing Save was not,
and a half-right save lands on a real person's payroll record. The gate asks
for exactly one thing -- somebody watches a record go in by hand -- and this is
the run that does it. It fills, it STOPS, and the person at the keyboard reads
the form and presses Save themselves.

IT NEVER PRESSES SAVE. Not behind a flag, not with --yes. The whole value of
this run is that a human saw the record before it existed, so a switch to skip
that would make it pointless.

WHAT IT NEEDS, AND WHAT IT DELIBERATELY DOES NOT
  * Blue Ink, for the packet their date of birth and address come out of.
  * Apex, signed into in the window this opens (no password is typed by us --
    the same rule as apex_signin / box_signin / ov_signin).
  * NOT ApplicantStream. The production path reads the office's training
    calendar to decide who is in the week; this takes ONE NAME from the person
    running it, so the rehearsal does not need a credential that is not on
    every machine. It is not a second opinion about who starts this week --
    nothing here writes a board or a result.

THE DUPLICATE CHECK IS THE OPERATOR'S, ON PURPOSE. `filler.py`'s browser path
checks All Employees before creating anybody, because "not on the Pending tab"
is not "not in Apex" and a create on somebody already there is a SECOND payroll
record for a real employee (Megan, 2026-09-17). That check is not re-ported
here: a second copy of two hundred lines of roster-DOM code, written against a
page this session cannot open, is how the two parallel fillers happened. The
person doing this run is looking at the roster anyway, so they do it -- and
this says so out loud rather than leaving them to assume it was handled.

NO SOCIAL IS FETCHED OR TYPED. `keep_ssn=False`, so there is nothing to leak;
the Social belongs to the tax tab in stage two, not to the create form.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional

from automations.apex_new_starts import blueink_data as BID
from automations.apex_new_starts import eco_run as ECO

# The create form is on screen when its own first control is. Read off the live
# form 2026-11-08 (resources/apex-form-controls.md), and the same model name
# eco_run.BY_MODEL fills, so this cannot drift away from what gets typed.
FORM_READY = '[ng-model="%s"]' % ECO.BY_MODEL["first"]

WAIT_SECONDS = 600
POLL_SECONDS = 3


def _board_person(office_key: str, name: str, week_start: dt.date,
                  log=print) -> Optional[ECO.Starter]:
    """One person off this week's onboarding board, as a Starter.

    The board is read rather than the training calendar: it was seeded off
    ApplicantStream's own Retention Report, and it is reachable from any
    machine with Google access instead of only from an AppStream holder.
    """
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import fillers as F
    from automations.icd_onboarding import sheet as S

    ws = S.open_board(F.workbook_for(office_key), create=False)
    if ws is None:
        log("  no onboarding board for %s yet." % office_key)
        return None
    rows = B.for_week(S.rows_of(ws.get_all_values()), week_start)
    if not rows:
        log("  the board has nobody for the week of %s."
            % B.week_label(week_start))
        return None
    want = B._fold(name)
    for r in rows:
        full = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        if B._fold(full) != want:
            continue
        started = r.get("Start") or ""
        when = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                when = dt.datetime.strptime(str(started).strip(), fmt).date()
                break
            except ValueError:
                continue
        return ECO.Starter(name=full, email=str(r.get("Email") or "").strip(),
                           phone=str(r.get("Phone") or "").strip(),
                           hire_date=when or week_start,
                           source="onboarding board")
    log("  %r is not on the week of %s. That week has: %s"
        % (name, B.week_label(week_start),
           ", ".join(sorted(("%s %s" % (r.get("Name", ""),
                                        r.get("Last Name", ""))).strip()
                            for r in rows)) or "nobody"))
    return None


def _describe(values: Dict) -> List[str]:
    """What is about to be typed, in the order a person reads a form.

    Printed BEFORE the browser opens, so the operator can stop on a wrong date
    of birth without a half-filled form on screen. Nothing sensitive is here
    that is not already on the form they are about to look at.
    """
    order = ("first", "middle", "last", "username", "account_email",
             "hire_date", "rate", "position", "pay_basis", "pay_frequency",
             "pay_state", "department")
    out = []
    for k in order:
        if values.get(k):
            out.append("    %-14s %s" % (k, values[k]))
    rest = sorted(set(values) - set(order))
    for k in rest:
        out.append("    %-14s %s" % (k, values[k]))
    return out


def wait_for_form(page, log=print, *, seconds: int = WAIT_SECONDS) -> bool:
    """Wait for the operator to land on the Add Employee form.

    Polled rather than navigated to. Clicking our own way there would walk past
    the All Employees check this run leaves to the person -- and a run that
    navigates for them teaches them it was handled.
    """
    waited = 0
    said = False
    while waited < seconds:
        try:
            if page.locator(FORM_READY).count() > 0:
                return True
        except Exception:          # noqa: BLE001 — mid-navigation
            pass
        if not said:
            log("")
            log("  Waiting for the Add Employee form.")
            log("")
            log("  In the window that just opened:")
            log("    1. Roster -> Employees -> the All Employees tab")
            log("    2. Filter for them and CHECK THEY ARE NOT ALREADY THERE.")
            log("       Not on Pending is not the same as not in Apex, and a")
            log("       create on somebody already there makes a second")
            log("       payroll record for a real employee.")
            log("    3. If they are not there, press Add Employee.")
            log("")
            said = True
        page.wait_for_timeout(POLL_SECONDS * 1000)
        waited += POLL_SECONDS
    return False


def signin(log=print, *, minutes: int = 20) -> int:
    """Open Apex in the profile this run uses, and wait while a person signs in.

    WHY THIS IS SEPARATE FROM `run`. `ApexSession.require_login` raises the
    moment Apex shows "change your password before you continue", which is
    right for a scheduled report -- it has no business sitting on that screen.
    But it also closes the window the person could have cleared it in, and on
    2026-11-10 that is exactly what happened: a fresh sign-in went password ->
    2FA -> change-password and the run exited with the screen in front of her.

    So this mode does not treat that screen as the end. It says what to do and
    keeps the window open, because the new password has to be set SOMEWHERE and
    setting it here leaves the session in the profile that needs it. Signing in
    with her own browser would clear the account's gate and leave this profile
    just as stale.

    NO PASSWORD IS TYPED OR READ. Same rule as everywhere else -- the person
    sets it, in the window, by hand.
    """
    import time

    from automations.apex_new_starts import apex as AX

    with AX.ApexSession(log=log) as s:
        if s.signed_in() and not s.password_gate():
            log("  Already signed in — %s" % s.page.url)
            return 0
        log("")
        log("  Apex is open. Sign in there, with the 2FA code if it asks.")
        log("")
        log("  IF IT ASKS YOU TO CHANGE YOUR PASSWORD, do it right here in")
        log("  this window. Apex is holding the account behind that screen,")
        log("  so nothing reaches the roster until it is cleared -- and")
        log("  doing it here is what leaves Lucy a session she can use.")
        log("  Nothing is typed for you and no password is read.")
        log("")
        deadline = time.time() + minutes * 60
        said = ""
        while time.time() < deadline:
            s.page.wait_for_timeout(2000)
            if s.password_gate():
                if said != "change":
                    log("  ...you're on the change-password screen — set the "
                        "new one here")
                    said = "change"
                continue
            step = s.on_signin_step()
            if step and step != said:
                log("  ...waiting — you're on %s" % step)
                said = step
                continue
            if s.signed_in():
                log("")
                log("  Signed in — %s" % s.page.url)
                log("  Now run the fill:")
                log("    PYTHONPATH=. .venv/bin/python -m "
                    "automations.apex_new_starts.supervised \\")
                log('        --office raf --person "First Last"')
                return 0
        log("  Nobody got through in %d minutes. Nothing was typed." % minutes)
        return 1


def run(office_key: str, name: str, week_start: dt.date, log=print) -> int:
    from automations.apex_new_starts import apex as AX

    person = _board_person(office_key, name, week_start, log=log)
    if person is None:
        return 1

    log("  %s — start %s, %s"
        % (person.name, person.hire_date, person.email or "no email"))

    # The packet. NO SOCIAL: keep_ssn stays off, so there is nothing here that
    # could reach a log, a result or a Google Sheet.
    hires = BID.for_people([person], keep_ssn=False)
    got = ECO.plan([person], hires, log=log)
    if not got["ready"]:
        why = (got["blocked"] or [{}])[0].get("why", "unknown")
        log("  held back: %s" % why)
        log("  Nothing was opened.")
        return 1
    _p, values = got["ready"][0]

    log("")
    log("  This is what will be typed into the create form:")
    for line in _describe(values):
        log(line)
    log("")
    log("  The password-reset box is set OFF deliberately — it defaults to")
    log("  TICKED, and saving with it on emails a brand new rep.")
    log("")

    with AX.ApexSession(log=log) as s:
        s.require_login()
        if not wait_for_form(s.page, log=log):
            log("  The form never appeared, so nothing was typed.")
            return 1
        log("  Filling.")
        res = ECO.fill_one(person, values, hires.get(person.name), log=log,
                           page=s.page, save=False)
        done = res.get("done") or []
        log("    filled: %s" % (", ".join(done) or "nothing"))
        if res.get("missed"):
            log("    NOT filled: %s" % ", ".join(res["missed"]))
        log("    Apex objects to: %s"
            % (", ".join(res.get("errors") or []) or "nothing"))
        log("    password-reset box: %s"
            % ("TICKED — untick it before saving"
               if res.get("passwordResetTicked") else "off"))
        log("")
        log("  READ THE FORM, THEN PRESS SAVE YOURSELF.")
        log("  Nothing here will press it. If the record is right, Save moves")
        log("  them onto the Pending tab, which is where stage two finds them.")
        log("")
        try:
            input("  Press Return here when you are done (the window closes). ")
        except EOFError:
            # Not at a keyboard: leave it be rather than closing a filled form
            # out from under somebody.
            log("  (no keyboard — closing)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fill ONE new start into Apex with somebody watching. "
                    "Never saves.")
    ap.add_argument("--office", default="raf", help="office key (default: raf)")
    ap.add_argument("--person", default="", help='"First Last", as the '
                                                 "board spells them")
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week")
    ap.add_argument("--signin", action="store_true",
                    help="just open Apex and wait for a sign-in (use this "
                         "when Apex is asking for a password change)")
    a = ap.parse_args(argv)
    if a.signin:
        return signin()
    if not a.person:
        ap.error("--person is required (or use --signin)")
    from automations.apex_new_starts import apex as AX
    from automations.icd_onboarding import board as B
    day = dt.date.fromisoformat(a.week) if a.week else dt.date.today()
    try:
        return run(a.office, a.person, B.week_start_of(day))
    except AX.PasswordChangeRequired as e:
        # Say the next command rather than only the diagnosis. Without it the
        # obvious move is to clear the gate in your own browser, which leaves
        # THIS profile just as stale and the next run back on this message.
        print("  %s" % e)
        print("")
        print("  Clear it in Lucy's own window, which also leaves her a")
        print("  usable session:")
        print("    PYTHONPATH=. .venv/bin/python -m "
              "automations.apex_new_starts.supervised --signin")
        return 1


if __name__ == "__main__":
    sys.exit(main())

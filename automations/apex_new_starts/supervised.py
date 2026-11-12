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
from automations.apex_new_starts import drive
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
        # GENDER COMES OFF THE BOARD, not a sales board -- an ECO machine has
        # no sales board to read (Megan, 2026-11-10). Blank is blank: nothing
        # guesses it, because a guess lands on a payroll record.
        return ECO.Starter(name=full, email=str(r.get("Email") or "").strip(),
                           phone=str(r.get("Phone") or "").strip(),
                           gender=str(r.get(B.GENDER) or "").strip(),
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
            log("  Apex will be showing 'change your password'. Ignore it —")
            log("  it never needs actioning. USE THE LEFT-HAND NAV, not a")
            log("  URL: typing one in from that page redirects you back to it.")
            log("")
            log("    1. ROSTER -> Employees -> the All Employees tab")
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

    For a profile that has actually been signed out. The fill run opens its
    own window and waits too, so this is only worth running on its own when
    you would rather get the sign-in out of the way first.

    IT DOES NOT ASK FOR A PASSWORD CHANGE. Apex lands every signed-in session
    on its change-password page and that prompt never needs actioning (Megan,
    2026-11-10: "apex ALWAYS goes to reset pw -- you have to use the NAV on the
    left"), so reaching it is SUCCESS here, not something to clear. An earlier
    version of this told her to set a new password there, which was wrong.

    NO PASSWORD IS TYPED OR READ, either way.
    """
    import time

    from automations.apex_new_starts import apex as AX

    with AX.ApexSession(log=log, login_timeout_s=minutes * 60) as s:
        if s.signed_in():
            log("  Already signed in — %s" % s.page.url)
            return 0
        log("")
        log("  Apex is open. Sign in there, with the 2FA code if it asks.")
        log("")
        log("  It will land on 'change your password'. IGNORE THAT — it is")
        log("  Apex's standing prompt and it never needs actioning. You are")
        log("  signed in as soon as you see it.")
        log("  Nothing is typed for you and no password is read.")
        log("")
        deadline = time.time() + minutes * 60
        said = ""
        while time.time() < deadline:
            s.page.wait_for_timeout(2000)
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


HOLD_MINUTES = 45


def _hold_open(page, log=print, *, minutes: int = HOLD_MINUTES) -> None:
    """Keep the filled form on screen until the person is finished with it.

    A filled Apex create form is not something to close out from under
    somebody, and closing it loses the fill -- so the window outlives this
    function's patience either way: it waits for Return when there IS a
    keyboard, and otherwise just stays up.

    WHY BOTH. Started from a terminal, Return is the obvious "done". Started
    any other way -- a launcher, a background shell, an agent -- stdin is not a
    tty and `input()` raises EOFError straight away, which used to close the
    browser the instant the fill finished. Nobody would ever have got to press
    Save.
    """
    import sys
    import time

    try:
        tty = sys.stdin is not None and sys.stdin.isatty()
    except Exception:          # noqa: BLE001
        tty = False
    if tty:
        try:
            input("  Press Return here when you are done (the window closes). ")
            return
        except EOFError:
            pass
    log("  No keyboard here, so the window stays open for %d minutes." % minutes)
    log("  Close it yourself when you are done — nothing is waiting on it.")
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        try:
            page.wait_for_timeout(5000)
        except Exception:      # noqa: BLE001 — they closed it; that is the signal
            log("  Window closed.")
            return


def _pages(values):
    """{page: {Apex label: value}} — filler's own map, not a second one."""
    from automations.apex_new_starts import filler as FL
    return FL.rows_for(values)


def _complete(page, who, person, apex_id, log=print) -> int:
    """Fill the employment tab of somebody ALREADY on Pending, stopping at Save.

    This is the path that runs twenty-odd times a week. The engine's own
    `runPerson` does all three tabs and SAVES each as it goes -- which is what
    must not happen while somebody is still deciding whether to trust it -- so
    this fills one tab and leaves the Save to the person watching.

    APEX IS NOT A SINGLE-PAGE APP ANY MORE. A probe on 2026-11-11 found no
    Angular on any page, and every tab is an ordinary link: moving between
    them is a FULL PAGE LOAD, which takes the injected script with it. So the
    script goes back in after each move, from here, rather than the page being
    trusted to still hold it.
    """
    want = "/employees/%s/edit/employment-record" % apex_id

    log("")
    log("  They are already on Pending, so this is the COMPLETE path:")
    log("  employment record, then user profile, then tax.")
    log("")

    if want not in (page.url or ""):
        drive.keep_loaded(page, [who], log=log)
        page.evaluate("async (p) => await window.__ansGoSpa(p)", want)
        page.wait_for_timeout(1500)
    if want not in (page.url or ""):
        log("  Could not open their employment record (%s)." % (page.url or "?"))
        log("  Nothing was typed.")
        return 1
    log("  On their employment record.")

    # The move was a page load, so put the engine back before asking it to
    # fill anything -- and wait for the form, which renders after the shell.
    if not drive.keep_loaded(page, [who], log=log):
        log("  The engine did not survive the move. Nothing was typed.")
        return 1
    # Wait for a REAL box, not for the loading message to clear -- the tab
    # drops that message before its fields exist, and a run that had just
    # filled everything found nothing at all on the next attempt.
    if not drive.wait_for_field(page, "Position", people=[who], log=log):
        log("  The form never finished loading, so nothing was typed.")
        _hold_open(page, log=log)
        return 1

    log("  Filling the FIRST tab only, and stopping before Save.")
    # THE DROPDOWNS GO FIRST, BY REAL CLICK. The engine's in-page clicks do
    # nothing to them since the Beta rewrite (2026-11-12), so these are set
    # from here, where the events are trusted. The engine then fills the plain
    # text boxes, which it has never had trouble with.
    picks = {k: v for k, v in (who.get("pages", {}).get("employment") or {}).items()
             if k in ("Position", "Basis of Pay", "Pay Frequency",
                      "State Working In", "Department")}
    if picks:
        drive.set_dropdowns(page, picks, log=log)
    # Rate of Pay is a numeric widget and ignores a JS-set value the same way:
    # it read as filled and Apex refused the save for a missing rate.
    rate = (who.get("pages", {}).get("employment") or {}).get("Rate of Pay")
    if rate:
        drive.type_into(page, "Rate of Pay", rate, log=log)
    got = page.evaluate(
        "async (p) => await window.__ansDoPage(p, 'employment')", who)
    done = (got or {}).get("done") or []
    miss = (got or {}).get("miss") or []
    log("    filled: %s" % (", ".join(done) or "nothing"))
    if miss:
        log("    NOT filled: %s" % ", ".join(miss))
    if not done:
        log("")
        log("  Nothing went in, so there is nothing to save. The boxes it")
        log("  looked for are not on this page under those labels.")
        _hold_open(page, log=log)
        return 1
    if "Gender" in miss or not person.gender:
        log("")
        log("  Gender is blank on the board for everybody this week, and Apex")
        log("  wants one on the profile tab. Set it by hand there.")
    log("")
    log("  READ THE TAB, THEN PRESS SAVE YOURSELF.")
    log("  Nothing here will press it. If this tab saves clean, the other two")
    log("  are the same shape and the whole-week run is safe to arm.")
    log("")
    _hold_open(page, log=log)
    return 0


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
    got = ECO.plan([person], hires, log=log, office_key=office_key)
    if not got["ready"]:
        why = (got["blocked"] or [{}])[0].get("why", "unknown")
        log("  held back: %s" % why)
        log("  Nothing was opened.")
        return 1
    _p, values = got["ready"][0]

    log("")
    log("  This is what will be typed in, on whichever path they need:")
    for line in _describe(values):
        log(line)
    log("")
    log("  The password-reset box is set OFF deliberately — it defaults to")
    log("  TICKED, and saving with it on emails a brand new rep.")
    log("")

    # 25 minutes, not the 10-minute default: this sign-in can go password ->
    # 2FA -> password again, and a person reading a code off a phone should
    # not lose a prepared fill to a timeout.
    with AX.ApexSession(log=log, login_timeout_s=25 * 60) as s:
        s.require_login()

        # WHICH OF THE TWO THIS PERSON NEEDS. Both checks of this week landed
        # on somebody already on Pending (David Flores, Victoria Newsom): an
        # ICD's people arrive there by themselves once they are in
        # OwnerVille, so COMPLETING is the common path and creating is the
        # rare one. Rehearsing only the create was rehearsing the wrong thing.
        who = {"name": person.name, "pages": _pages(values),
               "find": (person.name.split()[-1] if person.name else "")}
        if not drive.load(s.page, [who], week_start.strftime("%m/%d/%Y"), log=log):
            log("  The Apex engine did not load, so nothing was typed.")
            return 1
        if not drive.to_roster(s.page, log=log):
            log("  Could not get to Roster -> Employees, so nothing was typed.")
            return 1
        # The nav link was a full page load, so the engine went with it.
        if not drive.keep_loaded(s.page, [who],
                                 week_start.strftime("%m/%d/%Y"), log=log):
            log("  The Apex engine did not survive the move, so nothing was typed.")
            return 1
        need = drive.triage(s.page, [who], log=log).get(person.name, {})
        log("")
        log("  %s: %s" % (person.name, need.get("why", "unknown")))
        if need.get("need") == drive.COMPLETE:
            return _complete(s.page, who, person,
                             need.get("id", ""), log=log)
        if need.get("need") != drive.ADD:
            log("")
            log("  Neither path is safe for them. Creating would make a SECOND")
            log("  payroll record for a real employee, and there is nothing on")
            log("  Pending to complete. Find them on All Employees by hand.")
            log("  Nothing was typed.")
            return 1

        log("  Apex has never heard of them, so this is the create form.")
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
        _hold_open(s.page, log=log)
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
    except AX.NotLoggedIn as e:
        print("  %s" % e)
        print("")
        print("  Sign in first, then run this again:")
        print("    PYTHONPATH=. .venv/bin/python -m "
              "automations.apex_new_starts.supervised --signin")
        return 1


if __name__ == "__main__":
    sys.exit(main())

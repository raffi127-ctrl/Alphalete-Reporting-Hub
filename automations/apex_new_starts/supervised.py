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

THE SOCIAL IS FETCHED, AND TYPED INTO THE TAX TAB. It used to be withheld
(`keep_ssn=False`) on the grounds that the create form does not need one. That
was true while this run only reached the employment tab -- and wrong the
moment it reached the third, because Apex will not save the tax tab without a
Social, so the rehearsal could never finish the thing it exists to rehearse
(Megan, 2026-11-13: "I can't save it without a social").

It is handled the way it is everywhere else here: wrapped in `Secret`,
unwrapped at exactly one call site, typed with `secret=True` so the log says
only whether a box took it, and never returned, echoed or written to a Sheet.
Same data this run already types off the same signed packet -- a date of
birth and a home address are not less personal than a Social.
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
    from automations.icd_onboarding import sheet as S

    ws = S.board_for(office_key, week_start, create=False)
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
        # GENDER IS GUESSED FROM THE FIRST NAME, at the moment Apex is typed
        # (Megan, 2026-11-24: "gender now is just assumed based on name and
        # does not belong on the OBCL"). It used to be read off a Gender
        # column on the board; that column left the board the same day, so
        # this read silently returned "" and `plan` held EVERY person back
        # for "no gender on the board" -- which would have made this
        # rehearsal open nothing at all. Found before the sitting, not during
        # it.
        #
        # THIS IS THE RIGHT PLACE FOR THE GUESS: the person running this run
        # reads every value on screen before pressing Save, so a wrong one is
        # in front of the one human who can fix it. A name the guesser will
        # not call still comes back blank and is still held, because a guess
        # lands on a payroll record.
        from automations.icd_onboarding import gender_suggest as GS
        first = str(r.get("Name") or "").strip()
        return ECO.Starter(name=full, email=str(r.get("Email") or "").strip(),
                           phone=str(r.get("Phone") or "").strip(),
                           gender=GS.suggest(first),
                           hire_date=when or week_start,
                           source="onboarding board")
    log("  %r is not on the week of %s. That week has: %s"
        % (name, B.week_label(week_start),
           ", ".join(sorted(("%s %s" % (r.get("Name", ""),
                                        r.get("Last Name", ""))).strip()
                            for r in rows)) or "nobody"))
    return None


def _packet_person(name: str, week_start: dt.date, start: dt.date = None,
                   log=print):
    """The same person off their own signed Blue Ink packet, when the board
    has no row for them.

    WHY A SECOND SOURCE. Megan, 2026-11-24: "Frias isn't in payroll at all so
    he's one that would need added" -- and the people who most need adding by
    hand are exactly the ones the board missed. Refusing them because a Sheet
    has no row would make this run useless for its own purpose.

    IT IS NOT A LOOSER SOURCE, it is the SAME one. Every value Apex gets --
    date of birth, address, Social -- already comes out of this packet; the
    board was only ever supplying a name, an email and a start date. So this
    reads the name and email off the packet's own signer, which is the person
    who signed, and takes the start date from --start (or the week) because a
    packet does not carry one.

    IT STILL REFUSES AN UNSIGNED PACKET. "co" is complete. A packet still out
    for signature has no typed values in it, so filling off one would put
    blanks on a payroll record.
    """
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import gender_suggest as GS

    want = B._fold(name)
    last = (name.split()[-1] if name.split() else name)
    try:
        found = BID.search_bundles(last, limit=25)
    except Exception as e:
        log("  could not search Blue Ink: %s: %s" % (type(e).__name__, e))
        return None
    for b in found or []:
        for pk in b.get("packets") or []:
            who = str(pk.get("name") or "").strip()
            if B._fold(who) != want:
                continue
            if str(b.get("status") or "").lower() != "co":
                log("  %s has a Blue Ink packet, but it is %r, not signed. "
                    "Nothing to fill off." % (who, b.get("status")))
                return None
            log("  not on the board -- using %s's own signed packet (%s, "
                "signed %s)." % (who, b.get("id"), (b.get("created")
                                                    or "?")[:10]))
            return ECO.Starter(name=who,
                               email=str(pk.get("email") or "").strip(),
                               phone=str(pk.get("phone") or "").strip(),
                               gender=GS.suggest(who.split()[0] if who.split()
                                                 else who),
                               hire_date=start or week_start,
                               source="blue ink packet")
    log("  %r has no Blue Ink packet either." % name)
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
    rest = sorted(k for k in set(values) - set(order)
                  if not k.startswith("_"))
    for k in rest:
        out.append("    %-14s %s" % (k, values[k]))
    return out


def _drivable(page) -> bool:
    """jQuery is on the page.

    THE FIRST TEXT BOX IS NOT THE FORM BEING READY. Waiting on it alone
    returned True on a page still loading its libraries, so the fill ran with
    `window.jQuery` undefined: the text boxes took their values, every
    dropdown came back "no widget", and Hire Date threw (Luis Frias,
    2026-11-24). Every Kendo control -- the dropdowns, the datepicker, the
    rate box -- is driven through jQuery, so a page without it can only ever
    be half filled, and half a payroll record is the thing this run exists to
    not produce.

    jQUERY ONLY, NOT `window.kendo` TOO. The first version of this wanted
    both, and the form never came back ready: Kendo is reached through
    jQuery's `.data()` here and is not a dependable global on this page --
    `filler.kw` has always treated `window.kendo` as an optional extra branch.
    Requiring it turned a crash into a ten-minute silent wait, which is worse,
    because a crash at least says what went wrong (2026-11-24).
    """
    try:
        return bool(page.evaluate(
            "() => !!(window.jQuery || window.$)"))
    except Exception:              # noqa: BLE001 — mid-navigation
        return False


def _id_in_url(url: str) -> str:
    """The employee id out of an Apex URL, or "" if there is not one.

    Read rather than guessed: after the create form saves, the page lands on
    the new record and its id is the only place the new number appears.
    """
    import re
    m = re.search(r"/employees/(\d+)", str(url or ""))
    return m.group(1) if m else ""


def _readback(res, log=print) -> None:
    """What is in the boxes NOW, for the boxes that matter.

    The page's own red messages stopped being a verdict when the framework
    went: nothing re-renders them, so one can sit there over a filled box.
    This prints what the fill could read back instead, which is the thing a
    person at the keyboard would otherwise have to check by eye.
    """
    got = res.get("readback") or {}
    if not got:
        return
    log("    read back:")
    for k in sorted(got):
        if k.startswith("select:") or k.startswith("$ctrl"):
            log("      %-46s %r" % (k, got[k]))


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
                # THE GATE REPORTS, IT DOES NOT BLOCK. Requiring jQuery here
                # meant waiting for something the live Add Employee form never
                # provides -- it has neither `window.jQuery` nor `window.$` --
                # so the run sat on an open, empty form until it timed out
                # (Megan, 2026-11-24: "nothing is filling"). A fill that
                # reaches the text boxes and NAMES what it could not reach is
                # worth more than one that never starts: the guards below mean
                # it can no longer throw, and `missed` says what is left.
                if not _drivable(page):
                    # Said, not acted on. The fill needs no jQuery any more
                    # (the rewritten form has none), but knowing which shape
                    # of page a run met is worth one line in the log.
                    log("  (no jQuery global on this page — Kendo and "
                        "Angular are here, just bundled)")
                return True
        except Exception:          # noqa: BLE001 — mid-navigation
            pass
        if not said:
            log("")
            log("  Waiting for the Add Employee form.")
            try:
                seen = page.locator(FORM_READY).count() > 0
            except Exception:      # noqa: BLE001
                seen = False
            if seen:
                log("  (the form is there, but jQuery is on neither "
                    "window.jQuery nor window.$ —")
                log("   reload the page if this does not clear)")
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


def _complete(page, who, person, apex_id, log=print, *,
              social=None, press_save: bool = False, tabs=None) -> int:
    """Fill the employment tab of somebody ALREADY on Pending, stopping at Save.

    This is the path that runs twenty-odd times a week. The engine's own
    `runPerson` does all three tabs and SAVES each as it goes -- which is what
    must not happen while somebody is still deciding whether to trust it -- so
    this fills each tab and leaves the Save to the person watching.

    APEX IS NOT A SINGLE-PAGE APP ANY MORE. A probe on 2026-11-11 found no
    Angular on any page, and every tab is an ordinary link: moving between
    them is a FULL PAGE LOAD, which takes the injected script with it. So the
    script goes back in after each move, from here, rather than the page being
    trusted to still hold it.
    """
    # FOUND ON PENDING SETTLES A DISPUTED NAME. They are on that list under
    # the AppStream spelling, which is what was searched for -- so somebody
    # has already put them there under that name and it needs no admin.
    # AppStream's spelling is what gets typed, not the packet's.
    if (who.get("_values") or {}).get("_name_dispute"):
        parts = person.name.split()
        if parts:
            who["_values"]["first"] = parts[0]
            who["_values"]["last"] = " ".join(parts[1:]) or parts[0]
        log("")
        log("  Their packet spells their name differently, but they are on")
        log("  Pending under AppStream's spelling -- so that is the right")
        log("  one and it is what will be typed.")

    log("")
    log("  They are already on Pending, so this is the COMPLETE path:")
    log("  employment record, then user profile, then tax.")
    log("")

    # ALL THREE TABS, through the one walker drive.complete_person -- the same
    # code the unattended week runs. A second copy of the tab walk here is how
    # the two parallel fillers happened, and the whole point of this run is
    # that what gets watched is what will run by itself.
    values = who.get("_values") or {}
    log("  One tab at a time. %s"
        % ("THIS RUN PRESSES SAVE ITSELF." if press_save
           else "Nothing here presses Save -- you do, in Apex."))
    log("")

    # WHY IT WAITS FOR YOUR SAVE, AND NOT FOR A KEYPRESS.
    # Two things were measured on the live site on 2026-11-12:
    #   * Apex raises a confirm() when a tab with unsaved typing is left, and
    #     the only way past it discards the fill (probe_dirty). So filling
    #     all three and saving at the end is not possible -- a tab has to be
    #     saved before the next one opens.
    #   * The earlier version stopped and waited for Return in the terminal.
    #     Megan could not find the terminal, which is the whole
    #     "7-year-old-simple" rule: a step somebody cannot find does not
    #     work.
    # So the run watches for the save itself -- a POST to this employee's
    # URL -- and carries on when it sees one. The person only ever presses
    # Save, in the window they are already looking at.
    def saved(tab: str, got: dict) -> bool:
        if press_save:
            # ARMED (Megan, 2026-11-15: "arm the automatic save"). save_tab
            # refuses on its own if a required box is empty, a value is not
            # what was asked for, or Apex objects -- so this presses Save
            # only on a tab that is already right.
            return drive.save_tab(page, apex_id, got, log=log)
        # A WRONG VALUE STOPS THE RUN. It used to print "WRONG -- DO NOT
        # SAVE" and then, four lines later, "Press SAVE on this tab" -- and
        # Kyle's Rate of Pay went in at $10.10 because the second line is the
        # one that reads like an instruction (2026-11-13). Two contradictory
        # messages are worse than one wrong one: the person follows the one
        # that tells them what to do.
        if got.get("missed"):
            log("")
            log("  *** DO NOT SAVE THIS TAB ***")
            log("  These hold a value that is NOT what was asked for:")
            for k in got["missed"]:
                log("      %s" % k)
            log("")
            log("  Fix them by hand before you save, or close the window and")
            log("  leave the record as it was. Nothing here will press Save.")
            log("")
            return False
        if got.get("absent"):
            log("")
            log("  FILL THESE IN YOURSELF FIRST -- Apex refuses the tab "
                "without them:")
            for k in got["absent"]:
                log("      %s" % k)
        log("")
        log("  >>> Press SAVE on the %s tab in Apex. I am watching for it."
            % tab)
        log("")
        return drive.wait_for_save(page, apex_id, log=log)

    walked = drive.complete_person(page, who, apex_id, values=values,
                                   social=social,
                                   save=saved, log=log, tabs=tabs)
    if not walked:
        log("")
        log("  Nothing was filled on any tab, so there is nothing to save.")
        _hold_open(page, log=log)
        return 1

    log("")
    for tab, _path, _prove in (tabs or drive.TABS):
        got = walked.get(tab)
        if got is None:
            said = "NOT reached"
        elif got.get("saved"):
            said = "filled and saved"
        else:
            said = "FILLED BUT NOT SAVED"
        log("    %-20s %s" % (tab, said))
    # Short = anything not actually saved, not merely anything not reached.
    short = [t for t, _p, _v in (tabs or drive.TABS)
             if not (walked.get(t) or {}).get("saved")]
    if short:
        log("")
        log("  Stopped before: %s. Run this again to carry on." % ", ".join(short))
    else:
        log("")
        log("  All three tabs are in. Check they are Active on the roster.")
    log("")
    _hold_open(page, log=log)
    return 0 if not short else 1


def run(office_key: str, name: str, week_start: dt.date, log=print,
        *, press_save: bool = False, start: dt.date = None,
        gender: str = "") -> int:
    from automations.apex_new_starts import apex as AX

    person = _board_person(office_key, name, week_start, log=log)
    if person is None:
        person = _packet_person(name, week_start, start, log=log)
    if person is None:
        return 1
    if gender:
        # SAID BY THE PERSON RUNNING IT, never inferred. `gender_suggest`
        # returns blank for a name it will not call -- Kimble Townsend,
        # 2026-11-24 -- and `plan` then holds them, which is right for an
        # unattended run and wrong for this one: somebody is sitting here
        # who can simply say. What they say is used as given.
        person = person.__class__(**dict(person.__dict__, gender=gender))
        log("  gender: %s (given on the command line, not guessed)" % gender)

    log("  %s — start %s, %s"
        % (person.name, person.hire_date, person.email or "no email"))

    # The packet. NO SOCIAL: keep_ssn stays off, so there is nothing here that
    # could reach a log, a result or a Google Sheet.
    # keep_ssn=True: the tax tab cannot be saved without it -- see the note
    # at the top of this file.
    hires = BID.for_people([person], keep_ssn=True)
    # ANYTHING TYPED THAT WE DOUBT IS SAID BEFORE IT IS TYPED. A date of
    # birth the employee signed for goes in as they reported it (Megan,
    # 2026-11-23) -- but the person watching should know it cannot be true,
    # because they are the one who can ask.
    for _p, _h in (hires or {}).items():
        for _sem, _why in getattr(_h, "flagged", ()):
            log("  NOTE: %s" % _why)
    # WATCHED: a person is reading every value before it is saved, so a
    # name the gender guesser will not call (Kimble Townsend, 2026-11-24)
    # leaves one dropdown for them instead of holding the whole record.
    got = ECO.plan([person], hires, log=log, office_key=office_key,
                   watched=True)
    if not got["ready"]:
        why = (got["blocked"] or [{}])[0].get("why", "unknown")
        log("  held back: %s" % why)
        log("  Nothing was opened.")
        return 1
    _p, values = got["ready"][0]

    if values.get("_email_was"):
        log("")
        log("  EMAIL: ApplicantStream says %r; their signed packet says %r."
            % (values.get("account_email"), values["_email_was"]))
        log("  Using ApplicantStream's — it is the one we check, and a wrong")
        log("  account email means the sign-in and every password reset go")
        log("  nowhere. Stop here if the packet's is the right one.")
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
               "find": (person.name.split()[-1] if person.name else ""),
               # carried for the profile and tax tabs, which are driven by
               # field NAME rather than by the engine's page map
               "_values": values}
        # THE SOCIAL NEVER RIDES ON `who`. That dict is handed to the page,
        # and Playwright serializes its arguments to JSON -- which is where
        # this crashed, "Object of type Secret is not JSON serializable"
        # (2026-11-13). The wrapper did its job: a plain string would have
        # gone quietly into a page payload. It is passed on its own instead,
        # straight to the one place that types it.
        social = getattr(hires.get(person.name), "ssn", None)
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
        if need.get("need") == drive.ALREADY:
            # SAID OUT LOUD, NOT TREATED AS A FAILURE. Their record is
            # finished; the Pending row that named them is stale. Typing over
            # it is the thing this verdict exists to stop (Alena Guerrero,
            # 2026-11-23, caught on screen by a person).
            log("")
            log("  Their Apex record is already Active and finished.")
            log("  Nothing was opened and nothing was typed.")
            log("")
            return 0
        if need.get("need") == drive.COMPLETE:
            return _complete(s.page, who, person,
                             need.get("id", ""), log=log, social=social,
                             press_save=press_save)
        if (need.get("need") == drive.ADD
                and (values or {}).get("_name_dispute")):
            log("")
            log("  NOT CREATING THEM. %s" % values["_name_dispute"])
            log("")
            log("  They are not on Pending either, so nothing here can tell")
            log("  which spelling is right. An admin has to say, and then")
            log("  this will run.")
            return 1
        if need.get("need") != drive.ADD:
            log("")
            log("  Neither path is safe for them. Creating would make a SECOND")
            log("  payroll record for a real employee, and there is nothing on")
            log("  Pending to complete. Find them on All Employees by hand.")
            log("  Nothing was typed.")
            return 1

        log("  Apex has never heard of them, so this is the create form.")
        # OPENED HERE, not waited for. `triage` has already searched All
        # Employees with real clicks and come back empty -- that IS the
        # duplicate check the ten-minute wait was reserving for a person, and
        # asking them to run it again was asking them to redo work the log
        # above already reports (Megan, 2026-11-24: "why wait 10 min?").
        # The wait stays as the fallback for a roster this cannot press.
        if not drive.press_add_employee(s.page, log=log):
            log("  Opening it by hand instead.")
        if not wait_for_form(s.page, log=log):
            log("  The form never appeared, so nothing was typed.")
            return 1
        log("  Filling.")
        res = ECO.fill_one(person, values, hires.get(person.name), log=log,
                           page=s.page, save=False)
        done = res.get("done") or []
        log("    filled: %s" % (", ".join(done) or "nothing"))
        _readback(res, log=log)
        if res.get("missed"):
            log("    NOT filled: %s" % ", ".join(res["missed"]))
        log("    Apex objects to: %s"
            % (", ".join(res.get("errors") or []) or "nothing"))
        log("    password-reset box: %s"
            % ("TICKED — untick it before saving"
               if res.get("passwordResetTicked") else "off"))
        log("")
        log("  READ THE FORM, THEN PRESS SAVE YOURSELF.")
        log("  Nothing here will press it. I am watching for your Save, and")
        log("  when it lands I carry straight on to the user profile and the")
        log("  tax tab in the same sitting.")
        log("")
        # ONE SITTING FOR A NEW ADD. Pages 2 and 3 live at
        # /employees/<id>/edit/..., and that id DOES NOT EXIST until page 1
        # is saved -- which is why this used to stop here and why re-running
        # afterwards found them Active and refused to touch the record
        # (Luis Frias, 2026-11-24). So the id is read out of the URL the save
        # lands on, and the same walker the COMPLETE path uses finishes the
        # job, minus the employment tab that was just saved.
        if not drive.wait_for_save(s.page, "", log=log):
            log("  No save seen, so the other two tabs were not opened.")
            _hold_open(s.page, log=log)
            return 1
        new_id = _id_in_url(s.page.url)
        if not new_id:
            log("  Saved, but the URL does not name the new record (%s),"
                % s.page.url)
            log("  so I cannot open their profile tab. Run this again and it")
            log("  will find them on the roster.")
            _hold_open(s.page, log=log)
            return 1
        log("")
        log("  Saved — they are record %s. Carrying on to the last two tabs."
            % new_id)
        return _complete(s.page, who, person, new_id, log=log, social=social,
                         press_save=press_save, tabs=drive.TABS[1:])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fill ONE new start into Apex with somebody watching. "
                    "Never saves.")
    ap.add_argument("--office", default="raf", help="office key (default: raf)")
    ap.add_argument("--person", default="", help='"First Last", as the '
                                                 "board spells them")
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week")
    ap.add_argument("--gender", default="",
                    help="Male or Female. Only needed when the name is one "
                         "the guesser will not call -- it refuses to guess, "
                         "because a guess lands on a payroll record.")
    ap.add_argument("--start", default=None,
                    help="YYYY-MM-DD, their first day. Only needed for "
                         "somebody who is not on the board -- a Blue Ink "
                         "packet does not carry a start date.")
    ap.add_argument("--save", action="store_true",
                    help="press Save itself instead of waiting for you. It "
                         "still refuses a tab with a missing or wrong value.")
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
        return run(a.office, a.person, B.week_start_of(day),
                   press_save=a.save, gender=a.gender,
                   start=dt.date.fromisoformat(a.start) if a.start else None)
    except AX.NotLoggedIn as e:
        print("  %s" % e)
        print("")
        print("  Sign in first, then run this again:")
        print("    PYTHONPATH=. .venv/bin/python -m "
              "automations.apex_new_starts.supervised --signin")
        return 1


if __name__ == "__main__":
    sys.exit(main())

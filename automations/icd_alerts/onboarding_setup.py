"""Set this computer up to run its office's ONBOARDING BOARD. Run once, by the ICD.

    python -m automations.icd_alerts.onboarding_setup

Megan, 2026-11-24: *"we need to build an installer now like we have for Lucy
Eco to run on the ICDs machine to fully launch all of these steps on an eco
machine."*

WHAT IT IS FOR. Until now every step of the board ran on OUR machines against
OUR logins -- the reception contacts on Lucy 1, the OBCL seed and the OwnerVille
presses on Lucy 3, Blue Ink on Lucy 2. The destination has never been in doubt
(Megan, 2026-11-23: "I want to move it to the ECO machines once it's all built
out"): a personal login belongs on its owner's computer. This is the one line
that moves the whole set, for one office, in one sitting.

THE SHAPE IS `finish_setup`'S, DELIBERATELY. Every step is skipped when it is
already done and says so, so it is safe to send to somebody who has already
run it -- which is the only way one link can keep working for a year. Nobody
has to work out whether it applies to them.

WHY IT IS A SECOND LINK AND NOT MORE STEPS ON THE FIRST. Megan, 2026-11-13, on
George's install summary: "the main eco installer shouldn't ask for blue ink -
that's for a sterling/bg enrollment anyways". An office that does not do
onboarding should never be asked any of this. So the main ECO installer stays
as it is, and `finish_setup` offers THIS only to a machine that has already
taken on onboarding (a Sterling login on file) -- which is how a later change
here still reaches those offices without a new message to anybody.

IT LEAVES THE BOARD OFF. Setting a machine up and switching it on are two
decisions ([[feedback_onboarding_nothing_live_till_built]]). The last step
reports the switch and does not touch it; `icd_onboarding.eco_job --on` is the
separate, deliberate act, and the summary says so in as many words so nobody
reads a green list as "it is running".

WHAT IT CANNOT CHECK. The board itself lives in a Google Sheet and this
computer has no Google access at all -- everything it writes goes through the
relay. So "is this office's board ready" (ov_program, appstream_id, Rate of
Pay, the workbook) is asked on OUR side by
`icd_onboarding.launch_check --office <key>`, and this installer says so rather
than reporting a green it cannot see.
"""
from __future__ import annotations

import sys
from typing import List, Tuple

from automations.icd_alerts import config as C


def office_key() -> str:
    """The office this machine works, off its own ECO enrolment.

    THE BASE KEY, through the ONE definition of it (`config.base_office_key`).
    A second campaign hangs off the same office and the board belongs to the
    OFFICE. The rule lives in `config` rather than here or in
    `icd_onboarding.run.offices_here` because both need it and only `config`
    can be imported from both: that module reaches OwnerVille and Google
    Sheets through its siblings, and this installer must import on a machine
    that has neither. `test_onboarding_setup` still holds the two to the same
    answer, so a second opinion about whose board this is cannot appear.
    """
    for rec in C.enrollments():
        key = C.base_office_key(rec.get("office_key") or "")
        if key:
            return key
    return ""


def reception_email(rec=None) -> str:
    """The office's own reception Gmail, off this machine's enrolment.

    Megan, 2026-11-11: "each ICD will have their own reception email". On our
    side the answer comes off the second-round roster, which is a Google Sheet
    -- so an office machine cannot look it up, and asking the ICD is both
    cheaper and more reliable than relaying it: they know their own address.
    """
    rec = rec if rec is not None else (C.enrollments() or [{}])[0]
    return str(rec.get("reception_email") or "").strip()


def _this_office(log) -> str:
    key = office_key()
    if not key:
        return "this computer is not enrolled for an office yet"
    log("")
    log("  This computer works the onboarding board for: %s" % key)
    return key


def _relay(log) -> str:
    """The board is a Google Sheet and this machine cannot open one.

    So the relay is not an optimisation here, it is the whole access path:
    without it every step reads nothing and writes nothing, and reads nothing
    looks exactly like an office with nobody on the week
    ([[feedback_empty_means_proven_zero]]). Proven with a real read, not with
    "an enrolment exists" -- a key on file and a script that was never
    deployed answer the same way until something asks it a question.
    """
    key = office_key()
    if not key:
        return "no office on this computer yet"
    try:
        from automations.icd_onboarding import relay_board as RB
    except Exception:       # noqa: BLE001 -- older copy, update failed
        return "not available yet"
    if not RB.available(key):
        return ("skipped -- this computer has no relay enrolment, so it "
                "cannot reach the board")
    import datetime as dt
    from automations.shared.onboarding_week import week_start_of
    try:
        rows = RB.week(key, week_start_of(dt.date.today()))
    except Exception as e:  # noqa: BLE001
        if RB.is_not_deployed(e):
            return ("still needs the relay script re-deployed -- it is "
                    "running an older version that does not know the board")
        return "could not read the board: %s" % str(e)[:140]
    log("  The board answered: %d person/people on this week." % len(rows))
    return "already working"


def _applicantstream(log) -> str:
    """The seed and the no-shows walk both read ApplicantStream.

    Checked through `resume_push`, in the same Chrome the scheduled reads use:
    a sign-in proven in some other browser proves nothing about that one
    (as_signin says the same, for the same reason).
    """
    if not C.appstream_creds():
        return ("still needs the office's AppStream login -- run the main "
                "setup (finish_setup) first, which asks for it")
    try:
        from automations.icd_alerts import resume_push as RP
    except Exception:       # noqa: BLE001
        return "not available yet"
    log("")
    log("  Checking your ApplicantStream sign-in (about a minute).")
    try:
        rc = RP.check_login(log=log)
    except Exception as e:  # noqa: BLE001
        return "could not check it: %s" % _short(e)
    return "already working" if rc == 0 else "still needs signing in"


def _ownerville(log) -> str:
    """Five columns and the Owner Submit press. Reuses the main installer's
    step so there is one definition of what an OwnerVille sign-in is."""
    try:
        from automations.icd_alerts import finish_setup as FS
        return FS._ownerville(log)
    except Exception:       # noqa: BLE001
        return "not available yet"


def _sterling(log) -> str:
    """BG Status, and the invites the admin presses. Its own installer already
    exists and asks for two things only the ICD can give; this never re-asks a
    machine that has them."""
    if C.sterling_creds():
        return "already done"
    return ("still needs the background-check setup -- run "
            "`python -m automations.icd_alerts.sterling_setup`")


def _blueink(log) -> str:
    """The office's OWN Blue Ink account, never Alphalete's: an ICD falling
    back to the repo key sends its new starts' documents out of somebody
    else's account, which is the whole reason each ICD got their own on
    2026-11-09 (launch_check.check_blueink says the same)."""
    try:
        from automations.icd_alerts import blueink_setup as BS
    except Exception:       # noqa: BLE001
        return "nothing to do yet"
    try:
        return BS.run(log=log)
    except Exception as e:  # noqa: BLE001
        return "left for later (%s)" % _short(e)


def _contacts(log) -> str:
    """Contact Added, off this office's OWN reception Google Contacts.

    Megan, 2026-11-11: "each ICD will have their own reception email" -- so
    this is a per-office login like OwnerVille or Blue Ink. It has been running
    on Lucy 1 against Alphalete's reception account, which is the wrong machine
    for every other office: a box without the token skips, and a skip is
    indistinguishable from "nobody has been contacted" unless somebody reads
    the log line.
    """
    key = office_key()
    if not key:
        return "no office on this computer yet"
    try:
        from automations.second_round_contacts import contacts as K
    except Exception:       # noqa: BLE001
        return "not available yet"
    rows = C.enrollments()
    account = reception_email(rows[0] if rows else {})
    if not account:
        try:
            from automations.icd_alerts import dialogs as ask
            account = ask.text(
                "Your office's RECEPTION email -- the Google account your "
                "second-round applicants are saved into as contacts. Lucy "
                "reads it to tick 'Contact Added'; she never changes it."
            ).strip()
        except Exception:   # noqa: BLE001 -- Cancelled, or no dialogs here
            return "skipped -- needs your reception email address"
        if not account or "@" not in account:
            return "skipped -- needs your reception email address"
        rec = dict(rows[0]) if rows else {}
        rec["reception_email"] = account
        if rec.get("office_key"):
            C.add_enrollment(rec)
    if K.has_token(account):
        return "already done"
    try:
        from automations.fiber_owners_distro import contacts_write as CW
    except Exception:       # noqa: BLE001
        return "not available yet"
    if not CW.OAUTH_CLIENT_PATH.exists():
        # NAMED, NOT SKIPPED. This is the one thing here the office cannot
        # provide themselves, and a quiet skip would leave Contact Added blank
        # for ever with nothing on screen saying why.
        return ("still needs the Google sign-in file at %s -- ask the "
                "reporting team to send it to this computer"
                % CW.OAUTH_CLIENT_PATH)
    log("")
    log("  A browser opens on Google's sign-in. Sign in as the address below")
    log("  -- your office's reception account -- and approve the contacts")
    log("  permission. It is read once an hour; nothing is ever changed in it.")
    log("  Sign in as: %s" % account)
    try:
        CW.authorize(account)
    except Exception as e:  # noqa: BLE001
        return "did not finish: %s" % _short(e)
    return "done" if K.has_token(account) else "still needs signing in"


def _apex(log) -> str:
    """New starts into Apex, with this office's own login. Megan, 2026-11-11:
    "apex has to run on the ECO machine since it's that ICDs independent
    login." """
    try:
        from automations.icd_alerts import apex_login as AL
    except Exception:       # noqa: BLE001
        return "not available yet"
    try:
        if AL.creds():
            return "already done"
    except Exception:       # noqa: BLE001 -- unreadable is not saved
        pass
    try:
        from automations.icd_alerts import apex_2fa_setup as A2
    except Exception:       # noqa: BLE001
        return "not available yet"
    log("")
    log("  Setting up your Apex sign-in (payroll records for new starts).")
    try:
        rc = A2.run(log=log)
    except Exception as e:  # noqa: BLE001
        return "did not finish: %s" % _short(e)
    return "done" if rc == 0 else "still needs signing in"


def _the_switch(log) -> str:
    """Last, and it CHANGES NOTHING. Being set up and being switched on are
    two decisions; this one is Megan's, once the whole chain is built."""
    try:
        from automations.icd_onboarding import eco_job as J
    except Exception:       # noqa: BLE001
        return "not available yet"
    if J.switched_on():
        return "ON -- the board runs hourly on this computer"
    return ("ready, switched OFF on purpose (turn it on with "
            "`python -m automations.icd_onboarding.eco_job --on`)")


def _short(e: BaseException) -> str:
    first = (str(e).strip().splitlines() or [""])[0].strip()
    return "%s: %s" % (type(e).__name__, first[:120]) if first \
        else type(e).__name__


# Order matters: the relay is the access path everything else writes through,
# and the three sign-ins come before the things that use them.
STEPS: List[Tuple[str, object]] = [
    ("This office", _this_office),
    ("Board access", _relay),
    ("ApplicantStream sign-in", _applicantstream),
    ("OwnerVille sign-in", _ownerville),
    ("Background checks", _sterling),
    ("Blue Ink account", _blueink),
    ("Reception contacts", _contacts),
    ("Apex sign-in", _apex),
    ("Hourly board run", _the_switch),
]


def run(log=print) -> int:
    log("")
    log("  Setting this computer up to run your onboarding board.")
    log("  Anything already done is skipped -- it is safe to run this")
    log("  whenever you like.")
    log("")

    results = []
    for name, fn in STEPS:
        try:
            results.append((name, fn(log)))
        except Exception as e:  # noqa: BLE001 -- ONE STEP MUST NOT COST THE
            # OTHERS, and the MESSAGE, not just the class: "failed (Error)"
            # told nobody anything (Drew, 2026-10-06).
            log("")
            log("  %s stopped: %s" % (name, str(e).strip() or type(e).__name__))
            results.append((name, "failed -- %s" % _short(e)))

    log("")
    log("  " + "-" * 52)
    for name, said in results:
        log("  %-24s %s" % (name, said))
    log("  " + "-" * 52)
    log("")
    owed = [n for n, s in results
            if "needs" in s or "skipped" in s or "failed" in s
            or "could not" in s or "not available" in s]
    key = office_key()
    if key:
        log("  On the reporting team's side, before this office goes live:")
        log("    python -m automations.icd_onboarding.launch_check --office %s"
            % key)
        log("  (the board's own settings are in a Google Sheet this computer")
        log("   cannot open, so they are checked there, not here.)")
        log("")
    if owed:
        log("  Still to sort: %s." % ", ".join(owed))
        log("  Run this same line again when you can, or send the reporting")
        log("  team this screen.")
        return 1
    log("  This computer is ready. The board is switched OFF until the")
    log("  reporting team turns it on.")
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Set this computer up to run its onboarding board.")
    ap.parse_args(argv)
    return run()


if __name__ == "__main__":
    sys.exit(main())

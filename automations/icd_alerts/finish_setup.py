"""One command that brings a machine fully up to date, whatever it is missing.

Megan, 2026-09-16: "I can't keep going back to all the owners and having them
run a million things."

She is right, and the shape of the problem is this: CODE reaches the machines
by itself -- selfupdate pulls it daily and nobody is asked anything. Anything
the INSTALLER does cannot, because setup.py is not shipped and half of what it
does needs either an administrator password or a person holding an
authenticator. So every such change has meant a new link, a new paste, and
another message to five owners.

THIS IS THE LAST LINK. It is the only one an office should ever be sent, and
it does whatever that machine is missing, today or in a year:

    python -m automations.icd_alerts.finish_setup

  * pulls the newest code first, so the steps below are the current ones
  * installs the boot job, if this Mac still starts only at login
  * takes a new SaraPlus password, if that account has rotated one
  * signs into My Service Cloud, if this office sells Box and the session
    has gone
  * sets up resume pushing, if this office wants Lucy to push from here

EVERY STEP IS SKIPPED WHEN IT IS ALREADY DONE, and says so. A machine that is
fully set up prints four lines and exits -- so it is safe to send to somebody
who has already run it, which is the whole point of having one link. Nobody
has to work out whether it applies to them.

WHEN SOMETHING NEW IS NEEDED, IT GOES HERE. Not a new page, not a new message
to five people: a step added to this function, which the next daily update
carries to every machine. The link on docs/setup.html never changes.
"""
from __future__ import annotations

import sys
from typing import List

from automations.icd_alerts import config as C


def _update(log) -> str:
    """Pull today's code before deciding what is missing.

    FIRST, ALWAYS. The steps below are only as current as the files on the
    machine, and a stale copy would either skip something it does not know
    about or run a version we have since fixed.
    """
    try:
        from automations.icd_alerts import selfupdate
        selfupdate.STAMP.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 — no stamp is the same as a cleared one
        pass
    try:
        from automations.icd_alerts import selfupdate
        selfupdate.run(log=lambda m: None)
        return "up to date"
    except Exception as e:  # noqa: BLE001 — offline is not fatal
        log("  (could not check for updates: %s)" % type(e).__name__)
        return "could not check"


def _boot_job(log) -> str:
    try:
        from automations.icd_alerts import boot_schedule
    except Exception:  # noqa: BLE001 — older copy, update failed
        return "not available yet"
    if boot_schedule.loaded() and boot_schedule.runs_the_right_python():
        boot_schedule.unload_login_agent()
        return "already done"
    if boot_schedule.loaded():
        # LOADED IS NOT WORKING. Khalil's boot job was installed, running
        # every two minutes, and dying every time because it named the system
        # Python that ran the installer instead of the venv. Treating "loaded"
        # as "done" would skip the very repair he ran this for.
        log("")
        log("  The startup job on this computer is pointing at the wrong")
        log("  Python, so it has not been able to run. Reinstalling it.")
    log("")
    log("  This computer only starts the reports once somebody logs in.")
    log("  Letting it start on its own means a restart can't quietly stop")
    log("  your numbers.")
    log("")
    log("  You'll see the normal Mac password box — the Mac handles it,")
    log("  nothing here sees what you type. Skipping is fine.")
    if boot_schedule.install(log=lambda m: log("  " + m.strip())):
        boot_schedule.unload_login_agent()
        return "done"
    return "skipped — someone will need to log in after a restart"


def is_passcode_wall(e) -> bool:
    """SaraPlus's 'confirm this computer' challenge, by its own message: the
    password was accepted and a code is wanted in the agent's browser."""
    return "code it emails" in str(e) or "emailed code" in str(e)


def _saraplus(log) -> str:
    """Only when this machine reads SaraPlus, and only when it cannot.

    WHY THIS IS HERE AT ALL. SaraPlus rotates passwords every few weeks, so
    this is not a setup-time question -- it is the thing an office hits months
    later when their alerts go quiet. Khalil hit it on his first afternoon
    (2026-09-16) and needed a SECOND command pasted after this link, which is
    exactly the "one more thing" this module exists to stop.

    IT ASKS ONLY WHEN THE ANSWER IS NO. Prompting a working office for a
    password is how somebody changes one that was fine -- and our own notes
    record two unnecessary password changes from precisely that.
    """
    try:
        if not C.uses_saraplus():
            return "not needed for this office"
    except Exception:  # noqa: BLE001
        return "not needed for this office"
    try:
        from automations.icd_alerts import run as _run, sara_read
    except Exception:  # noqa: BLE001
        return "not available yet"

    log("")
    log("  Checking your SaraPlus sign-in.")
    try:
        got = sara_read.check_account(headless=True, log=lambda *_a: None)
        if got.get("ok"):
            return "already working"
    except Exception as e:  # noqa: BLE001 — any failure means ASK
        log("  %s" % str(e)[:200])
        if is_passcode_wall(e):
            # THE PASSWORD IS FINE. SaraPlus accepted it and wants an emailed
            # code typed in THIS browser. Asking for the password here had
            # Rashad type his three times on 2026-10-01 and end on "that
            # password did not work either" -- for a password that worked.
            # The one thing that clears it is the window the code goes in.
            from automations.icd_alerts import sara_signin
            return ("done" if sara_signin.run(log=log) == 0
                    else "still needs the emailed code typed in the SaraPlus window")

    log("")
    log("  SaraPlus is not letting this computer in. If you have just set a")
    log("  new password, enter it now and it will be checked for real.")
    return "done" if _run.cmd_set_login(headless=True) == 0 \
        else "still needs a working SaraPlus password"


def _never_sleeps(log) -> str:
    """Sleep off for good, and back ON by itself after a power cut.

    The caffeinate helper only holds while somebody is logged in -- and the
    boot job exists precisely so nobody has to be. Without the real pmset
    setting, a Mac that restarts to the login screen can sleep there, and
    one that loses power stays off (Carlos, 2026-09-30: dark from 11:01 all
    day). One password box covers both. Asked only when the answer is no.
    """
    try:
        from automations.icd_alerts import stay_awake
    except Exception:  # noqa: BLE001 — older copy, update failed
        return "not available yet"
    import platform
    if platform.system() != "Darwin":
        return "not needed on this computer"
    if stay_awake.pmset_ok() and stay_awake.powers_back_on() is not False:
        return "already done"
    log("")
    log("  This computer can still go to sleep, or stay off after a power")
    log("  cut. You will see the normal Mac password box once.")
    if stay_awake.apply_pmset():
        return "done"
    return "skipped — needs the Mac password"


def _service_cloud(log) -> str:
    """Only for the offices that sell through it, and only when it is out."""
    try:
        if not C.uses_servicecloud():
            return "not needed for this office"
    except Exception:  # noqa: BLE001
        return "not needed for this office"
    try:
        from automations.icd_alerts import box_signin
    except Exception:  # noqa: BLE001
        return "not available yet"
    log("")
    log("  Checking your My Service Cloud sign-in.")
    return "done" if box_signin.run(log=log) == 0 else "still needs signing in"


def _resume_push(log) -> str:
    """Resume pushing from this computer (Carlos 2026-10-05). Asked ONCE per
    machine; a NO is remembered, a YES gets its login, sign-in and Resume
    Helper checked every time this runs."""
    try:
        from automations.icd_alerts import resume_push as RP
        from automations.icd_alerts import dialogs as ask
    except Exception:  # noqa: BLE001 — older copy, update failed
        return "not available yet"
    rows = C.enrollments()
    if not rows:
        return "not needed for this office"
    if not RP.push_record():
        if all(r.get("push_resumes") is False for r in rows):
            return "not wanted"
        try:
            yes = ask.choose(
                "Do you want Lucy to push your resumes (send applicants to "
                "the AI call list) from this computer?",
                ["Yes, push my resumes from this computer", "No"]
            ).startswith("Yes")
        except ask.Cancelled:
            return "skipped"
        for r in rows:
            r["push_resumes"] = yes if r is rows[0] else False
            C.add_enrollment(r)
        if not yes:
            return "not wanted"
    if not C.appstream_creds():
        try:
            user = ask.text("Your AppStream username (type it exactly, "
                            "spaces and all):").strip()
            pwd = ask.password("Your AppStream password:")
        except ask.Cancelled:
            return "skipped — needs your AppStream login"
        if not (user and pwd):
            return "skipped — needs your AppStream login"
        C.save_appstream_creds(user, pwd)
    log("")
    log("  Checking your AppStream sign-in (about a minute).")
    if RP.check_login(log=log) != 0:
        return "still needs signing in"
    if not RP.extension_installed():
        log("")
        log("  Lucy's Chrome needs the Resume Helper extension once.")
        log("  Click 'Add to Chrome' in the window that opens.")
        if not RP.setup_extension(log=log):
            return "still needs Resume Helper added"
    return "done"


def run(log=print) -> int:
    log("")
    log("  Getting this computer fully set up. Anything already done is")
    log("  skipped — it is safe to run this whenever you like.")
    log("")

    steps: List = [("Latest version", _update),
                   ("Starts on its own", _boot_job),
                   ("Never sleeps", _never_sleeps),
                   ("SaraPlus sign-in", _saraplus),
                   ("Box sales sign-in", _service_cloud),
                   ("Resume pushing", _resume_push)]
    results = []
    for name, fn in steps:
        try:
            results.append((name, fn(log)))
        except Exception as e:  # noqa: BLE001 — ONE STEP MUST NOT COST THE
            # OTHERS. A machine that needs two things fixed and gets one
            # would look fixed, and the second would be found the slow way.
            results.append((name, "failed (%s)" % type(e).__name__))

    log("")
    log("  " + "-" * 44)
    for name, said in results:
        log("  %-22s %s" % (name, said))
    log("  " + "-" * 44)
    log("")
    if any("needs" in s or "skipped" in s or "failed" in s
           for _n, s in results):
        log("  Something above still needs doing — run this again when you")
        log("  can, or send the reporting team this screen.")
        return 1
    log("  All set. Nothing else to do.")
    return 0


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())

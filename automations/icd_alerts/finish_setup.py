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
  * signs into My Service Cloud, if this office sells Box and the session
    has gone

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
    if boot_schedule.loaded():
        boot_schedule.unload_login_agent()
        return "already done"
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


def run(log=print) -> int:
    log("")
    log("  Getting this computer fully set up. Anything already done is")
    log("  skipped — it is safe to run this whenever you like.")
    log("")

    steps: List = [("Latest version", _update),
                   ("Starts on its own", _boot_job),
                   ("Box sales sign-in", _service_cloud)]
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

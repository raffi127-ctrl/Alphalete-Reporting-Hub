"""Turn a sign-up into a real office. The only step Megan has to take.

    python -m automations.icd_signup.approve            # who is waiting
    python -m automations.icd_signup.approve cyrus      # enrol them
    python -m automations.icd_signup.approve cyrus --decline --note "..."

NOTHING EXISTS UNTIL THIS RUNS. A sign-up is a request on a tab: no key, no
roster entry, no push. That is deliberate -- an abandoned form leaves nothing
to clean up, and an office cannot enrol itself into our reporting.

Approving reads what they told us on the form and hands it straight to
icd_alerts.enroll, which mints the key, writes both roster files, pushes, and
prints the link to send them. Their answers are used as given: the whole point
of asking them first is that we stop guessing hours and re-asking for them.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from automations.icd_signup import store
from automations.icd_signup.schema import (IcdSignup, STATUS_APPROVED,
                                           STATUS_DECLINED, STATUS_PENDING)


def show_waiting(log=print) -> int:
    waiting = store.pending()
    if not waiting:
        log("Nobody is waiting to be enrolled.")
        return 0
    log("")
    log("Waiting to be enrolled:")
    log("")
    for s in waiting:
        sat = ("Sat %s-%s" % (s.sat_start, s.sat_end) if s.saturday
               else "no Saturday")
        log("  %-10s %-22s %s  ·  M-F %s-%s · %s"
            % (s.office_key, s.owner,
               "Mac" if s.platform == "mac" else "Windows",
               s.day_start, s.day_end, sat))
        log("             submitted %s · %s" % (s.submitted_at, s.contact))
    log("")
    log("Enrol one with:  python -m automations.icd_signup.approve <office>")
    log("")
    return 0


def approve(office_key: str, *, do_push: bool = True, log=print) -> int:
    from automations.icd_alerts import enroll as E

    rec = store.get(office_key)
    if not rec:
        log("No sign-up for %r. Waiting ones:" % office_key)
        return show_waiting(log=log) or 1
    if rec.status == STATUS_APPROVED:
        log("%s was already approved. To re-send their link:" % office_key)
        log("  python -m automations.icd_alerts.invite %s" % office_key)
        return 1

    log("Enrolling %s (%s) from their sign-up." % (rec.owner, rec.office_key))
    rc = E.enroll(
        rec.owner,
        office=rec.office_key,
        tz=rec.timezone or "America/Chicago",
        day=(rec.day_start, rec.day_end),
        sat=(rec.sat_start, rec.sat_end) if rec.saturday else E.DEFAULT_SAT,
        saturday=rec.saturday,
        platform=rec.platform or "mac",
        label=rec.office_label or None,
        # THEIRS, not a default -- they told us on the form, which is the
        # entire reason for asking them first.
        hours_known=True,
        do_push=do_push,
        log=log,
    )
    if rc != 0:
        log("Enrolment did not finish, so the sign-up is left PENDING.")
        return rc
    store.set_status(rec.office_key, STATUS_APPROVED,
                     note="enrolled %s" % rec.submitted_at)
    if rec.contact:
        log("  Send that link to: %s" % rec.contact)
    if rec.knocks_cadence == -1:
        log("  They said they do NOT want a knocks board.")
    log("")
    return 0


def decline(office_key: str, note: str = "", log=print) -> int:
    rec = store.get(office_key)
    if not rec:
        log("No sign-up for %r." % office_key)
        return 1
    store.set_status(office_key, STATUS_DECLINED, note=note)
    log("%s marked declined. Nothing was created, so there is nothing to undo."
        % office_key)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Approve an ICD's sign-up")
    ap.add_argument("office", nargs="?", help="office key from the alert")
    ap.add_argument("--decline", action="store_true")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-push", action="store_true",
                    help="write everything but do not push (their install "
                         "cannot work until you do)")
    a = ap.parse_args(argv)
    if not a.office:
        return show_waiting()
    if a.decline:
        return decline(a.office, a.note)
    return approve(a.office, do_push=not a.no_push)


if __name__ == "__main__":
    sys.exit(main())

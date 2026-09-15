"""Turn a sign-up into posts. The only step Megan has to take.

    python -m automations.icd_signup.approve            # who is waiting
    python -m automations.icd_signup.approve cyrus      # switch them on
    python -m automations.icd_signup.approve cyrus --decline --note "..."

WHAT APPROVAL MEANS NOW. It used to mean "create this office" -- mint the key,
write the roster, push. It no longer does, because Megan asked for the office
to be installed and waiting before she looks (2026-09-13: "their machine is set
up so that when I approve it's good to go"). The key is theirs at sign-up and
the roster comes off the sheet, so by the time you read the alert their laptop
may already be relaying.

So approval is now the thing it always should have been: WHERE THEIR NUMBERS
POST. Until you run this they can install, and relay, and nothing they send
reaches a Slack channel -- an office with nothing approved is HELD, not
dropped. That is the gate, and it is the only one that matters, because it is
the only one whose failure is visible to somebody else's team.
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
    rec = store.get(office_key)
    if not rec:
        log("No sign-up for %r. Waiting ones:" % office_key)
        return show_waiting(log=log) or 1
    if rec.status == STATUS_APPROVED:
        log("%s is already approved." % office_key)
        return 1

    from automations.icd_alerts import approve as channels
    from automations.icd_signup.schema import uses_saraplus

    log("Switching on %s (%s)." % (rec.owner, rec.office_key))
    # A KNOCKS-ONLY OFFICE HAS NO ALERT CHANNEL TO APPROVE. Box, Energy Wells
    # and NDS are not on SaraPlus, so demanding one would block an approval
    # over a channel that was never asked for.
    if not uses_saraplus(rec.campaign):
        log("  %s campaign — no credit checks or sales, so no alert channel."
            % rec.campaign)
        rc = 0
    else:
        # THE GATE: the channels they asked for. icd_alerts.approve resolves
        # the room, checks Lucy is in it, and writes the sign-off.
        rc = channels.cmd_approve(rec.office_key, None)
    if rc != 0:
        log("")
        log("Their channel was not approved, so nothing posts yet and the "
            "sign-up stays PENDING.")
        return rc
    if rec.knocks_cadence != -1:
        log("")
        log("Now their knocks board:")
        channels.cmd_knocks(rec.office_key)
    else:
        log("  They said they do not want a knocks board.")

    # THE TEXT DESTINATION IS ADDITIONAL, so it is approved separately and a
    # problem with it must not un-approve the Slack half that already worked
    # (Megan 2026-09-15: "not instead- this is in addition to").
    if rec.text_groups:
        log("")
        log("They also asked to be texted:")
        channels.cmd_texts(rec.office_key)

    store.set_status(rec.office_key, STATUS_APPROVED,
                     note="approved %s" % rec.submitted_at)
    # BUST THE ROSTER CACHE. offices.sheet_offices() holds its read for ten
    # minutes so the poster is not doing a Sheets round trip every two, but
    # the moment somebody approves an office is exactly when that staleness
    # is felt as "I approved them and nothing happened".
    try:
        from automations.icd_alerts import offices as O
        O.SHEET_CACHE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 — it expires on its own anyway
        pass
    log("")
    log("%s is live. Their numbers start appearing within a few minutes of "
        "their laptop's next check-in." % rec.owner)
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

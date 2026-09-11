"""The ICD-side agent: check the account, or run one credit-check sweep.

  python -m automations.icd_alerts.run --set-login          # save the login
  python -m automations.icd_alerts.run --check              # step one: is this
                                                            # account usable?
  python -m automations.icd_alerts.run --once --dry-run     # read + show what
                                                            # WOULD be alerted
  python -m automations.icd_alerts.run --once               # read + record

DRY RUN IS THE DEFAULT for --once until the relay exists. Nothing in this file
posts to Slack and nothing sends: the laptop's whole job is to read its own
office and hand the numbers over. Wiring the relay is the next piece, and
keeping it out of this one means an ICD can prove their account works today
without anything leaving their machine.

--headful is the debugging escape hatch: SaraPlus can challenge a new browser
with an emailed passcode, and watching that happen once beats guessing at it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.icd_alerts import config as C
from automations.icd_alerts import sara_read, state as St


def _log(msg: str) -> None:
    print("[icd_alerts] %s" % msg, flush=True)


def _alert_lines(gained, totals):
    """The line an owner actually sees, worded exactly as the AO one is:
    ':mag: Ana Griffin just ran 1 credit check (6 today).'

    Built here rather than on our side purely so --dry-run can show the owner
    the real thing. The SENT version is composed centrally, because the wording
    has to be changeable without reaching 52 laptops.
    """
    from automations.shared.credit_check_line import records_line
    return [records_line(rep, int(totals.get(rep, 0)), int(up))
            for rep, up in sorted(gained.items())]


def cmd_set_login() -> int:
    import getpass
    print("Enter the SaraPlus login for THIS office.")
    print("It is saved on this computer only and is never sent to anyone.\n")
    email = input("SaraPlus email: ").strip()
    if not email:
        print("Nothing entered; nothing saved.")
        return 1
    password = getpass.getpass("SaraPlus password: ")
    if not password:
        print("Nothing entered; nothing saved.")
        return 1
    path = C.save_creds(email, password)
    print("\nSaved to %s" % path)
    print("Now run:  python -m automations.icd_alerts.run --check")
    return 0


def cmd_check(headless: bool) -> int:
    try:
        result = sara_read.check_account(headless=headless, log=_log)
    except sara_read.AccountProblem as e:
        print("\n%s" % e)
        return 1
    except RuntimeError as e:          # config.creds() speaks plain English too
        print("\n%s" % e)
        return 1
    print("\n%s" % result["message"])
    if not result["ok"]:
        print("(signed in, but landed on %s)" % result["landed"])
    return 0 if result["ok"] else 1


def cmd_once(headless: bool, dry_run: bool, day: dt.date) -> int:
    try:
        current = sara_read.read_records(day, headless=headless, log=_log)
    except sara_read.AccountProblem as e:
        print("\n%s" % e)
        return 1
    except RuntimeError as e:
        print("\n%s" % e)
        return 1

    data = St.load()
    baseline = St.is_baseline(data, day)
    gained = St.deltas(data, day, current)

    if baseline:
        _log("first sweep for %s -- recording the day, sending nothing. "
             "(%d rep(s) already have credit checks today.)"
             % (day.isoformat(), len(current)))
    else:
        _log("new since the last sweep: %d rep(s)" % len(gained))
        for line in _alert_lines(gained, current):
            print("  %s" % line)

    if dry_run:
        _log("dry run -- state not updated, nothing relayed.")
        return 0

    St.save(St.remember(data, day, current))
    _log("state updated (%s)" % C.STATE_PATH)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ICD credit-check alerts agent")
    ap.add_argument("--set-login", action="store_true",
                    help="save this office's SaraPlus login on this computer")
    ap.add_argument("--check", action="store_true",
                    help="step one: confirm this account can read reports")
    ap.add_argument("--once", action="store_true",
                    help="run one sweep")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --once: read and show, change nothing")
    ap.add_argument("--headful", action="store_true",
                    help="show the browser (for watching a passcode challenge)")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today, local)")
    args = ap.parse_args(argv)

    day = dt.date.fromisoformat(args.day) if args.day else C.today()
    headless = not args.headful

    if args.set_login:
        return cmd_set_login()
    if args.check:
        return cmd_check(headless)
    if args.once:
        return cmd_once(headless, args.dry_run, day)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

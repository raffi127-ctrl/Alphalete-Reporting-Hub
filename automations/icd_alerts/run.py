"""The ICD-side agent: check the account, or run one credit-check sweep.

  python -m automations.icd_alerts.run --set-login          # save the login
  python -m automations.icd_alerts.run --check              # step one: is this
                                                            # account usable?
  python -m automations.icd_alerts.run --once --dry-run     # read + show what
                                                            # WOULD be alerted
  python -m automations.icd_alerts.run --once               # read + record

NOTHING HERE POSTS TO SLACK. The laptop reads its own office and hands the
totals over; we decide what is new and what gets said. So the local state below
powers the PREVIEW only -- it is not what stops a duplicate alert. That job
belongs to `post.decide` on our side, where losing a laptop's state file, or
restoring one from a backup, cannot cause anyone to be pinged twice.

--dry-run reads and shows without sending anything anywhere, which is how an
ICD checks the thing works before it is switched on.

--headful is the debugging escape hatch: SaraPlus can challenge a new browser
with an emailed passcode, and watching that happen once beats guessing at it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.icd_alerts import config as C
from automations.icd_alerts import ov_read, relay as R, sara_read, state as St


def _log(msg: str) -> None:
    print("[icd_alerts] %s" % msg, flush=True)


def _alert_lines(gained, totals):
    """A PREVIEW of the line the office will see, worded exactly as the real
    one is: ':mag: Ana Griffin just ran 1 credit check (6 today).'

    Shown here only so an owner running --dry-run sees the real thing. What is
    actually posted is composed on our side from the same shared function, so
    the wording can change without reaching 52 laptops.
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
        read = sara_read.read_day(day, headless=headless, log=_log)
        current, sales = read["records"], read["sales"]
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
        _log("first run today -- %d rep(s) already have credit checks. "
             "Nothing is announced for a day we have not seen before."
             % len(current))
    else:
        lines = _alert_lines(gained, current)
        _log("new since the last run: %d rep(s)" % len(lines))
        for line in lines:
            print("  %s" % line)

    # The real work. Totals go over; what gets SAID is decided on our side.
    try:
        R.send(current, day, sales=sales, dry_run=dry_run, log=_log)
    except R.RelayError as e:
        # Not fatal and not the owner's problem to solve: SaraPlus is
        # cumulative, so the next run hands over the whole day again.
        _log("could not send this time: %s" % e)
        return 1

    if dry_run:
        _log("dry run -- nothing sent, nothing recorded.")
        return 0

    St.save(St.remember(data, day, current))
    return 0


def cmd_knocks(headless: bool, dry_run: bool, day: dt.date) -> int:
    """Hand over today's disposition rows. Quiet when no OwnerVille login is
    saved: the knocks board is optional, and an office that never gave us one
    has not failed at anything."""
    if not C.OV_CREDS_PATH.exists():
        _log("no OwnerVille login saved — skipping knocks")
        return 0
    try:
        payload = ov_read.read_knocks(day, headless=headless, log=_log)
        rows, tracker = payload["rows"], payload["time_tracker"]
    except ov_read.KnocksProblem as e:
        print("\n%s" % e)
        return 1
    except RuntimeError as e:
        print("\n%s" % e)
        return 1

    if not rows:
        # A real answer. Nobody has knocked yet today, and an empty grid is
        # what that looks like -- it is not a failed read, and reporting it as
        # one would cry wolf every morning.
        _log("no knocks logged yet today")

    try:
        R.send_knocks(rows, day, time_tracker=tracker, dry_run=dry_run, log=_log)
    except R.RelayError as e:
        _log("could not send the knocks this time: %s" % e)
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ICD credit-check alerts agent")
    ap.add_argument("--set-login", action="store_true",
                    help="save this office's SaraPlus login on this computer")
    ap.add_argument("--check", action="store_true",
                    help="step one: confirm this account can read reports")
    ap.add_argument("--once", action="store_true",
                    help="run one sweep: credit checks, then knocks")
    ap.add_argument("--knocks", action="store_true",
                    help="hand over today's knocks only")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --once: read and show, change nothing")
    ap.add_argument("--headful", action="store_true",
                    help="show the browser (for watching a passcode challenge)")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today, local)")
    ap.add_argument("--if-due", action="store_true",
                    help="with --once: do nothing outside selling hours. This "
                         "is what the scheduled run uses, so the schedule can "
                         "stay simple and the decision lives in one place.")
    args = ap.parse_args(argv)

    day = dt.date.fromisoformat(args.day) if args.day else C.today()
    headless = not args.headful

    if args.set_login:
        return cmd_set_login()
    if args.check:
        return cmd_check(headless)
    if args.knocks:
        return cmd_knocks(headless, args.dry_run, day)
    if args.once:
        if args.if_due and not C.in_selling_window():
            # Quiet on purpose. This fires every 15 minutes on somebody's
            # laptop; a line per skip would be the only thing in the log.
            return 0
        # BOTH, INDEPENDENTLY. SaraPlus and OwnerVille are different systems
        # with different outages, and a credit-check sweep that worked must not
        # be thrown away because OwnerVille was slow -- nor the reverse. Each
        # reports its own failure and the run ends unhappy if either did.
        rc = cmd_once(headless, args.dry_run, day)
        rk = cmd_knocks(headless, args.dry_run, day)
        return rc or rk
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

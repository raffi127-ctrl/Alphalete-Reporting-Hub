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
import traceback
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


def cmd_set_login(headless: bool = True) -> int:
    """Take a new SaraPlus password and PROVE it works before saying so.

    SARAPLUS ROTATES PASSWORDS OFTEN (Megan 2026-09-12), so this is not a
    setup-only path -- it is the thing an owner runs months later, on their
    own, when their alerts have gone quiet. It therefore asks in a dialog like
    the installer does, and it verifies: "saved" on a password that does not
    work is the same silence they already had, except now they think it is
    fixed.
    """
    from automations.icd_alerts import dialogs as ask

    try:
        current = C.creds().get("email", "")
    except RuntimeError:
        current = ""

    for attempt in (1, 2, 3):
        try:
            email = ask.text(
                "Your SaraPlus email:%s" % ("\n\n(currently %s)" % current
                                            if current else "")).strip()
            if not email:
                email = current
            password = ask.password("Your NEW SaraPlus password:")
        except ask.Cancelled:
            print("Nothing was changed.")
            return 1
        if not email or not password:
            print("Nothing entered; nothing changed.")
            return 1

        C.save_creds(email, password)
        _log("checking it against SaraPlus...")
        try:
            result = sara_read.check_account(headless=headless, log=_log,
                                         interactive=True)
            ok = result.get("ok")
        except sara_read.AccountProblem as e:
            ok, result = False, {"message": str(e)}
        except RuntimeError as e:
            ok, result = False, {"message": str(e)}

        if ok:
            ask.message("That worked — your alerts will start again within a "
                        "few minutes.\n\nNothing else to do.")
            print("OK")
            return 0
        if attempt == 3:
            break
        try:
            again = ask.choose(
                "%s\n\nTry again?" % result.get("message", "It did not work."),
                ["Yes, let me retype it", "No, I'll sort it out later"])
        except ask.Cancelled:
            return 1
        if not again.startswith("Yes"):
            return 1

    ask.message("That password did not work either.\n\nPlease DM Megan & Eve "
                "— it may be that your SaraPlus account needs looking at from "
                "their end.", error=True)
    return 1


def cmd_check(headless: bool) -> int:
    try:
        result = sara_read.check_account(headless=headless, log=_log,
                                         interactive=True)
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


def _report(stage: str, e: Exception, detail: str = "") -> None:
    """Tell us what broke here. Never makes the failure worse.

    NOT FOR A RelayError. When the relay itself is what failed, reporting to
    the relay is a second failed call and tells nobody anything -- the quiet
    nudge already covers "this laptop stopped talking to us".
    """
    if isinstance(e, R.RelayError):
        return
    R.report_fault(stage, "%s: %s" % (type(e).__name__, str(e)[:200]),
                   detail or traceback.format_exc(), log=_log)


def cmd_once(headless: bool, dry_run: bool, day: dt.date) -> int:
    # FIRST, AND ONCE A DAY. Getting a fix onto an office's machine used to
    # mean messaging a person and hoping they pasted a line -- which is how
    # Kash ran a whole day on the first agent with no sales at all. The files
    # replaced here are used by the NEXT run, not this one: the modules for
    # this sweep are already imported, and swapping code under a running
    # process is a much worse idea than waiting three minutes.
    if not dry_run:
        try:
            from automations.icd_alerts import selfupdate
            selfupdate.run(log=_log, today=day)
        except Exception as e:  # noqa: BLE001 — never lose a sweep to this
            _log("self-update skipped: %s" % type(e).__name__)

    # SARAPLUS IS ONE ACCOUNT PER MACHINE, not one per campaign: AT&T is the
    # only campaign on it, so a machine has at most ONE enrollment that reads
    # it. Find that one and relay under its key; if there is none, this half
    # of the agent is not this office's at all.
    att = next((r for r in C.enrollments()
                if str(r.get("campaign") or "att").lower()
                not in ("nds", "energy", "b2b_box")), None)
    if att is None and C.enrollments():
        _log("no AT&T campaign on this machine — knocks only")
        return 0
    att_key = str((att or {}).get("office_key") or "")

    try:
        read = sara_read.read_day(day, headless=headless, log=_log)
        current, sales = read["records"], read["sales"]
    except sara_read.AccountProblem as e:
        print("\n%s" % e)
        _report("sweep", e)
        return 1
    except RuntimeError as e:
        print("\n%s" % e)
        _report("sweep", e)
        return 1
    except Exception as e:  # noqa: BLE001
        # THE ONE THAT USED TO VANISH. An unexpected crash printed a traceback
        # into a log file on a laptop in another state and told us nothing at
        # all; the office simply went quiet and we guessed. Now the traceback
        # comes to us.
        _log("unexpected failure: %s" % traceback.format_exc())
        _report("sweep", e)
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
        R.send(current, day, sales=sales, dry_run=dry_run,
               office_key=att_key, log=_log)
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
    """Hand over today's disposition rows, ONE READ PER ENROLLED CAMPAIGN.

    An office that runs two campaigns enrolled twice on this machine, and each
    campaign is its own reporting unit -- its own relay key, its own channels,
    its own board. So each gets its own pinned read.

    QUIET ONLY WHERE QUIET IS HONEST. A missing OwnerVille login is a skipped
    extra for an AT&T office, whose credit checks and sales carry on without
    it. For a Box, Energy Wells or NDS office the board is the ENTIRE product,
    so the same missing file means this machine can never report anything --
    and logging that to a file on their desk is how it stays unnoticed. Carlos
    was installed without an OwnerVille login on 2026-09-15 and his machine
    would have ticked every two minutes, said this to nobody, and relayed
    nothing for as long as it took someone to ask.

    ONE CAMPAIGN FAILING DOES NOT COST THE OTHERS. They are separate reads of
    separate grids; a pin that will not take on one says nothing about the
    other, and losing both would turn a half-outage into a whole one.
    """
    if not C.OV_CREDS_PATH.exists():
        _log("no OwnerVille login saved — skipping knocks")
        if not C.uses_saraplus():
            # Nothing else on this machine reports anything, so this is an
            # outage, not a skipped extra. report_fault de-duplicates by
            # (office, stage, summary), so this is one row and one Slack
            # thread however many ticks run before somebody fixes it.
            _report("knocks", RuntimeError(
                "no OwnerVille login is saved on this computer, and this "
                "office has no SaraPlus — so nothing can be read or reported "
                "at all. The install needs to be run again."))
        return 0

    rows_of = C.enrollments() or [{}]
    worst = 0
    for rec in rows_of:
        key = str(rec.get("office_key") or "")
        campaign = str(rec.get("campaign") or "att")
        if len(rows_of) > 1:
            _log("--- %s (%s) ---" % (key or "this office", campaign))
        try:
            payload = ov_read.read_knocks(day, headless=headless,
                                          campaign=campaign, log=_log)
            rows, tracker = payload["rows"], payload["time_tracker"]
        except ov_read.KnocksProblem as e:
            print("\n%s" % e)
            _report("knocks", e)
            worst = 1
            continue
        except RuntimeError as e:
            print("\n%s" % e)
            _report("knocks", e)
            worst = 1
            continue
        except Exception as e:  # noqa: BLE001 — see cmd_once
            _log("unexpected failure: %s" % traceback.format_exc())
            _report("knocks", e)
            worst = 1
            continue

        if not rows:
            # A real answer. Nobody has knocked yet today, and an empty grid
            # is what that looks like -- not a failed read, and reporting it
            # as one would cry wolf every morning.
            _log("no knocks logged yet today")

        try:
            R.send_knocks(rows, day, time_tracker=tracker, dry_run=dry_run,
                          office_key=key, log=_log)
        except R.RelayError as e:
            _log("could not send the knocks this time: %s" % e)
            worst = 1
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ICD credit-check alerts agent")
    ap.add_argument("--set-login", action="store_true",
                    help="change the saved SaraPlus password, and check it")
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
        return cmd_set_login(headless)
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

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
from automations.icd_alerts import watchdog as W
from automations.icd_alerts import (box_read, closeout, ov_read, relay as R,
                                    sara_read, state as St)


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
            # The sweep may be standing back after the refusals; a person
            # just fixed it, so the next tick must try, not sit out the hold.
            sara_read.clear_sara_hold()
            ask.message("That worked — your alerts will start again within a "
                        "few minutes.\n\nNothing else to do.")
            print("OK")
            return 0
        if "code it emails" in str(result.get("message", "")):
            # NOT A PASSWORD PROBLEM, so do not ask for it again (Rashad,
            # 2026-10-01: three retypes of a working password). Open the
            # browser the code has to be typed in; it verifies before
            # saying done.
            from automations.icd_alerts import sara_signin
            ask.message("Your password is fine — SaraPlus just wants to "
                        "confirm this computer with a code it emailed you.\n\n"
                        "A SaraPlus window will open next: sign in there and "
                        "type that code.")
            if sara_signin.run(log=_log) == 0:
                sara_read.clear_sara_hold()
                print("OK")
                return 0
            return 1
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


def cmd_set_ownerville_login() -> int:
    """Take the OwnerVille login in a box and PROVE it with a real knocks read.

    Twice at most, not three times like SaraPlus: every wrong try here is one
    more strike toward OwnerVille locking the account, and the box only ever
    appears because the saved one already failed.
    """
    from automations.icd_alerts import dialogs as ask

    try:
        current = C.ownerville_creds().get("username", "")
    except RuntimeError:
        current = ""

    for attempt in (1, 2):
        try:
            user = ask.text(
                "Lucy can't sign in to OwnerVille.\n\nYour OwnerVille "
                "username:%s" % ("\n\n(currently %s -- leave blank to keep it)"
                                 % current if current else "")).strip()
            user = user or current
            password = ask.password("Your OwnerVille password:")
        except ask.Cancelled:
            print("Nothing was changed.")
            return 1
        if not user or not password:
            print("Nothing entered; nothing changed.")
            return 1

        C.save_ownerville_creds(user, password)     # also clears the hold
        _log("checking it against OwnerVille (about a minute)...")
        try:
            C.OV_SIGNIN_LOCK.write_text(dt.datetime.now().isoformat())
        except OSError:
            pass
        try:
            ov_read.read_knocks(C.today(), log=_log)
            ok, why = True, ""
        except Exception as e:  # noqa: BLE001
            ok, why = False, str(e)
        finally:
            try:
                C.OV_SIGNIN_LOCK.unlink()
            except OSError:
                pass
        if ok:
            ask.message("That worked -- your knocks board will start again "
                        "within a few minutes.\n\nNothing else to do.")
            print("OK")
            return 0
        # LOCKED IS NOT A WRONG PASSWORD. Jenny (Figspire) 2026-10-13 typed
        # hers twice into this box and got "that did not work either": the
        # account was locked, so no password could have worked, and asking
        # her to retype it only told her the password was the problem.
        if ov_read.held_on_lock():
            ask.message(
                "OwnerVille has LOCKED this account (too many failed "
                "sign-ins). Your password is not the problem -- typing it "
                "again will not help.\n\nEmail onboarding@ownerville.com and "
                "ask them to unlock %s. Lucy notices the unlock by herself; "
                "nothing else to do.\n\nQuestions: DM Megan & Eve." % user,
                error=True)
            return 1
        if attempt == 2:
            break
        # THE PASSWORD IS SAVED; RETYPING IT IS NOT THE FIX. Steve McElwee
        # (2026-10-21) typed his three times into this box and each proof
        # landed back on the login page with no session -- a first-login
        # prompt, a security check, a username that is not the email: the
        # agent cannot tell, a person at the window can. So the second
        # chance is the window, not the box (same as SaraPlus / Service
        # Cloud): sign in by hand once in Lucy's browser and the session
        # lives there; the sweep never types the password again.
        try:
            ask.message(
                "OwnerVille did not open a session with that, but the login "
                "is saved.\n\nNext, Lucy's own browser will open on "
                "OwnerVille: sign in there by hand once, the same way you do "
                "anywhere else. That is all she needs.")
        except ask.Cancelled:
            return 1
        from automations.icd_alerts import ov_signin
        if ov_signin.run(log=_log) == 0:
            ask.message("That worked -- your knocks board will start again "
                        "within a few minutes.\n\nNothing else to do.")
            return 0
        ask.message("Nobody signed in, so nothing has changed. Run this again "
                    "when you have a minute at the computer, or DM Megan & "
                    "Eve.", error=True)
        return 1
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


def _report(stage: str, e: Exception, detail: str = "",
            office_key: str = "") -> None:
    """Tell us what broke here. Never makes the failure worse.

    NOT FOR A RelayError. When the relay itself is what failed, reporting to
    the relay is a second failed call and tells nobody anything -- the quiet
    nudge already covers "this laptop stopped talking to us".

    NAME THE OFFICE. A machine can hold two campaigns, and without a key the
    relay files the fault against whichever enrolled first -- which put a
    SaraPlus failure on Carlos's Box office (2026-09-16).
    """
    if isinstance(e, R.RelayError):
        return
    # Only a REAL traceback. The watchdog files a slow read from a `finally`
    # with nothing raised, and format_exc() then returns "NoneType: None" --
    # which went into Kash's thread as if it were an error (2026-09-21).
    live = sys.exc_info()[0] is not None
    R.report_fault(stage, "%s: %s" % (type(e).__name__, str(e)[:200]),
                   detail or (traceback.format_exc() if live else ""),
                   log=_log, office_key=office_key)


def _is_code_wall(e: Exception) -> bool:
    """True when SaraPlus took the password but wants its emailed code."""
    wall = getattr(sara_read.S, "SaraPasscodeWall", None)
    cause = getattr(e, "__cause__", None)
    if wall is not None and isinstance(cause, wall):
        return True
    return "code it emails" in str(e)


# cmd_once's answer when the overnight catch-up had no session to resume and
# was told not to log in: sales_closeout leaves the day owed on this code.
CATCHUP_DEFERRED = 3


_EMPTY_READ_STAMP = C.APP_DIR / "sweep-empty-reported.txt"


def _applied_release() -> str:
    try:
        from automations.icd_alerts import selfupdate
        return selfupdate.applied_release()
    except Exception:  # noqa: BLE001
        return ""


def _empty_read_due() -> bool:
    """Once an hour -- or right away on a new release: the fault folds on
    its summary anyway, this just keeps the evidence from being re-sent
    every sweep. A release that changes WHAT the evidence says must not
    wait out the hour (Steve 2026-10-21: the fuller grid dump was the
    whole point of the update)."""
    release = _applied_release()
    try:
        stamp, _, seen = _EMPTY_READ_STAMP.read_text().strip().partition("|")
        last = dt.datetime.fromisoformat(stamp)
        if (dt.datetime.now() - last < dt.timedelta(hours=1)
                and seen == release):
            return False
    except (OSError, ValueError):
        pass
    try:
        _EMPTY_READ_STAMP.parent.mkdir(parents=True, exist_ok=True)
        _EMPTY_READ_STAMP.write_text(
            dt.datetime.now().isoformat(timespec="seconds") + "|" + release)
    except OSError:
        pass
    return True


def cmd_once(headless: bool, dry_run: bool, day: dt.date,
             sales_only: bool = False, resume_only: bool = False) -> int:
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
    # ONE LIST, NOT A SECOND COPY OF IT. This spelled the exclusions out
    # inline, so moving NDS onto SaraPlus in config.py would have left this
    # still skipping it -- the office asked for a login, saved it, and the
    # sweep quietly never used it.
    att = next((r for r in C.active_enrollments()
                if str(r.get("campaign") or "att").strip().lower()
                not in C.NO_SARAPLUS), None)
    if att is None and C.enrollments():
        _log("no SaraPlus campaign on this machine — sales come from elsewhere")
        return 0
    att_key = str((att or {}).get("office_key") or "")

    held = sara_read.sara_held_until()
    if held is not None:
        # Refused recently. The fault is already reported; another attempt
        # now is another poke at a throttled login page. See hold_sara.
        _log("SaraPlus refused this login at the last try; holding off "
             "until %s" % held.strftime("%H:%M"))
        return 0

    try:
        # TIMED AND BOUNDED. A read that hangs holds the two-minute slot and
        # every tick behind it, which is what an office experiences as
        # "she's super delay today" -- Roshan, 2026-09-18, twice in one day
        # with no fault either time because nothing had failed, it was still
        # working. Abandoning it costs one gap; holding the slot costs the
        # afternoon, and the numbers are cumulative so nothing is lost.
        read = W.timed("sweep",
                       lambda: sara_read.read_day(day, headless=headless,
                                                  log=_log,
                                                  resume_only=resume_only),
                       log=_log, report=_report, office_key=att_key)
        current, sales = read["records"], read["sales"]
        # Wireless credit checks, offices on the three alerts only; None when
        # this office is not one of them or the pass was not read.
        credit = read.get("credit")
        # NDS line counts off the same grid; None leaves NL as read.
        lines = read.get("lines")
        # AN EMPTY GRID DURING SELLING HOURS IS A FAULT WITH EVIDENCE, once an
        # hour, not a quiet day of zeros (Steve McElwee 2026-10-21).
        if (read.get("empty_evidence") and not sales_only
                and C.in_selling_window() and _empty_read_due()):
            _report("sweep-empty", RuntimeError(
                "the credit-check read passed but came back with 0 reps while "
                "the office is selling -- what the grid showed is in the detail"),
                office_key=att_key, detail=read["empty_evidence"])
    except sara_read.SessionLost as e:
        # THE OVERNIGHT CATCH-UP FOUND NO SESSION. Not a fault and not a
        # login: a headless login now is the emailed-code wall at 2am with
        # nobody there (every office's wall of 10/7-10/8 landed 2-4am). The
        # catch-up stays owed and runs on the first sweep of the day.
        _log("catch-up deferred: %s -- not logging in headless at this hour" % e)
        return CATCHUP_DEFERRED
    except sara_read.SignInInProgress:
        # Somebody is at the keyboard finishing a sign-in. Send NOTHING: an
        # empty read relayed here is a day of zeros written over the real
        # one. Same as cmd_box.
        return 0
    except W.SweepTimeout:
        # ALREADY REPORTED, with the duration and why it was dropped. Falling
        # through would file it a second time as an unexpected crash.
        return 1
    except sara_read.AccountProblem as e:
        print("\n%s" % e)
        # THE EMAILED-CODE WALL IS A SIGN-IN, not a laptop fault. Filed as
        # "sweep" it went to the corrections room saying "the office was not
        # asked to send anything" -- and the one person who could clear it was
        # never told (Eveliz, 2026-10-03..06). As signin-saraplus the poster
        # DMs the owner, their helpers, Megan & Eve, once a day.
        stage = "signin-saraplus" if _is_code_wall(e) else "sweep"
        # THE CODE CAN COME FROM LUCY NOW (2026-10-29). Before anybody is
        # told, a detached helper asks Lucy 1 for the emailed code and types
        # it in itself; only if that cannot finish does it file this same
        # fault and offer the window -- the old path, minutes later. Once per
        # RETRY_AFTER_MINUTES, so an office with no forward set up costs one
        # short detour, not one per sweep.
        if stage == "signin-saraplus":
            try:
                from automations.icd_alerts import sara_code
                if not sara_code.recently_tried() and sara_code.launch(att_key, log=_log):
                    sara_read.hold_sara(log=_log)
                    return 1
            except Exception:  # noqa: BLE001 — never cost the fault report
                pass
        # WITH THE NIGHT'S EVIDENCE: how old the session was and what the
        # keep-alive did, so the wall tells idle-expiry from a hard lifetime.
        # EVIDENCE FIRST: the relay keeps 1500 characters of detail and the
        # traceback alone fills them (Luke's 02:00 wall of 10/9 arrived with
        # the evidence cut off). The traceback's tail is the least useful part.
        _report(stage, e, office_key=att_key,
                detail=("read: sales_only=%s resume_only=%s selling_window=%s "
                        "sales_window=%s\n" % (sales_only, resume_only,
                                                C.in_selling_window(),
                                                C.in_sales_window()))
                       + sara_read.session_evidence() + "\n\n"
                       + traceback.format_exc())
        sara_read.hold_sara(log=_log)
        # SAME AS THE BOX PATH, and for the SAME reason. Khalil's machine hit
        # SaraPlus's passcode wall 115 times on 2026-09-17 -- five hours of
        # every-two-minutes failing while people traded screenshots about a
        # password that was never wrong. Whoever is at the Mac gets the window
        # that can actually clear it.
        try:
            from automations.icd_alerts import autoprompt
            # A REFUSED PASSWORD GETS THE PASSWORD BOX; a wall or a bounce
            # gets the sign-in window. Offering the window for a wrong saved
            # password had Francia sign in twice while the sweep stayed
            # refused (Khalil, 2026-09-22/23).
            which = "saraplus_password" if "did not accept" in str(e) else "saraplus"
            autoprompt.offer(which, log=_log)
        except Exception:  # noqa: BLE001 — never cost the fault report
            pass
        return 1
    except RuntimeError as e:
        print("\n%s" % e)
        _report("sweep", e, office_key=att_key)
        return 1
    except Exception as e:  # noqa: BLE001
        # THE ONE THAT USED TO VANISH. An unexpected crash printed a traceback
        # into a log file on a laptop in another state and told us nothing at
        # all; the office simply went quiet and we guessed. Now the traceback
        # comes to us.
        _log("unexpected failure: %s" % traceback.format_exc())
        _report("sweep", e, office_key=att_key)
        return 1

    data = St.load()
    if sales_only:
        # OUTSIDE THE ALERT HOURS the sales still go over, but the credit
        # checks sent are the ones already seen today — so our side has
        # nothing new to announce at 11pm or on a Sunday (Megan 2026-09-22:
        # the extended hours are for the sales boards).
        current = dict(data.get(day.isoformat()) or {})
        try:
            R.send(current, day, sales=sales, dry_run=dry_run,
                   office_key=att_key, log=_log, credit=credit, lines=lines)
        except R.RelayError as e:
            _log("could not send this time: %s" % e)
            return 1
        return 0
    baseline = St.is_baseline(data, day)
    gained = St.deltas(data, day, current)

    if baseline:
        _log("first run today -- %d rep(s) already have credit checks. "
             "Nothing is announced for a day we have not seen before."
             % len(current))
    else:
        # NOT `lines`: that name is the NDS line counts going to R.send below.
        # Reusing it handed the relay this list of strings, and every NDS
        # office crashed on its send -- silently -- from 2026-10-23 11:38.
        said = _alert_lines(gained, current)
        _log("new since the last run: %d rep(s)" % len(said))
        for line in said:
            print("  %s" % line)

    # The real work. Totals go over; what gets SAID is decided on our side.
    try:
        R.send(current, day, sales=sales, dry_run=dry_run,
               office_key=att_key, log=_log, credit=credit, lines=lines)
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


def _box_key(boxes) -> str:
    """The office key a Service Cloud fault belongs to. One key when there is
    one Box campaign, which is every office so far; blank if somehow two, so
    the relay falls back rather than blaming the wrong one."""
    keys = [str(r.get("office_key") or "") for r in (boxes or [])]
    return keys[0] if len(keys) == 1 else ""


def cmd_box(headless: bool, dry_run: bool, day: dt.date) -> int:
    """Hand over today's Box sales, read from My Service Cloud.

    THE HALF THAT EXISTED AND NEVER RAN. box_read was written, tested and
    shipped in the package on 2026-09-15 and nothing called it -- so a Box
    office's agent ticked all day, reported success, and relayed no sales at
    all. Its own knocks board kept filling, which is what would have made it
    look fine.

    ONE READ PER SERVICE CLOUD ENROLLMENT. Like SaraPlus this is one signed-in
    session per machine, but unlike SaraPlus a machine could hold two Box
    campaigns, so each relays under its own key off the one read.

    A LOST SESSION IS ITS OWN FAULT, not a sweep failure. It is the one thing
    here that needs a person to walk to that computer, and it is reported as
    such so the DM that asks them to goes out instead of a generic "something
    broke on the laptop".
    """
    if not C.uses_servicecloud():
        return 0
    boxes = [r for r in C.active_enrollments()
             if str(r.get("campaign") or "att").strip().lower()
             in C.SERVICECLOUD_CAMPAIGNS]
    if not boxes:
        return 0

    try:
        read = W.timed("box",
                       lambda: box_read.read_day(day, headless=headless,
                                                 log=_log),
                       log=_log, report=_report, office_key=_box_key(boxes))
    except box_read.SignInInProgress:
        # Somebody is at that keyboard finishing a sign-in. Not a failure,
        # and reporting it would alert on the exact minute they are doing
        # what we asked them to.
        return 0
    except W.SweepTimeout:
        return 1
    except box_read.SignInNeeded as e:
        print("\n%s" % e)
        # The stage names the SYSTEM. post.notify_faults reads it to send the
        # sign-in DM -- to the owner, Megan and Eve -- rather than posting a
        # laptop fault nobody can act on.
        _report("signin-servicecloud", e, office_key=_box_key(boxes))
        # AND PUT THE WINDOW ON THEIR SCREEN, if anybody is there to use it.
        # The DM is the fallback for an empty office, not the plan: Ryan lost
        # 3.5 hours on 2026-09-16 and Carlos over 5, and both machines knew
        # within two minutes. Everything after detection was people finding a
        # message, opening a link and pasting a command.
        try:
            from automations.icd_alerts import autoprompt
            autoprompt.offer("servicecloud", log=_log)
        except Exception:  # noqa: BLE001 — never cost the fault report
            pass
        return 1
    except box_read.AccountProblem as e:
        print("\n%s" % e)
        _report("box", e, office_key=_box_key(boxes))
        return 1
    except RuntimeError as e:
        print("\n%s" % e)
        _report("box", e, office_key=_box_key(boxes))
        return 1
    except Exception as e:  # noqa: BLE001 — see cmd_once
        _log("unexpected failure: %s" % traceback.format_exc())
        _report("box", e, office_key=_box_key(boxes))
        return 1

    if read.get("unknown"):
        # NOT FATAL, BUT NOT SILENT. Box adding a substatus we have no rule
        # for would otherwise drop those contracts out of every Box number
        # with nothing to show for it.
        _report("box", RuntimeError(
            "My Service Cloud has substatuses nobody has ruled on: %s. Sales "
            "in them are being counted as nothing until somebody says what "
            "they are." % ", ".join(read["unknown"])),
                office_key=_box_key(boxes))

    worst = 0
    for rec in boxes:
        key = str(rec.get("office_key") or "")
        if len(boxes) > 1:
            _log("--- %s ---" % (key or "this office"))
        try:
            R.send(read["records"], day, sales=read["sales"], dry_run=dry_run,
                   office_key=key, log=_log)
        except R.RelayError as e:
            # Not fatal: the window is re-read every sweep, so the next one
            # hands over the whole of it again.
            _log("could not send the sales this time: %s" % e)
            worst = 1
    return worst


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
        else:
            # NOT SILENT EITHER (Omar 2026-10-28): his OwnerVille login was
            # cleared to get past a stuck check, the sign-in window said
            # "Signed in", and every sweep after it skipped knocks with only
            # this log line to show for it -- an hour of "did it relay yet?"
            # that one fault row would have answered. De-duplicated by its
            # summary, so it is one row however many sweeps run.
            _report("knocks", RuntimeError(
                "no OwnerVille login is saved on this computer, so the knocks "
                "board cannot run (credit-check and sales alerts still do). "
                "Save it with: python -m automations.icd_alerts.run "
                "--set-ownerville-login"))
        return 0

    try:
        started = dt.datetime.fromisoformat(C.OV_SIGNIN_LOCK.read_text().strip())
        if dt.datetime.now() - started < dt.timedelta(minutes=5):
            _log("the OwnerVille password box is checking a new login — "
                 "skipping knocks this time")
            return 0
    except (OSError, ValueError):
        pass

    if C.enrollments() and not C.active_enrollments():
        _log("every campaign on this machine is paused -- no knocks read")
        return 0
    rows_of = C.active_enrollments() or [{}]
    worst = 0
    for rec in rows_of:
        key = str(rec.get("office_key") or "")
        campaign = str(rec.get("campaign") or "att")
        if len(rows_of) > 1:
            _log("--- %s (%s) ---" % (key or "this office", campaign))
        try:
            payload = W.timed(
                "knocks",
                lambda: ov_read.read_knocks(day, headless=headless,
                                            campaign=campaign, log=_log),
                log=_log, report=_report, office_key=key)
            rows, tracker = payload["rows"], payload["time_tracker"]
        except W.SweepTimeout:
            worst = 1
            continue
        except ov_read.KnocksProblem as e:
            print("\n%s" % e)
            # EVIDENCE FIRST. The relay trims the detail, and a traceback is
            # long enough to push the page's URL, title and text off the end
            # (Jamis 2026-10-06: the first evidence row stopped at "page
            # url: ...p=89&"). The traceback is the same every time; the
            # evidence is the part nobody has seen.
            seen = getattr(e, "seen", "")
            _report("knocks", e, office_key=key,
                    detail=(seen + "\n\n" + traceback.format_exc())
                    if seen else "")
            # Signing in is on hold for something only a person can fix:
            # put the password box in front of whoever is at the Mac.
            try:
                if ov_read.needs_password_box():
                    from automations.icd_alerts import autoprompt
                    # The WINDOW, not the box: a saved password that does
                    # not open a session is fixed by a person signing in
                    # once in Lucy's browser (Steve, 2026-10-21).
                    if ov_read.held_on_lock() or not autoprompt.offer("ownerville", log=_log):
                        autoprompt.offer("ownerville_password", log=_log)
            except Exception:  # noqa: BLE001 — never cost the fault report
                pass
            worst = 1
            continue
        except RuntimeError as e:
            print("\n%s" % e)
            _report("knocks", e, office_key=key)
            worst = 1
            continue
        except Exception as e:  # noqa: BLE001 — see cmd_once
            _log("unexpected failure: %s" % traceback.format_exc())
            _report("knocks", e, office_key=key)
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
    """_main, with a crash that nothing below caught REPORTED before it ends.

    2026-10-23: a TypeError at the send killed every NDS office's run from
    11:38 to 20:30 -- no relay, no fault, nothing but a traceback in a log on
    a laptop nobody can reach. The offices looked switched off; the owners
    were told to wake computers that were awake. A scheduled run that dies
    now says so first.
    """
    try:
        return _main(argv)
    except W.SweepTimeout:
        raise                           # already reported where it fired
    except Exception as e:  # noqa: BLE001 — reported, then re-raised
        _log("unexpected failure: %s" % traceback.format_exc())
        try:
            _report("crash", e)
        except Exception:  # noqa: BLE001 — reporting must not mask the crash
            pass
        raise


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ICD credit-check alerts agent")
    ap.add_argument("--set-login", action="store_true",
                    help="change the saved SaraPlus password, and check it")
    ap.add_argument("--ownerville-signin", action="store_true",
                    help="open OwnerVille in Lucy's browser so you sign in by "
                         "hand once; the session then lives in that profile")
    ap.add_argument("--set-ownerville-login", action="store_true",
                    help="change the saved OwnerVille login, and check it")
    ap.add_argument("--check", action="store_true",
                    help="step one: confirm this account can read reports")
    ap.add_argument("--once", action="store_true",
                    help="run one sweep: credit checks, then knocks")
    ap.add_argument("--knocks", action="store_true",
                    help="hand over today's knocks only")
    ap.add_argument("--box", action="store_true",
                    help="hand over today's My Service Cloud sales only")
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

    # THE SCHEDULED RUNS GET A HARD CEILING, the interactive ones do not: a
    # --set-login or --check has a person waiting on a window. See
    # watchdog.arm_hard_ceiling -- a run that never exits silences the office.
    if (args.once or args.knocks or args.box) and not args.dry_run:
        W.arm_hard_ceiling(log=_log, report=_report)

    if args.set_login:
        return cmd_set_login(headless)
    if args.ownerville_signin:
        from automations.icd_alerts import ov_signin
        return ov_signin.run(log=_log)
    if args.set_ownerville_login:
        return cmd_set_ownerville_login()
    if args.check:
        return cmd_check(headless)
    if args.knocks:
        return cmd_knocks(headless, args.dry_run, day)
    if args.box:
        return cmd_box(headless, args.dry_run, day)
    if args.once:
        # YESTERDAY FIRST, AND BEFORE THE GATE BELOW -- which is the whole
        # point. The selling window starts at 10:00 local, and the metrics
        # thread reads this office's knocks at about 06:50 Central, so
        # anything that waits for the window is already too late to be the
        # number people see. Once the local date has flipped, the previous day
        # is finished and OwnerVille has its real total no matter when this
        # machine stopped relaying.
        #
        # Cheap when there is nothing owed: a small JSON read, no browser.
        try:
            closeout.maybe_run(
                lambda d: cmd_knocks(headless, args.dry_run, d), log=_log)
        except Exception as e:  # noqa: BLE001 — never lose a sweep to this
            _log("close-out skipped: %s" % type(e).__name__)

        # THE 2AM SALES CATCH-UP, also ahead of the gate: past 2am the
        # previous day is finished, so its sales are read once more and that
        # day's row overwritten with the final numbers (Megan 2026-09-22).
        try:
            from automations.icd_alerts import sales_closeout
            sales_closeout.maybe_run(
                lambda d: (cmd_once(headless, args.dry_run, d, sales_only=True,
                                    resume_only=True)
                           or cmd_box(headless, args.dry_run, d)),
                log=_log)
        except Exception as e:  # noqa: BLE001 — never lose a sweep to this
            _log("sales catch-up skipped: %s" % type(e).__name__)

        # RESUME PUSHING, for an office that asked for it. Its own hours
        # (7am-10pm, every day) and its own process, so it goes ahead of the
        # gate and never holds up a sweep (Carlos 2026-10-05).
        try:
            from automations.icd_alerts import resume_push
            resume_push.maybe_kick(log=_log)
        except Exception as e:  # noqa: BLE001 — never lose a sweep to this
            _log("resume push skipped: %s" % type(e).__name__)

        # HEADSHOTS, for an office Lucy 3 has queued any for. Ahead of the
        # gate for the same reason as the push: they keep office hours, not
        # selling hours. Asks the relay at most every 10 minutes.
        try:
            from automations.icd_alerts import headshot_jobs
            headshot_jobs.maybe_run(log=_log)
        except Exception as e:  # noqa: BLE001 — never lose a sweep to this
            _log("headshots skipped: %s" % type(e).__name__)

        # THE OWNER'S PNL, for an office that asked for it. Office hours, its
        # own state file; today only the one-time DD check (see pnl.py).
        try:
            from automations.icd_alerts import pnl
            pnl.maybe_run(log=_log)
        except Exception as e:  # noqa: BLE001 — never lose a sweep to this
            _log("pnl skipped: %s" % type(e).__name__)

        # CAN THIS MAC READ THE OWNER'S SARAPLUS TEXTS? Once a day, read-only,
        # counts only -- for the offices whose codes come by SMS (Eveliz,
        # 2026-10-29). See messages_probe.py.
        try:
            from automations.icd_alerts import messages_probe
            messages_probe.maybe_run(log=_log)
        except Exception as e:  # noqa: BLE001 — never lose a sweep to this
            _log("messages check skipped: %s" % type(e).__name__)

        alerting = C.in_selling_window()
        # Sales read noon to midnight every day; alerts keep their own hours.
        # Outside BOTH, nothing to do.
        if args.if_due and not (alerting or C.in_sales_window()):
            # Quiet on purpose. This fires every 15 minutes on somebody's
            # laptop; a line per skip would be the only thing in the log.
            # EXCEPT THE SARAPLUS SESSION, which must not idle out overnight:
            # an expired one means a fresh login at the 2am close-out, and on
            # some accounts every fresh login is an emailed-code wall
            # (Eveliz, 2026-10-06). See sara_read.keep_session_alive.
            if not args.dry_run and not sara_read.sara_held_until():
                try:
                    did = sara_read.keep_session_alive(headless=headless,
                                                       log=_log)
                    if did in ("kept", "lost"):
                        _log("SaraPlus keep-alive: %s" % did)
                except Exception:  # noqa: BLE001 — never lose a tick to this
                    pass
            return 0
        sales_only = bool(args.if_due and not alerting)
        # OUTSIDE THE ALERT WINDOW, NEVER TYPE THE PASSWORD. Nobody is at the
        # Mac to clear the emailed-code wall a fresh headless login earns, so
        # an evening or overnight read only resumes the session it has; a lost
        # one waits for the first in-window sweep, when the wall opens in
        # front of a person (Luke's 02:00 PT wall of 10/9 came through this
        # path on release 2026.10.08.2, not the catch-up).
        resume_only = sales_only
        # BOTH, INDEPENDENTLY. SaraPlus and OwnerVille are different systems
        # with different outages, and a credit-check sweep that worked must not
        # be thrown away because OwnerVille was slow -- nor the reverse. Each
        # reports its own failure and the run ends unhappy if either did.
        # THREE SYSTEMS, INDEPENDENTLY. SaraPlus, My Service Cloud and
        # OwnerVille have different outages, and a read that worked must not
        # be thrown away because another was slow. Each reports its own
        # failure and the run ends unhappy if any did.
        rc = cmd_once(headless, args.dry_run, day, sales_only=sales_only,
                      resume_only=resume_only)
        if rc == CATCHUP_DEFERRED:
            rc = 0          # nothing read, nothing wrong: not a failed tick
        rb = cmd_box(headless, args.dry_run, day)
        # Knocks keep the selling window; the knocks close-out above delivers
        # the finished day either way.
        rk = 0 if sales_only else cmd_knocks(headless, args.dry_run, day)
        return rc or rb or rk
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

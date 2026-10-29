"""Clear SaraPlus's emailed-code screen by itself, with the code from Lucy 1.

WHY (Eve/Megan, 2026-10-29). Eveliz, Luke, Rashad and Tre are asked for a code
on every fresh SaraPlus login, and SaraPlus ends the session every 2-4 days.
Until today that meant a dark office and a DM until somebody typed the code
into Lucy's window. The owner now forwards SaraPlus's code mails to the
reporting inbox, and this does the typing:

  hidden browser, THE SWEEP'S OWN PROFILE -> sign in -> code screen
  -> choose Email, Get Code -> ask Lucy 1 for it (relay.request_code)
  -> wait for the answer (relay.poll_code) -> type it -> signed in.

The hidden browser clearing the screen itself is the point: it is the browser
the sweeps use, so the trust lands where it is needed -- the sign-in window's
whole difficulty (a visible window trusted, the hidden read still asked) does
not arise.

DETACHED, AND HOLDING THE SIGN-IN LOCK. run.py launches this and returns at
once; the wait is minutes and a sweep has a five-minute deadline. The lock is
the one the sign-in window takes, so sweeps stand back while this works.

IF IT CANNOT, NOTHING IS LOST. No forward set up ("none"), an old relay, no
answer within CODE_WAIT_SECONDS, or a code SaraPlus refuses: it files the same
`signin-saraplus` fault the sweep used to file at once, and offers the sign-in
window -- exactly the path every office had before, a few minutes later.

    python -m automations.icd_alerts.sara_code
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Optional

from automations.icd_alerts import config as C

CODE_WAIT_SECONDS = 9 * 60      # Gmail forwarding adds minutes some days
POLL_SECONDS = 15
# Fewer than rc_contact_sync's 3: each attempt is a fresh code and a fresh
# request, and a screen that refuses two good codes will refuse a third.
ATTEMPTS = 2

# NOT EVERY WALL. A machine that cannot clear the screen (no forward set up)
# must not try on every sweep: once, then the DM path, until this has passed.
RETRY_AFTER_MINUTES = 45
# The whole run, login to signed in: inside the 15-minute sign-in lock.
RUN_DEADLINE_SECONDS = (C.SARA_SIGNIN_LOCK_MINUTES - 1) * 60
STAMP_PATH = C.APP_DIR / "sara-code-tried.txt"


class NoCode(RuntimeError):
    """Lucy 1 has no code for us, and will not have one."""


def recently_tried(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    try:
        when = dt.datetime.fromisoformat(STAMP_PATH.read_text().strip())
    except (OSError, ValueError):
        return False
    return now - when < dt.timedelta(minutes=RETRY_AFTER_MINUTES)


def _stamp() -> None:
    try:
        STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        STAMP_PATH.write_text(dt.datetime.now().isoformat(timespec="seconds"))
    except OSError:
        pass


def code_from_relay(since: dt.datetime, *, office_key: str = "",
                    wait_s: int = CODE_WAIT_SECONDS, poll_s: int = POLL_SECONDS,
                    sleep=time.sleep, clock=time.time, log=print) -> str:
    """Ask Lucy 1 for the code mailed after `since`, and wait for it."""
    from automations.icd_alerts import relay as R

    if not R.request_code(since, office_key=office_key):
        raise NoCode("could not file the code request with the relay")
    log("  asked Lucy for the code (requested %s)" % since.strftime("%H:%M:%S"))
    deadline = clock() + wait_s
    while True:
        sleep(poll_s)
        got = R.poll_code(since, office_key=office_key)
        status = got.get("status")
        if status == R.CODE_READY and got.get("code"):
            log("  code received")
            return got["code"]
        if status == R.CODE_NONE:
            raise NoCode("no SaraPlus code forward is set up for this office")
        if status == R.CODE_UNSUPPORTED:
            raise NoCode("the relay cannot hand out codes yet (%s)"
                         % (got.get("error") or "old relay"))
        if clock() >= deadline:
            raise NoCode("no code reached Lucy within %d minutes" % (wait_s // 60))


def _attempt(office_key: str = "", log=print) -> str:
    """Sign in, clear the code screen, return the dealer root. Raises."""
    from patchright.sync_api import sync_playwright

    from automations.icd_alerts import sara_read as SR
    from automations.shared import sara_passcode as SP
    from automations.shared import saraplus as S

    cr = C.creds()
    with sync_playwright() as p:
        ctx = SR._context(p, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                return S._login(page, cr["email"], cr["password"],
                                creds_hint="the SaraPlus login saved on this computer",
                                log=log)
            except S.SaraPasscodeWall:
                log("  SaraPlus wants its emailed code -- getting it from Lucy")
            SP.verify_browser(
                page, lambda since: code_from_relay(since, office_key=office_key, log=log),
                attempts=ATTEMPTS, log=log)
            url = page.url
            for marker in ("DealerPages/", "Reports/"):
                if marker in url:
                    # LET SARAPLUS FINISH writing whatever it keeps for a
                    # trusted browser before the profile is closed.
                    page.wait_for_timeout(10_000)
                    return url.split(marker)[0]
            raise SP.PasscodeError("verified, but landed on %s" % url)
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def _fall_back(why: str, office_key: str = "", log=print) -> None:
    """The path every office had before: the fault (-> DM) and the window."""
    from automations.icd_alerts import relay as R
    R.report_fault(
        "signin-saraplus",
        "AccountProblem: SaraPlus wants to confirm this computer with a code "
        "it emails you. Your password is fine — do NOT change it.",
        detail="automatic code entry did not finish: %s" % why,
        log=log, office_key=office_key)
    try:
        from automations.icd_alerts import autoprompt
        autoprompt.offer("saraplus", log=log)
    except Exception:  # noqa: BLE001
        pass


def _tell_upstream(verdict: str, office_key: str = "") -> None:
    try:
        from automations.icd_alerts import relay as R
        try:
            from automations.icd_alerts import selfupdate as SU
            release = SU.applied_release() or "?"
        except Exception:  # noqa: BLE001
            release = "?"
        R.report_fault("probe-sara-code",
                       "SaraPlus code entry %s (release %s): %s"
                       % (dt.datetime.now().strftime("%H:%M"), release, verdict),
                       office_key=office_key)
    except Exception:  # noqa: BLE001
        pass


def run(office_key: str = "", log=print, attempt=None) -> int:
    from automations.icd_alerts import sara_read as SR

    if SR.signin_in_progress():
        log("a SaraPlus sign-in is already going on this computer")
        return 0
    _stamp()
    C.SARA_SIGNIN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        C.SARA_SIGNIN_LOCK.write_text(dt.datetime.now().isoformat())
    except OSError:
        pass
    from automations.icd_alerts import watchdog as W
    try:
        # UNDER THE SIGN-IN LOCK'S OWN LIFETIME: past it the sweeps stop
        # standing back, and two browsers on one profile is the one outcome
        # worse than waiting.
        with W._Deadline(RUN_DEADLINE_SECONDS, log=log):
            base = (attempt or _attempt)(office_key=office_key, log=log)
    except (Exception, W.SweepTimeout) as e:  # noqa: BLE001 -- every failure is the old path
        why = "%s: %s" % (type(e).__name__, str(e)[:300])
        log("  could not clear the code screen by itself: %s" % why)
        _release_lock()
        _tell_upstream("fell back -- %s" % why, office_key)
        _fall_back(why, office_key, log=log)
        return 1
    _release_lock()
    SR._remember_session(base)
    SR.clear_sara_hold()
    _tell_upstream("done -- signed in by itself", office_key)
    log("  SaraPlus signed in by itself; sales start again on the next sweep")
    return 0


def _release_lock() -> None:
    try:
        C.SARA_SIGNIN_LOCK.unlink()
    except OSError:
        pass


def launch(office_key: str = "", log=print) -> bool:
    """Start run() detached, the way autoprompt starts its windows."""
    import subprocess

    from automations.icd_alerts import boot_schedule as B
    root = B.app_root()
    if not root:
        return False
    args = [str(B.venv_python(root)), "-m", "automations.icd_alerts.sara_code"]
    if office_key:
        args += ["--office", office_key]
    try:
        # INTO THE AGENT'S OWN LOG, so what it did is on the machine to read.
        out = open(str(C.LOG_PATH), "a")
    except OSError:
        out = subprocess.DEVNULL
    try:
        subprocess.Popen(args, cwd=str(root), start_new_session=True,
                         stdout=out, stderr=subprocess.STDOUT)
    except Exception as e:  # noqa: BLE001
        log("could not start automatic code entry: %s" % type(e).__name__)
        return False
    log("started automatic SaraPlus code entry")
    return True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    office = ""
    if "--office" in argv:
        i = argv.index("--office")
        office = argv[i + 1] if i + 1 < len(argv) else ""
    return run(office_key=office,
               log=lambda m: print("[sara_code] %s" % m, flush=True))


if __name__ == "__main__":
    sys.exit(main())

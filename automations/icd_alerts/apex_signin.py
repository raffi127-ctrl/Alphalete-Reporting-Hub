"""Open Apex in LUCY'S OWN browser so the owner signs in there once, by hand.

WHY (the PNL, Eve + Megan 2026-10-29). The owner's PNL needs what each rep
got paid, and that lives in their Apex payroll. Lucy reads it the way Lucy 2
reads Carlos's (carlos_payroll_pull): an Apex session the owner signed into
himself, in a Chrome profile kept for it. No password is saved or typed by
Lucy -- the same rule as box_signin / ov_signin, and for the same reason: a
session in their everyday browser is invisible to her.

    python -m automations.icd_alerts.apex_signin      # what autoprompt opens

Read-only: posts nothing, relays nothing. It waits for the session, proves it
the way the PNL will use it (Payroll Entry shows a pay period), and closes.
The payroll itself stays on this computer.
"""
from __future__ import annotations

import datetime as dt
import sys
import os
import time

from automations.icd_alerts import config as C

APEX_PROFILE_DIR = C.APP_DIR / "chrome-profile-apex"
# The PNL check stands back while this is open: Chromium will not open one
# profile twice, and somebody mid-2-step code must not lose the race.
APEX_SIGNIN_LOCK = C.APP_DIR / "apex-signin.lock"
APEX_SIGNIN_LOCK_MINUTES = 10

WAIT_SECONDS = 300
POLL_SECONDS = 4

BANNER = "LUCY NEEDS YOU TO SIGN INTO APEX -- ONLY ONCE"
BANNER_DETAIL = ("Sign in here the way you always do, with your 2-step code if "
                 "it asks. This window closes by itself when it is done.")


def mark_open() -> None:
    """Say a window is up: when, and WHICH process holds it. Raises OSError."""
    APEX_SIGNIN_LOCK.write_text("%s %d" % (dt.datetime.now().isoformat(),
                                           os.getpid()))


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":      # os.kill(pid, 0) on Windows is a Ctrl+C, not a look
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def signin_open(now=None) -> bool:
    """A sign-in window is up. With the holder's pid on file: as long as that
    process lives, however long (Jairo's finish window sat an hour+ on a box
    on 2026-11-25 and the next window crashed into its profile twice). Old
    lock without a pid: the ten-minute rule."""
    try:
        parts = APEX_SIGNIN_LOCK.read_text().split()
        was = dt.datetime.fromisoformat(parts[0])
    except (OSError, ValueError, IndexError):
        return False
    if len(parts) > 1 and parts[1].isdigit() and os.name != "nt":
        return _pid_alive(int(parts[1]))
    return (now or dt.datetime.now()) - was < dt.timedelta(
        minutes=APEX_SIGNIN_LOCK_MINUTES)


def _past_login(page) -> bool:
    """Signed in = the app's own Payroll link is on the page. Checked WITHOUT
    navigating, so a person mid-form (or mid-2-step code, a page with no
    password box on it) is never yanked away."""
    try:
        return page.locator('a[href="/payrolls"]').count() > 0
    except Exception:  # noqa: BLE001 -- mid-navigation
        return False


def run(log=print) -> int:
    from patchright.sync_api import sync_playwright
    from automations.carlos_payroll_pull import run as AP
    from automations.shared import browser_banner
    from automations.icd_alerts import apex_guard as G

    log("")
    log("  Opening Apex in Lucy's browser.")
    log("")
    log("  Sign in there the same way you do anywhere else. It has to be THIS")
    log("  window -- signing in with your own browser does not reach Lucy.")
    log("")
    APEX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        mark_open()
    except OSError:
        pass          # not being able to say so must not stop them signing in
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(APEX_PROFILE_DIR), headless=False, args=["--disable-sync"],
                **G.launch_args())
            # A person's hands: nothing stopped, but whatever Lucy's lock would
            # stop is written down -- that is how the sign-in / 2-step requests
            # get learned before Lucy signs in alone (apex_guard).
            guard = None
            try:
                guard = G.install(ctx, "watch")
            except Exception:  # noqa: BLE001 -- the list is a note here
                pass
            browser_banner.attach(ctx, BANNER, BANNER_DETAIL)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(AP.APEX_URL, wait_until="domcontentloaded",
                          timeout=60_000)
                waited = 0
                while waited < WAIT_SECONDS:
                    time.sleep(POLL_SECONDS)
                    waited += POLL_SECONDS
                    if not _past_login(page):
                        continue
                    # PROVE IT THE WAY THE PNL WILL: Payroll Entry with a pay
                    # period on it, not just a page that is not the login.
                    try:
                        AP._dismiss_modal(page)
                        AP.goto_payroll_entry(page)
                    except (SystemExit, Exception):  # noqa: BLE001
                        continue
                    log("")
                    log("  Signed in -- checked by opening your Payroll Entry.")
                    log("  Nothing else to do.")
                    return 0
                log("")
                log("  Nobody signed in, so nothing has changed. This will")
                log("  open again later.")
                return 1
            finally:
                if guard:
                    guard.save()
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        try:
            APEX_SIGNIN_LOCK.unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())

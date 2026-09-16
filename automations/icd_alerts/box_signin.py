"""Open Lucy's own browser so the office can sign into My Service Cloud.

WHY THIS EXISTS AND A NORMAL BROWSER WILL NOT DO. Lucy keeps her own Chrome
profile, deliberately: pointing her at the office's real profile would fight
their own browsing, and a profile already held by a running Chrome blocks the
launch outright (see config.py). So a session in Safari, or in their everyday
Chrome, is invisible to her -- they could sign in ten times and nothing would
change.

The office cannot be expected to know that. All they see is "sales stopped".
So this opens the window Lucy actually uses, in front of them, and waits while
they sign in with their authenticator.

  python -m automations.icd_alerts.box_signin

It is the ONLY thing they ever have to do for this, and only when the session
drops -- which Ryan McSpadden describes as "it saves typically, but it feels
random when it logs me out" (2026-09-15).

IT VERIFIES. The window closing is not the same as being signed in, and
"looks done" is how an office waits a day for numbers that were never coming.
This checks the page and says plainly which happened.
"""
from __future__ import annotations

import sys
import time

from automations.icd_alerts import config as C
from automations.shared import servicecloud as SC

# How long to leave the window open. Long enough to find a phone, unlock it,
# open an authenticator and type six digits -- without leaving a browser open
# on somebody's desk all afternoon if they walk away.
WAIT_SECONDS = 300
POLL_SECONDS = 3


def _login(log=print) -> dict:
    """The saved My Service Cloud login, ASKING FOR IT if there is none.

    WHY THIS BELONGS HERE AND NOT ONLY IN THE INSTALLER. An office already
    enrolled before Box sales existed has no My Service Cloud login saved,
    and the only thing that asked for one was a full re-run of setup --
    which needs their original enrolment code, which is the one thing they
    no longer have to hand. Sending somebody hunting for a code to fix a
    login is how a five-minute job becomes next week.

    The reader refuses to run without a saved login (box_read.read_day), so
    signing in here and skipping this would leave the session live and the
    sweep still reporting that it cannot read anything -- fixed, and still
    broken, which is the worst of the three states.

    CANCELLING IS ALLOWED. They may not have the password on them. The
    browser still opens, they can still sign in, and the next sweep will ask
    again -- rather than this refusing to open the window at all.
    """
    cr = C.sc_creds()
    if cr.get("email"):
        return cr
    from automations.icd_alerts import dialogs as ask
    log("")
    log("  No My Service Cloud login is saved on this computer yet.")
    log("  Look for the pop-up box.")
    try:
        email = ask.text("Your My Service Cloud email:").strip()
        if not email:
            raise ask.Cancelled()
        password = ask.password("Your My Service Cloud password:")
        if not password:
            raise ask.Cancelled()
    except ask.Cancelled:
        log("  Skipped. You can still sign in below, but the computer will")
        log("  ask for this again.")
        return {}
    except Exception as e:  # noqa: BLE001 — a dialog failure is not fatal here
        log("  Could not show the box (%s). Carrying on." % type(e).__name__)
        return {}
    C.save_sc_creds(email, password)
    log("  Saved.")
    return {"email": email, "password": password}


def run(log=print) -> int:
    from patchright.sync_api import sync_playwright

    cr = _login(log)
    log("")
    log("  Opening My Service Cloud in Lucy's browser.")
    log("")
    log("  Sign in there with your authenticator code, the same as you would")
    log("  anywhere else. It has to be THIS window -- signing in with your")
    log("  own browser does not reach Lucy.")
    if cr.get("email"):
        log("")
        log("  The account is %s." % cr["email"])
    log("")

    C.SC_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.SC_PROFILE_DIR), headless=False, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = SC.LOGIN_URL.rsplit("/", 1)[0]
            page.goto(SC.LOGIN_URL, timeout=SC.LOGIN_TIMEOUT_MS)

            if not SC.session_lost(page):
                log("  Already signed in — nothing to do.")
                return 0

            waited = 0
            said_mfa = False
            while waited < WAIT_SECONDS:
                time.sleep(POLL_SECONDS)
                waited += POLL_SECONDS
                try:
                    # SAY WHERE THEY ACTUALLY ARE. Ryan reached the
                    # authenticator enrolment screen and was told he was
                    # finished, because that page has no password box on it.
                    # Being told "done" is why somebody stops.
                    if SC.on_mfa_setup(page) and not said_mfa:
                        said_mfa = True
                        log("")
                        log("  My Service Cloud wants you to set up your")
                        log("  authenticator first — scan the code with the")
                        log("  app, then enter the six digits. Keep going;")
                        log("  this is still waiting.")
                        continue
                    if not SC.session_lost(page):
                        # PROVE IT THE WAY THE SWEEP WILL USE IT. Being past
                        # the login form is not the same as being able to
                        # read contracts, and the contracts page is the only
                        # thing that matters here.
                        page.goto(base + SC.CONTRACTS_PATH,
                                  timeout=SC.LOGIN_TIMEOUT_MS)
                        if SC.session_lost(page):
                            continue
                        log("")
                        log("  Signed in — checked by opening your contracts.")
                        log("  Lucy can see your sales again; they start")
                        log("  updating within a few minutes.")
                        return 0
                except Exception:  # noqa: BLE001 — they may be mid-navigation
                    pass
            log("")
            log("  Nobody signed in, so nothing has changed. Run this again")
            log("  when you have your authenticator to hand.")
            return 1
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())

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


def run(log=print) -> int:
    from patchright.sync_api import sync_playwright

    cr = C.sc_creds()
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
            page.goto(SC.LOGIN_URL, timeout=SC.LOGIN_TIMEOUT_MS)

            if not SC.session_lost(page):
                log("  Already signed in — nothing to do.")
                return 0

            waited = 0
            while waited < WAIT_SECONDS:
                time.sleep(POLL_SECONDS)
                waited += POLL_SECONDS
                try:
                    if not SC.session_lost(page):
                        # VERIFIED, not assumed. A closed window and a live
                        # session are different things.
                        log("")
                        log("  Signed in. Lucy can see your sales again —")
                        log("  they start updating within a few minutes.")
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

"""Open Lucy's own browser so a Verizon office can sign into Optix.

    python -m automations.icd_alerts.optix_signin

Same reason box_signin exists: Lucy reads Optix from HER Chrome profile
(config.OPTIX_PROFILE_DIR), so signing in from Safari or the office's own
Chrome never reaches her. This opens the window she uses and waits.

IT VERIFIES. Signed in = Optix shows its "please select your profile" page
(the first screen after a good Verizon SSO sign-in, mapped on Nico
Murrugarra's account 2026-11-06). The window closing is not proof.
"""
from __future__ import annotations

import datetime as dt
import sys
import time

from automations.icd_alerts import config as C
from automations.icd_alerts import optix_read as O

# Verizon SSO is last name + User ID, then password and adaptive MFA -- give
# a person time to find a code (Megan's first try ran out at 5 min, 2026-11-06).
WAIT_SECONDS = 600
POLL_SECONDS = 3


def signed_in(page) -> bool:
    try:
        return "select your profile" in page.inner_text("body").lower()
    except Exception:  # noqa: BLE001 — mid-navigation reads throw
        return False


def run(log=print) -> int:
    log("")
    log("  Opening Verizon Optix in Lucy's browser.")
    log("")
    log("  Sign in there the same as you always do. It has to be THIS window --")
    log("  signing in with your own browser does not reach Lucy.")
    log("")
    C.OPTIX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        C.OPTIX_SIGNIN_LOCK.write_text(dt.datetime.now().isoformat())
    except OSError:
        pass
    try:
        return _window(log)
    finally:
        try:
            C.OPTIX_SIGNIN_LOCK.unlink()
        except OSError:
            pass


def _window(log) -> int:
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.OPTIX_PROFILE_DIR), headless=False, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(O.PROFILE_URL, timeout=60000)
            try:
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
            deadline = time.time() + WAIT_SECONDS
            while time.time() < deadline:
                if signed_in(page):
                    log("  Signed in to Optix. Lucy can read your knocks now.")
                    return 0
                time.sleep(POLL_SECONDS)
            log("  Still not signed in after %d minutes. Run this again when"
                " you are ready:" % (WAIT_SECONDS // 60))
            log("    python -m automations.icd_alerts.optix_signin")
            return 1
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(run())

"""Open OwnerVille in LUCY'S OWN browser so the owner signs in there by hand.

WHY (Steve McElwee, 2026-10-21). The password box saved his OwnerVille
password every time and then PROVED it with a real knocks read -- and every
proof landed back on ownerville.com's login page with no session, so the box
said "OwnerVille did not take that" and asked again. From the outside that is
"my password keeps getting rejected", and every retry is a strike toward
OwnerVille locking the account. Nothing in the fault said WHY the sign-in did
not stick: a first-login prompt, a security check that did not clear, a
username that is not the email -- the agent cannot tell, a person at the
window can.

SaraPlus and My Service Cloud already have exactly this window (sara_signin,
box_signin): sign in once, by hand, in the Chrome profile the sweep uses, and
the session lives in that profile from then on. The sweep finds its rqst token
and never types the password. This is the OwnerVille copy.

    python -m automations.icd_alerts.ov_signin          # what finish_setup / the box run

Read-only outside that profile: posts nothing, relays nothing, saves no
password. It only waits for the session to exist, proves it the way the sweep
does (capture_rqst), and clears the sign-in hold so the next sweep tries.
"""
from __future__ import annotations

import datetime as dt
import sys
import time

from automations.icd_alerts import config as C
from automations.shared import ownerville_knocks as K

WAIT_SECONDS = 300
POLL_SECONDS = 5


def _rqst_now(page) -> bool:
    """Signed in = the page we are on, or the link on it, carries rqst.
    Checked WITHOUT navigating, so a person mid-form is never yanked away."""
    try:
        if "rqst=" in (page.url or ""):
            return True
        href = page.evaluate(
            "() => { const a = document.querySelector('a[href*=\"rqst=\"]');"
            " return a ? a.getAttribute('href') : ''; }")
        return "rqst=" in (href or "")
    except Exception:  # noqa: BLE001 -- mid-navigation
        return False


def run(log=print) -> int:
    from patchright.sync_api import sync_playwright
    try:
        cr = C.ownerville_creds()
    except RuntimeError:
        cr = {}
    log("")
    log("  Opening OwnerVille in Lucy's browser.")
    log("")
    log("  Sign in there the same way you do anywhere else. It has to be THIS")
    log("  window -- signing in with your own browser does not reach Lucy.")
    if cr.get("username"):
        log("")
        log("  The saved username is %s." % cr["username"])
    log("")
    C.OV_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        C.OV_SIGNIN_LOCK.parent.mkdir(parents=True, exist_ok=True)
        C.OV_SIGNIN_LOCK.write_text(dt.datetime.now().isoformat())
    except OSError:
        pass
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(C.OV_PROFILE_DIR), headless=False, args=["--disable-sync"])
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(K.LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
                waited = 0
                while waited < WAIT_SECONDS:
                    time.sleep(POLL_SECONDS)
                    waited += POLL_SECONDS
                    if not _rqst_now(page):
                        continue
                    # PROVE IT THE WAY THE SWEEP WILL: a fresh visit that
                    # comes back with the token, not just a page that rendered.
                    try:
                        if K.capture_rqst(page):
                            from automations.icd_alerts import ov_read
                            ov_read.clear_ov_hold()
                            log("")
                            log("  Signed in -- checked the way the knocks read")
                            log("  checks. Your knocks board starts again within")
                            log("  a few minutes. Nothing else to do.")
                            return 0
                    except Exception:  # noqa: BLE001
                        pass
                log("")
                log("  Nobody signed in, so nothing has changed. Run this again")
                log("  when you have a minute at the computer.")
                return 1
            finally:
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        try:
            C.OV_SIGNIN_LOCK.unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())

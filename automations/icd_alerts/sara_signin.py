"""Open Lucy's own browser so the office can clear SaraPlus's passcode wall.

WHY A NORMAL BROWSER WILL NOT DO -- the same reason box_signin exists. Lucy
keeps her own Chrome profile, and SaraPlus's `/Security/` challenge trusts a
BROWSER, not an account. Francia signed into SaraPlus on Khalil's Mac and in
her own browser on 2026-09-17 and nothing changed for the agent, because the
agent has never been that browser. She could have done it ten more times.

WHAT THIS IS ACTUALLY FOR, and it is not a password. SaraPlus answered
Khalil's sign-in with:

    /e/(S(qvxtpep3hkijen2pmu1hwdge))/Security/VerifyPasscode.aspx

There is a SESSION ID in that url, which is the proof the password was already
accepted -- SaraPlus is saying "new location or browser", not "wrong
password". Read as a password problem it costs a password change that fixes
nothing; our own notes record two of those.

AND WHY THE AGENT CANNOT HEAL THIS ONE ITSELF. _heal_and_login answers the
Change Password page by throwing the Chrome profile away and retrying, which
is right when the profile is wedged. Against the passcode wall it is exactly
wrong: a brand-new profile is a brand-new BROWSER, so the retry earns a fresh
challenge, and "the wall survived a new profile" then reads as proof the
account expired. It is not proof. It is the heal feeding the wall.

So this opens the profile the sweep really uses, in front of a person, and
waits while they sign in and type the code SaraPlus emails them. One person,
once per machine, and the trust cookie stays in the profile afterwards.

    python -m automations.icd_alerts.sara_signin

IT VERIFIES, because a closed window is not a signed-in one, and "looks done"
is how an office waits a day for numbers that were never coming.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Dict

from automations.icd_alerts import config as C
from automations.shared import saraplus as S

WAIT_SECONDS = 600          # the email is the slow part, not the typing
POLL_SECONDS = 5


def _signed_in(url: str) -> bool:
    """On the Hub, rather than merely off the login page.

    Deliberately NOT "no password field": SaraPlus's own security pages have
    no password field either, so that test calls the passcode wall a success
    and sends somebody away from the one screen they needed to finish.
    """
    u = (url or "").lower()
    if S.SECURITY_PATH in u:
        return False
    return "dealerpages/" in u or "reports/" in u


def _still_challenged(url: str) -> bool:
    return S.SECURITY_PATH in (url or "").lower()


def run(log=print) -> int:
    from patchright.sync_api import sync_playwright

    try:
        cr = C.creds()
    except Exception:  # noqa: BLE001 — no creds saved is not fatal here
        cr = {}

    log("")
    log("  Opening SaraPlus in Lucy's browser.")
    log("")
    log("  Sign in there, then enter the code SaraPlus emails you. It has to")
    log("  be THIS window -- signing in with your own browser does not reach")
    log("  Lucy, however many times you do it.")
    if cr.get("email"):
        log("")
        log("  The account is %s." % cr["email"])
    log("")
    log("  Your password is NOT being changed and does not need to be.")
    log("")

    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    C.SARA_SIGNIN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        C.SARA_SIGNIN_LOCK.write_text(dt.datetime.now().isoformat())
    except OSError:
        pass          # not being able to say so must not stop them signing in
    try:
        return _window(log=log)
    finally:
        try:
            C.SARA_SIGNIN_LOCK.unlink()
        except OSError:
            pass


def _live_urls(ctx) -> list:
    """Where every open tab ACTUALLY is right now, asked of the page itself.

    NOT page.url. In the sync API that is a cached value refreshed by protocol
    events, and events are only processed while a Playwright call is running.
    The loop below used to wait with time.sleep, which runs none -- so page.url
    stayed frozen on the address the window opened on, forever. Francia signed
    in, typed the emailed code, reached the Hub on 2026-09-18 AND again on
    2026-09-21, and the Terminal never noticed either time. box_signin never
    had this bug only by accident: it asks the page a question every tick.

    EVERY TAB, because a sign-in that opens its result in a new tab would
    otherwise be watched in the old one.
    """
    out = []
    for pg in list(getattr(ctx, "pages", []) or []):
        try:
            out.append(pg.evaluate("() => location.href") or pg.url)
        except Exception:  # noqa: BLE001 -- a tab mid-navigation or closed
            try:
                out.append(pg.url)
            except Exception:  # noqa: BLE001
                pass
    return out


def _window(log=print) -> int:
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        from automations.icd_alerts import sara_read as _SR
        kw = {"headless": False, "args": ["--disable-sync"]}
        if _SR.browser_id():
            kw["user_agent"] = _SR.browser_id()
        ctx = p.chromium.launch_persistent_context(str(C.PROFILE_DIR), **kw)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(S.LOGIN_URL, timeout=60000)
            if _signed_in(page.url):
                log("  Already signed in — nothing to do.")
                return 0

            waited, said, url = 0, False, ""
            while waited < WAIT_SECONDS:
                # wait_for_timeout, NOT time.sleep: it keeps the connection to
                # the browser running, so the page's address actually updates.
                try:
                    page.wait_for_timeout(POLL_SECONDS * 1000)
                except Exception:  # noqa: BLE001 — the tab we held was closed
                    time.sleep(POLL_SECONDS)
                waited += POLL_SECONDS
                urls = _live_urls(ctx)
                if not urls:
                    break                     # they closed the window
                if any(_signed_in(u) for u in urls):
                    # THE IDENTITY THAT WAS JUST TRUSTED is the one the hidden
                    # reads must present from now on.
                    try:
                        _SR.remember_browser_id(
                            page.evaluate("() => navigator.userAgent"), log=log)
                    except Exception:  # noqa: BLE001
                        pass
                    log("")
                    log("  Signed in. This browser is trusted now, so the")
                    log("  sweep can read sales again within a few minutes.")
                    return 0
                url = urls[0]
                if any(_still_challenged(u) for u in urls) and not said:
                    said = True
                    log("  SaraPlus is asking for the emailed code — that is")
                    log("  this step, not a password problem. Enter it here.")
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass

    if _still_challenged(url):
        log("")
        log("  Still on SaraPlus's security screen, so nothing changed. The")
        log("  code has to be entered in THAT window before it closes.")
    else:
        log("")
        log("  Did not reach the SaraPlus Hub, so this is not done yet.")
    log("  Run this again when you have the code to hand.")
    return 1


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())

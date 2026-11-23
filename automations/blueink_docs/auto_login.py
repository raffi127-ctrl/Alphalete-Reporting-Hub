"""Sign in to Blue Ink with the office's own saved password, no person needed.

Blue Ink's sign-in is an email, a password and a Log In button -- no code, no
second factor (Megan, 2026-11-23, screenshot of the page). "Continue with
Google" sits beside it as an alternative, not a requirement. So this is the
same shape as the OwnerVille and Sterling sign-ins the fleet already types,
and it is typed the same way.

WHY THIS IS NEW, GIVEN session.py SAYS NOTHING TYPES A PASSWORD. That rule
was written for ONE SHARED ACCOUNT driven from our machines, and the reason
it gives is "the repo is public". The credential never goes in the repo: it
lives in the owner's own home directory beside their OwnerVille, Sterling,
AppStream and Apex passwords, readable by that user alone, on their machine.
An ICD's Blue Ink password is no different from those, and a fortnightly
window asking an owner to sign in again is a window Lucy is not supposed to
open (CLAUDE.md: ECO runs in the background).

TWO THINGS THIS DELIBERATELY DOES NOT DO.

  It never retries a rejected password. Steve McElwee's OwnerVille box
  re-typed a password that was not working and every attempt was a strike
  toward the account locking (ov_signin.py). One attempt; if it does not
  take, hand over to the person and say why.

  It never reports a sign-in it has not proved. The Blue Ink app routes
  itself to /dashboard while still logged out, which is how --login once
  saved an empty session and called it success (2026-09-08). This uses the
  same two-stable-looks test session.signed_in was written for.

NOT PROVED LIVE YET. Nothing here has run against a real Blue Ink sign-in
page -- the selectors come from the screenshot. The first run that matters
should be watched, exactly as sterling_send's Send press was.

    python -m automations.blueink_docs.auto_login            # try it
    python -m automations.blueink_docs.auto_login --check    # creds present?
"""
from __future__ import annotations

import argparse
import sys

from automations.blueink_docs import config
from automations.blueink_docs import session

# The page in the screenshot: two text boxes and a Log In button. Asked for by
# what they ARE rather than by a class name -- Blue Ink is a single-page app
# and its class names are generated, so they change without the page changing.
EMAIL_BOX = "input[type='email'], input[name='email'], input[name='username']"
PASSWORD_BOX = "input[type='password']"
LOGIN_BUTTON = "button:has-text('Log In'), button:has-text('Login'), " \
               "button[type='submit']"

# Long enough for a slow sign-in, short enough that a hung page does not hold
# a run open. A person signing in by hand gets ten minutes (session.login);
# typing takes seconds, so anything past this is a page that is not answering.
SETTLE_MS = 3000
TRIES = 10          # 10 x 3s = 30s


class NotSignedIn(RuntimeError):
    """The typed sign-in did not take. Carries WHY, for the owner's window."""


def can_try() -> bool:
    """Is there a saved Blue Ink password on this machine at all?"""
    return bool(config.login_creds())


def _signed_in_twice(page) -> bool:
    """Signed in, confirmed by a second look three seconds later.

    One look catches the moment the app is passing THROUGH /dashboard on its
    way to the login screen -- which is exactly how a sign-in was reported
    twice on 2026-09-08 with nobody signed in.
    """
    if not session.signed_in(page):
        return False
    page.wait_for_timeout(SETTLE_MS)
    return session.signed_in(page)


def login(log=print) -> int:
    """0 signed in and saved · 1 no password saved · 2 it did not take."""
    creds = config.login_creds()
    if not creds:
        log("  No Blue Ink password saved on this machine -- a person signs "
            "in here.")
        return 1

    sync_playwright = session._sync_api()
    session.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(session.PROFILE_DIR),
            # HIDDEN. This runs by itself on somebody's office computer and
            # nobody has to act, so nothing appears on their screen
            # (CLAUDE.md, and icd_alerts/visible_windows.py lists the few
            # exceptions -- this is not one of them).
            headless=True, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(session.LOGIN_URL, wait_until="domcontentloaded",
                      timeout=60_000)

            # ALREADY SIGNED IN IS A SUCCESS, NOT A REASON TO TYPE. The
            # profile may still hold a live session; typing a password into
            # a signed-in app is how you end up logged out of it.
            if _signed_in_twice(page):
                log("  Blue Ink was already signed in on this machine.")
                _save(ctx, log)
                return 0

            try:
                page.fill(EMAIL_BOX, creds["email"], timeout=20_000)
                page.fill(PASSWORD_BOX, creds["password"], timeout=20_000)
            except Exception as exc:                 # noqa: BLE001
                # NEVER let the exception carry the password: a fill() error
                # from Playwright quotes the value it was given, and that text
                # goes into a log file and a Slack post.
                raise NotSignedIn(
                    "Blue Ink's sign-in page did not look the way we expect "
                    "(%s). Nothing was typed." % type(exc).__name__) from None
            page.click(LOGIN_BUTTON, timeout=20_000)

            for _ in range(TRIES):
                page.wait_for_timeout(SETTLE_MS)
                if _signed_in_twice(page):
                    log("  Signed in to Blue Ink.")
                    _save(ctx, log)
                    return 0

            # ONE ATTEMPT. Not a retry loop: a wrong password typed again and
            # again is how an account gets locked, and a locked Blue Ink
            # account stops the paperwork for everybody in that office.
            raise NotSignedIn(
                "Blue Ink did not accept the saved sign-in. It was tried "
                "once and will not be tried again -- the password may have "
                "changed, or the account may need a person.")
        finally:
            try:
                ctx.close()
            except Exception:                        # noqa: BLE001
                pass


def _save(ctx, log=print) -> None:
    """Keep the session so the next run does not sign in at all."""
    try:
        ctx.storage_state(path=str(session.STORAGE_STATE))
        session.STORAGE_STATE.chmod(0o600)
    except Exception as exc:                         # noqa: BLE001
        # Not fatal: we ARE signed in, this context can send. It only means
        # the next run signs in again.
        log("  (could not save the session: %s)" % type(exc).__name__)


def ensure(log=print) -> bool:
    """True when this machine can send. Types the password if it has one.

    The one call a caller wants: try the saved session first (free), then the
    saved password, and only then is a person needed.
    """
    if session.have_session() or session.have_profile():
        if session.check(headless=True) == 0:
            return True
    if not can_try():
        return False
    try:
        return login(log=log) == 0
    except NotSignedIn as exc:
        log("  %s" % exc)
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="say whether a password is saved here, sign in to "
                         "nothing")
    args = ap.parse_args(argv)
    if args.check:
        print("A Blue Ink password IS saved on this machine."
              if can_try() else
              "No Blue Ink password saved here -- a person signs in.")
        return 0
    try:
        return login()
    except NotSignedIn as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

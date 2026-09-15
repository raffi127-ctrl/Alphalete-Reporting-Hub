"""My Service Cloud — what Box offices use for sales, as AT&T uses SaraPlus.

ONE FILE FOR THE SITE, the same rule saraplus.py follows: every selector, URL
and grid marker lives here and nothing re-derives them. Every Box office signs
into the same system, so a change to the site is a change in one place for all
of them.

WHY IT EXISTS AT ALL. Box, Energy Wells and NDS have no SaraPlus account, so
until now the knocks board was their ENTIRE product -- no credit checks, no
sales, nothing on the days their reps were selling rather than knocking. This
is the other half for the Box offices (Megan 2026-09-15: "this is what Box
uses for sales like at&t uses Sara+").

THE PASSWORD NEVER LEAVES THE OFFICE'S MACHINE. Same contract as SaraPlus and
OwnerVille: the installer asks for it on their own Mac, it is written to their
own config directory, and what reaches us is counts. Nothing in this repo ever
holds one.
"""
from __future__ import annotations

from typing import Optional

# The office signs in here. Asked for and confirmed rather than guessed
# (Megan 2026-09-15, from Ryan McSpadden's own screenshot).
LOGIN_URL = "https://myservicecloud.net/sign-in"

# Read off the live sign-in page, not invented. The form is a plain HTML one:
# an email input, a password input and a submit button, with no framework
# wrapper to fight -- unlike SaraPlus, whose Telerik ids are what most of
# saraplus.py exists to handle.
SEL_EMAIL = "input[type='email']"
SEL_PASSWORD = "input[type='password']"
SEL_SUBMIT = "button[type='submit']"

# Where a wrong or expired password lands. Treated the same way SaraPlus's
# ResetPassword.aspx is: a page we must recognise, because the alternative is
# a scrape that "succeeds" against a login form and reports zero of everything.
PASSWORD_RESET_PATH = "/user/index/request-password-reset"

LOGIN_TIMEOUT_MS = 60_000


class AccountProblem(RuntimeError):
    """Something the office can fix, phrased for the office."""


def _is_password_reset(url: str) -> bool:
    """Did we land on the reset page instead of the app?

    A LOGIN THAT LANDS HERE IS NOT A LOGIN. SaraPlus taught this the
    expensive way: a session that lands on ResetPassword.aspx still renders a
    page, still parses, and reports every rep at zero -- which reads as a
    quiet day rather than a broken account.
    """
    return PASSWORD_RESET_PATH in (url or "").lower()


def signed_in(page) -> bool:
    """Are we past the login form?

    Asked of the page rather than assumed from a click: the sign-in button
    submitting is not the same as the credentials being accepted.
    """
    try:
        if _is_password_reset(page.url):
            return False
        return page.query_selector(SEL_PASSWORD) is None
    except Exception:  # noqa: BLE001
        return False


def sign_in(page, email: str, password: str, *,
            login_url: str = LOGIN_URL, log=print) -> str:
    """Sign in and return the URL we ended up on. Raises AccountProblem.

    The error text is written for the OFFICE OWNER, not for us: they are the
    only person who can fix a wrong password, and "authentication failed" in
    a log on their own Mac helps nobody.
    """
    page.goto(login_url, timeout=LOGIN_TIMEOUT_MS)
    page.fill(SEL_EMAIL, email)
    page.fill(SEL_PASSWORD, password)
    page.click(SEL_SUBMIT)
    try:
        page.wait_for_load_state("networkidle", timeout=LOGIN_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — a slow page is not a failed login
        pass

    if _is_password_reset(page.url):
        raise AccountProblem(
            "My Service Cloud is asking %s to reset its password, so nothing "
            "can be read until that is done. Sign in at %s in a normal "
            "browser, set the new password, then run the installer again to "
            "save it." % (email, login_url))
    if not signed_in(page):
        raise AccountProblem(
            "My Service Cloud did not accept the login for %s. If the "
            "password has changed, run the installer again and it will ask "
            "for the new one." % email)
    log("signed in to My Service Cloud as %s" % email)
    return page.url

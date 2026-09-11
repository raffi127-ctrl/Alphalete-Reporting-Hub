"""Read this office's own knocks out of OwnerVille, on this office's machine.

ONE DAY, ONE GRID, THEIR OWN LOGIN. No impersonation, no office picker, no
campaign pin -- an owner's account lands on their own office, which is the
entire reason this read is worth moving to their laptop rather than adding a
53rd impersonation to ours.

IT RELAYS ROWS, NOT A BOARD. What the rows are called, which columns matter,
how the card is drawn and when it is posted are all decided on our side. The
laptop's job is to be the thing that can authenticate, and nothing more.

THE SESSION IS REUSED. A persistent profile keeps the OwnerVille session alive
between runs, so most sweeps skip the login entirely -- which matters because
the login costs a full minute of deliberate waiting (see
shared/ownerville_knocks: the security box clears itself if you leave it
alone). Signing in every 15 minutes would be both slow and the kind of pattern
that earns a challenge.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.icd_alerts import config as C
from automations.shared import ownerville_knocks as K


class KnocksProblem(RuntimeError):
    """Phrased for whoever is reading it on an owner's laptop."""


def _context(p, headless: bool):
    C.OV_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        str(C.OV_PROFILE_DIR), headless=headless, args=["--disable-sync"])
    if not headless:
        from automations.shared import browser_banner
        browser_banner.attach(ctx)
    return ctx


def _session(page, log=print) -> str:
    """An rqst token, signing in only if the profile's session has lapsed."""
    rqst = K.capture_rqst(page)
    if rqst:
        log("OwnerVille session still good")
        return rqst

    try:
        cr = C.ownerville_creds()
    except RuntimeError as e:
        raise KnocksProblem(str(e))

    log("OwnerVille session has lapsed — signing in")
    try:
        K.login(page, cr["username"], cr["password"], log=log)
    except Exception as e:  # noqa: BLE001
        raise KnocksProblem(
            "Could not sign in to OwnerVille. If you recently changed your "
            "OwnerVille password, open the alerts app and enter the new one. "
            "(%s)" % type(e).__name__)

    rqst = K.capture_rqst(page)
    if not rqst:
        raise KnocksProblem(
            "Signed in to OwnerVille but it did not open a working session. "
            "Nothing is lost — the next run tries again.")
    return rqst


def read_knocks(day: Optional[dt.date] = None, *, headless: bool = True,
                log=print) -> List[Dict[str, str]]:
    """Today's disposition rows for this office, raw, keyed by grid header."""
    from patchright.sync_api import sync_playwright

    day = day or C.today()
    mdy = day.strftime("%m/%d/%Y")      # NOT %-m/%-d: that is not portable

    with sync_playwright() as p:
        ctx = _context(p, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            rqst = _session(page, log=log)
            K.navigate(page, rqst, mdy, log=log)
            try:
                return K.read_rows(page, log=log)
            except K.OwnervilleError as e:
                raise KnocksProblem(str(e))
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass

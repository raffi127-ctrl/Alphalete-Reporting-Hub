"""Open OwnerVille on THIS office's own computer, with this office's login.

Megan, 2026-11-24, when I raised the OwnerVille session contention on Lucy 3:
*"the OV sweep would happen on the ECO machine."* That is the answer, and it
dissolves the problem rather than working around it -- forty offices reading
their own OwnerVille on forty machines, each with its own login and its own
session, never queue behind each other. The contention only ever existed
because one Lucy was doing it on behalf of everybody.

WHY THIS FILE. `shared.tableau_patchright.ownerville_session` is what
`icd_onboarding.presses` and `obcl_ov_sweep` both open, and it cannot ship: it
pulls in `recruiting_report.opt_phase` and the Hub behind it. It also holds ONE
session per machine on purpose, which is right for a Lucy serving many offices
and pointless on a box serving one. This is the office-side twin, the same move
`eco_steps.appstream_here` made for ApplicantStream on the same day.

EVERYTHING HARD HERE IS ALREADY SOLVED, in `ov_read`, and this reuses it rather
than restating it:

  * the session is REUSED. A sweep that signed in every time would spend its
    strikes and hit OwnerVille's lock page.
  * a window ONLY when one is needed. The security check on the password step
    never clears for a headless browser, so a lapsed session needs a real
    window -- but that is the rare case, and a browser on the owner's screen
    four times an hour for no reason is what `quiet_window` exists to stop.
  * SIGNING IN CAN BE ON HOLD, and then this refuses rather than trying. Jenny
    (Figspire), 2026-10-12: a saved login kept failing, the agent retried every
    sweep, and Lucy's window sat on OwnerVille's "Account Permanently Locked"
    page 134 times in a day. A hold is a real answer and the caller is told
    which one.

    THAT IS WHY THIS RAISES instead of yielding a page that cannot work: a
    caller handed a dead page reports "no rows", and "I could not look" must
    never read as "nobody has done anything"
    ([[feedback_empty_means_proven_zero]]).
"""
from __future__ import annotations

import contextlib
from typing import Optional

from automations.icd_alerts import config as C


class OwnervilleUnavailable(RuntimeError):
    """OwnerVille could not be opened, with the reason in its message.

    Its own class so a caller can tell it from anything that went wrong DURING
    a read -- the first means nothing was looked at, which is the one a step
    must never record as an answer.
    """


@contextlib.contextmanager
def ownerville_here(*, headless: bool = True, campaign: str = "",
                    log=print):
    """Yield an OwnerVille page on this office's own browser.

    `campaign` picks the client/campaign the way `ov_read` does, when a
    machine's OwnerVille holds more than one.

    IT DOES NOT CLOSE A BROWSER IT DID NOT OPEN, and it always closes the one
    it did: the profile is shared with the knocks read, and a context left
    behind is a profile the next sweep finds locked.
    """
    from automations.icd_alerts import ov_read as OV
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:            # noqa: F401 -- a box without patchright
        from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # A window ONLY when one is actually needed -- see the module note.
        show = headless and not OV._has_session(p, log=log)
        if show:
            held = OV.ov_hold_message()
            if held:
                # No window at all while signing in is on hold: the window IS
                # the popup the owner keeps closing (Jenny, 2026-10-12).
                raise OwnervilleUnavailable(held)
        quiet, guard = False, None
        if show:
            try:
                from automations.icd_alerts import quiet_window as QW
                quiet = QW.use_quiet()
                if quiet:
                    guard = QW.Guard(C.OV_PROFILE_DIR).start()
            except Exception:      # noqa: BLE001 -- the old window is the fallback
                quiet, guard = False, None
            log("OwnerVille needs signing in again — %s"
                % ("in the background" if quiet else "opening a window briefly"))
        ctx = OV._context(p, headless and not show, quiet=quiet)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # THE CAMPAIGN, THE WAY THE KNOCKS READ DOES IT. The id comes from
            # this office's own config -- a named campaign, else whichever one
            # this machine is pinned to -- never from a caller, because an
            # office reading another campaign's rows is indistinguishable from
            # an office with nothing on.
            cid = (C.CAMPAIGN_IDS.get((campaign or "").strip().lower())
                   if campaign else C.campaign_id())
            if cid and OV._is_v2(page):
                # V2 IGNORES THE URL PIN SERVER-SIDE (Jamis 2026-10-06 got no
                # grid; Roshan 2026-10-08 got the wrong campaign's). On a page
                # carrying the V2 switcher, the client is chosen through the
                # page's own control.
                if not OV._choose_client(page, cid, campaign, log=log):
                    raise OwnervilleUnavailable(
                        "could not choose this office's campaign (%s) in "
                        "OwnerVille's own switcher, so whose rows the page "
                        "would serve is unknown" % (campaign or cid))
            yield page
        finally:
            try:
                ctx.close()
            except Exception:      # noqa: BLE001
                pass
            if guard is not None:
                try:
                    guard.stop()
                except Exception:  # noqa: BLE001
                    pass

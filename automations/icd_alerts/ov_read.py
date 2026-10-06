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

THE LOGIN NEEDS A VISIBLE WINDOW; THE READS DO NOT. Proven against the live
site on 2026-09-11: headless, the password step comes back "Please complete the
security check" no matter how long you wait -- the box does not clear for a
headless browser. The same login headful sailed through and landed on the
office dashboard with an rqst. Once the session is in the profile, reads run
headless perfectly well (41 reps and 41 tracker rows, invisible).

So this opens headless, and only falls back to a window when the session has
actually lapsed -- which is rare. That window is why browser_banner exists: it
appears on somebody's screen unannounced, and the reasonable thing for them to
do with an unexplained browser is close it.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.icd_alerts import config as C
from automations.shared import ownerville_knocks as K


class KnocksProblem(RuntimeError):
    """Phrased for whoever is reading it on an owner's laptop."""


def _page_evidence(page, seen: List[str]) -> str:
    """The read's own log lines plus where the page ended up and what it says.

    Best effort on every line: this runs inside a failure, and a probe that
    itself throws would replace a diagnosable fault with a crash."""
    out = ["what the read saw:"] + ["  " + ln for ln in seen[-15:]]
    try:
        out.append("page url: %s" % page.url)
    except Exception:  # noqa: BLE001
        pass
    try:
        out.append("page title: %s" % page.title())
    except Exception:  # noqa: BLE001
        pass
    try:
        body = page.evaluate(
            "() => (document.body && document.body.innerText || '')"
            ".replace(/\\s+/g, ' ').trim().slice(0, 400)")
        out.append("page text: %s" % body)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(out)


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
            "OwnerVille password, open Lucy Reports and enter the new one. "
            "(%s)" % type(e).__name__)

    rqst = K.capture_rqst(page)
    if not rqst:
        raise KnocksProblem(
            "Signed in to OwnerVille but it did not open a working session. "
            "Nothing is lost — the next run tries again.")
    return rqst


def _has_session(p, log=print) -> bool:
    """Cheap headless probe: is the profile's OwnerVille session still live?"""
    ctx = _context(p, True)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        return bool(K.capture_rqst(page))
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass


def read_knocks(day: Optional[dt.date] = None, *, headless: bool = True,
                campaign: str = "",
                log=print) -> Dict[str, List[Dict]]:
    """Today's grid AND time tracker for this office, both raw.

    {'rows': [...], 'time_tracker': [...]}. The gaps live in the second one --
    the disposition grid has no idea how long a rep stood still -- and a board
    without them reads as "nobody was idle" rather than "we did not look".
    """
    from patchright.sync_api import sync_playwright

    day = day or C.today()
    mdy = day.strftime("%m/%d/%Y")      # NOT %-m/%-d: that is not portable

    with sync_playwright() as p:
        # A window ONLY when one is actually needed. The security check on the
        # password step never clears for a headless browser, so a lapsed
        # session has to be re-established in a visible one -- but that is the
        # rare case, and making every sweep visible would put a browser on the
        # owner's screen four times an hour for no reason.
        show = headless and not _has_session(p, log=log)
        if show:
            log("OwnerVille needs signing in again — opening a window briefly")
        ctx = _context(p, headless and not show)
        # KEEP WHAT THE READ SAW. When the grid never appears, the traceback
        # says only that -- and from a laptop we cannot open, that was the
        # whole story. Jamis (2026-10-06): signed in, campaigns pinned, no
        # table, for four hours, while the same office impersonated from
        # Lucy 2 served its grid at once. The log lines, the URL the page
        # ended on and the first words of its body are the difference.
        seen: List[str] = []

        def _l(msg: str) -> None:
            seen.append(str(msg))
            log(msg)

        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            rqst = _session(page, log=_l)
            # PIN THE CAMPAIGN FIRST. The campaign is a sticky session-global
            # in OwnerVille, so an unpinned read on a multi-campaign owner
            # returns whatever THEY last clicked. Whether the grid that
            # arrives really is that campaign's is checked on our side,
            # against the rows -- a pin can fail to take and still serve a
            # grid (Calvin, 2026-09-02).
            cid = C.CAMPAIGN_IDS.get((campaign or "").strip().lower()) \
                if campaign else C.campaign_id()
            if cid:
                K.pin_campaign(page, rqst, cid, log=_l)
            K.navigate(page, rqst, mdy, log=_l)
            try:
                rows = K.read_rows(page, log=_l)
            except K.OwnervilleError as e:
                problem = KnocksProblem(
                    "%s (what the page showed is in the fault detail)" % e)
                problem.seen = _page_evidence(page, seen)
                raise problem
            # Never fatal: the disposition half is still worth handing over,
            # and losing the whole board because the gaps endpoint blipped
            # would be the wrong trade.
            try:
                tracker = K.fetch_time_tracker(page, rqst, mdy, log=log)
            except Exception as e:  # noqa: BLE001
                log("time tracker failed (%s) — gaps will be blank"
                    % type(e).__name__)
                tracker = []
            return {"rows": rows, "time_tracker": tracker}
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass

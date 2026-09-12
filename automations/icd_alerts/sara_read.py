"""Log into THIS machine's SaraPlus account and read today's numbers.

THREE PASSES, the same three the AO office makes, because no single service
filter carries every measure:

  1. 'AT&T'          -> Internet Sales / Internet Upgrades / AIA / Wireless Lines
  2. 'All'           -> DTV Streaming   (the AT&T-filtered grid always says 0)
  3. 'AT&T Internet' -> Records, i.e. credit checks

It started as one pass -- credit checks only -- and grew the other two when
Megan asked for sales as well (2026-09-12: "it should work exactly like the AO
workspace"). All three run in ONE browser session: the login is the expensive
part and doing it three times would treble the cost of a sweep that now fires
every three minutes.

Every selector, column index and row marker comes from
automations.shared.saraplus. Nothing here re-derives them: every SaraPlus is
the same, so a change to the site is a change in one file, for all 52 offices.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

from automations.shared import saraplus as S
from automations.icd_alerts import config as C


class AccountProblem(RuntimeError):
    """Something the ICD can fix, phrased for the ICD."""


def _context(p, headless: bool):
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"])
    if not headless:
        # Only when a person can actually see it. On the scheduled run this is
        # headless and nothing appears on their screen at all.
        from automations.shared import browser_banner
        browser_banner.attach(ctx)
    return ctx


def _sign_in(page, log=print) -> str:
    """Sign in, returning the dealer root. Re-raises login trouble as something
    an owner can act on -- a password change is the common case and reads as a
    bounce back to the login page, not as an error."""
    cr = C.creds()
    try:
        return S._login(page, cr["email"], cr["password"])
    except S.SaraError as e:
        msg = str(e)
        if "still on the login page" in msg:
            raise AccountProblem(
                "SaraPlus did not accept that email and password. If you "
                "recently changed your SaraPlus password, open the alerts app "
                "and enter the new one.")
        raise AccountProblem(
            "Could not finish signing in to SaraPlus. %s" % msg)


def check_account(*, headless: bool = True, log=print) -> Dict:
    """STEP ONE of the app: can this login actually read reports?

    Answers, read-only, in a single pass: does the login work, does this
    account have the Reporting Hub, and does the credit-check grid come back.
    Nothing is stored and nothing is relayed -- an owner can run this before
    deciding to take part at all.

    Returns {'ok': bool, 'message': str, 'reps': int, 'landed': str}.
    """
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _context(p, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = _sign_in(page, log=log)
            log("signed in: %s" % base)

            # The Reporting Hub is a SIBLING of DealerPages, not a child. A bad
            # path is served as 404.aspx -- a real page -- so the failure would
            # otherwise surface 90 seconds later as a missing dropdown.
            page.goto(base + S.HUB_PATH, wait_until="networkidle",
                      timeout=S.NAV_TIMEOUT_MS)
            try:
                S._assert_on_hub(page, base)
            except S.SaraError:
                return {
                    "ok": False,
                    "landed": page.url,
                    "reps": 0,
                    "message": (
                        "This SaraPlus account can sign in, but it has no "
                        "reporting access -- there is nothing for the alerts to "
                        "read. Ask your SaraPlus admin for an owner account "
                        "with the Reporting Hub."),
                }

            rows = S._run_report(page, base, C.today(), C.SERVICE_INTERNET,
                                 S.GRID_INTERNET, log=log)
            records = S.parse_records(rows)
            return {
                "ok": True,
                "landed": page.url,
                "reps": len(records),
                "message": (
                    "Your SaraPlus account is good to go. Credit checks are "
                    "readable for %d rep(s) today." % len(records)),
            }
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def read_day(day: Optional[dt.date] = None, *, headless: bool = True,
             log=print) -> Dict:
    """{'records': {REP: credit checks}, 'sales': {REP: {Int, Int Up, DTV, NL}}}.

    ONE SESSION, THREE PASSES. A failure in the sales half must not cost the
    credit checks: they are the faster-moving alert and the one this started
    as, so they are read FIRST and the other two are allowed to come back
    empty. An office whose grid has no AT&T rows yet still gets its pings.
    """
    from patchright.sync_api import sync_playwright
    from automations.shared import sale_hype as H

    day = day or C.today()
    with sync_playwright() as p:
        ctx = _context(p, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = _sign_in(page, log=log)

            records = S.parse_records(
                S._run_report(page, base, day, C.SERVICE_INTERNET,
                              S.GRID_INTERNET, log=log))
            log("credit-check pass: %d rep(s)" % len(records))

            sales = {}
            try:
                agents = S.parse_att(
                    S._run_report(page, base, day, "AT&T", S.GRID_ATT, log=log))
                log("AT&T pass: %d rep(s)" % len(agents))
                dtv = S.parse_dtv(
                    S._run_report(page, base, day, "All", S.GRID_ALL, log=log))
                log("All pass: DTV for %d rep(s)" % len(dtv))
                for a in S.merge_dtv(agents, dtv):
                    name = S.strip_office(a.get("name"))
                    if name:
                        sales[name] = H.metrics_for(a)
            except Exception as e:  # noqa: BLE001 — credit checks still stand
                log("sales passes failed (%s) — credit checks are unaffected"
                    % type(e).__name__)

            return {"records": records, "sales": sales}
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def read_records(day: Optional[dt.date] = None, *, headless: bool = True,
                 log=print) -> Dict[str, int]:
    """Credit checks only. Kept for `--check` and anything that wants the
    cheap read."""
    return read_day(day, headless=headless, log=log)["records"]

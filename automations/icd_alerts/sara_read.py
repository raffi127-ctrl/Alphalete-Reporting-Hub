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


def _sign_in_raw(page, log=print) -> str:
    """The login, with SaraPlus's own exception classes intact.

    UNTRANSLATED ON PURPOSE: _heal_and_login has to tell a stuck profile from
    a real password demand, and that difference lives in the exception CLASS.
    Translating here would flatten both into one AccountProblem and make the
    heal impossible to trigger.
    """
    cr = C.creds()
    return S._login(page, cr["email"], cr["password"],
                    creds_hint="the SaraPlus login saved on this computer",
                    log=log)


def _sign_in(page, log=print, interactive: bool = False) -> str:
    """Sign in, returning the dealer root, with trouble phrased for an owner.

    INTERACTIVE is kept in the signature because the human paths pass it; it
    no longer changes the login. It used to carry a passcode prompt, from when
    /security/ was modelled as an emailed browser challenge; that model is
    gone [[_heal_and_login]].
    """
    try:
        return _sign_in_raw(page, log=log)
    except S.SaraError as e:
        raise _as_owner_problem(e) from e


def _as_owner_problem(e: Exception) -> "AccountProblem":
    """Translate SaraPlus's own words into the one action an owner can take.

    The shared messages are written for US -- they name Chrome profiles,
    set_credentials and password character rules. An ICD in another state can
    act on exactly two things: re-enter the password, or tell us. So that is
    all this says.
    """
    msg = str(e)
    change_required = getattr(S, "SaraPasswordChangeRequired", None)
    wall = getattr(S, "SaraPasswordWall", None)
    if change_required is not None and isinstance(e, change_required):
        return AccountProblem(
            "SaraPlus is asking for a NEW password on this account — it does "
            "that every few weeks, and it is not a fault.\n\n"
            "Sign in to SaraPlus in your normal browser, set a new password, "
            "then open the alerts app and run the password step so this "
            "computer knows it too.")
    if wall is not None and isinstance(e, wall):
        # Should not escape _heal_and_login, which rotates the profile and
        # retries. If it does, say the true thing rather than blaming the
        # password -- that mistake cost a day on 2026-09-12.
        return AccountProblem(
            "SaraPlus would not open past its Change Password page on this "
            "computer. Nothing was read and nothing was changed — please tell "
            "Megan & Eve, this one is ours to fix.")
    if "still on the login page" in msg:
        return AccountProblem(
            "SaraPlus did not accept that email and password. If you recently "
            "changed your SaraPlus password, open the alerts app and enter "
            "the new one.")
    return AccountProblem("Could not finish signing in to SaraPlus. %s" % msg)


def _heal_and_login(p, headless: bool, log=print):
    """Open a context, sign in, and HEAL a stuck Chrome profile by itself.

    Returns (ctx, page, base). The caller owns ctx and must close it.

    WHY THIS IS NOT saraplus.login_healing, which does the same job: that one
    opens its own context, and this one has to attach the red DO-NOT-TOUCH
    banner BEFORE the login page loads. Attaching it afterwards would leave
    the sign-in -- the exact moment somebody is tempted to "help" by typing
    their password or clearing Cloudflare -- as the one unbannered page.

    The heal itself is the shared rule, and the reasoning belongs to
    saraplus._stuck_profile_error: SaraPlus's Change Password page is usually
    a WEDGED BROWSER PROFILE, not an expired account, and throwing the profile
    away and trying once more is what tells the two apart. An ICD laptop is
    the best possible place for that to happen by itself -- nobody is sitting
    there, and the alternative is an office silently dark until somebody
    notices.
    """
    def _open():
        ctx = _context(p, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return ctx, page, _sign_in_raw(page, log=log)
        except Exception:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
            raise

    wall = getattr(S, "SaraPasswordWall", None)
    try:
        return _open()
    except S.SaraError as first:
        if wall is None or not isinstance(first, wall):
            raise _as_owner_problem(first) from first
        log("SaraPlus served its Change Password page -- testing whether it "
            "is this profile or the account")
        S.rotate_profile(C.PROFILE_DIR, log=log)
        try:
            return _open()
        except S.SaraError as second:
            if isinstance(second, wall):
                # A BRAND-NEW EMPTY PROFILE HIT THE SAME PAGE. That is the one
                # thing that rules out a wedged profile, so this is the real
                # every-few-weeks reset and it needs the owner, not us.
                raise _as_owner_problem(
                    S.SaraPasswordChangeRequired(str(second))) from second
            raise _as_owner_problem(second) from second


def check_account(*, headless: bool = True, log=print,
                  interactive: bool = False) -> Dict:
    """STEP ONE of the app: can this login actually read reports?

    Answers, read-only, in a single pass: does the login work, does this
    account have the Reporting Hub, and does the credit-check grid come back.
    Nothing is stored and nothing is relayed -- an owner can run this before
    deciding to take part at all.

    Returns {'ok': bool, 'message': str, 'reps': int, 'landed': str}.
    """
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx, page, base = _heal_and_login(p, headless, log=log)
        try:
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
        ctx, page, base = _heal_and_login(p, headless, log=log)
        try:

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

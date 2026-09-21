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


class SignInInProgress(RuntimeError):
    """Somebody is at this machine finishing a SaraPlus sign-in. Not a fault,
    and NOT a day with no sales -- there is simply nothing to send yet."""


def signin_in_progress() -> bool:
    """Is somebody at a SaraPlus sign-in window right now?

    They are typing into the SAME Chrome profile the sweep opens, and Chromium
    will not open one profile twice -- so without this the sweep races a person
    who is part-way through a passcode challenge and neither of them wins.

    A STALE LOCK IS IGNORED, on the box_read rule: a crashed sign-in must not
    mute this office for the rest of the afternoon. The failure mode of a
    forgotten lock has to be noise, never silence.
    """
    try:
        held = dt.datetime.fromisoformat(
            C.SARA_SIGNIN_LOCK.read_text().strip())
    except (OSError, ValueError):
        return False
    return (dt.datetime.now() - held) < dt.timedelta(
        minutes=C.SARA_SIGNIN_LOCK_MINUTES)


# WHAT THIS BROWSER CALLS ITSELF, once SaraPlus has ever asked who it is.
#
# The scheduled read runs Chrome hidden, and hidden Chrome tells every site it
# is "HeadlessChrome/148.0.7778.96". The sign-in window a person uses is
# visible, and says "Chrome/148.0.0.0". Same profile folder, same cookies --
# and to a site that fingerprints the browser, two different computers.
#
# Khalil, 2026-09-21: Francia cleared SaraPlus's emailed-code check in the
# visible window at 9:24, closed it at 9:55, and the hidden read hit the same
# check at 10:05. Four other offices read as HeadlessChrome every day and are
# never asked, so this is NOT applied everywhere: changing what a trusted
# machine calls itself is exactly how you get it asked again.
#
# So a machine switches only after SaraPlus has challenged it, and from then
# on every launch -- hidden or visible -- presents the one identity a person
# has vouched for. Written when the check is hit, and again when a sign-in
# window succeeds.
BROWSER_ID_PATH = C.APP_DIR / "sara-browser-id.txt"
_LAST_UA = {"ua": ""}


def _as_visible_chrome(ua: str) -> str:
    """'...HeadlessChrome/148.0.7778.96 ...' -> '...Chrome/148.0.0.0 ...' --
    exactly what the same Chrome reports when it has a window."""
    import re
    return re.sub(r"HeadlessChrome/(\d+)[\d.]*", r"Chrome/\1.0.0.0", ua or "")


def browser_id() -> str:
    try:
        return BROWSER_ID_PATH.read_text().strip()
    except OSError:
        return ""


def remember_browser_id(ua: str, log=print) -> None:
    ua = _as_visible_chrome(ua).strip()
    if not ua or "Chrome/" not in ua:
        return
    try:
        BROWSER_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        if BROWSER_ID_PATH.exists() and browser_id() == ua:
            return
        BROWSER_ID_PATH.write_text(ua)
        log("SaraPlus has challenged this browser -- every launch now presents "
            "itself the way the sign-in window does")
    except OSError:
        pass


def _context(p, headless: bool):
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    kw = {"headless": headless, "args": ["--disable-sync"]}
    known = browser_id()
    if known:
        kw["user_agent"] = known
    ctx = p.chromium.launch_persistent_context(str(C.PROFILE_DIR), **kw)
    if not known:
        # Kept, in case SaraPlus challenges this launch and we need to say
        # what the visible version of it is.
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            _LAST_UA["ua"] = pg.evaluate("() => navigator.userAgent") or ""
        except Exception:  # noqa: BLE001 -- never cost the read for this
            pass
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
    passcode = getattr(S, "SaraPasscodeWall", None)
    if passcode is not None and isinstance(e, passcode):
        return AccountProblem(
            "SaraPlus wants to confirm this computer with a code it emails "
            "you. Your password is fine — do NOT change it.\n\n"
            "A SaraPlus window opens on this computer by itself when someone "
            "is at it. Sign in THERE and type in the emailed code — signing "
            "in from your normal browser does not count.")
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
    passcode = getattr(S, "SaraPasscodeWall", None)
    try:
        return _open()
    except S.SaraError as first:
        if passcode is not None and isinstance(first, passcode):
            # From the next launch on, look like the window a person clears
            # the check in. Nothing else changes; the check still has to be
            # cleared once.
            remember_browser_id(_LAST_UA["ua"], log=log)
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


def _report_sales_fault(summary: str, log=print) -> None:
    """Tell us the sales half is broken. Best effort, never raises.

    Separate from the sweep's own error path because this is NOT a failed
    run: the credit checks came back and the office keeps its alerts. It is
    a half-outage, and the whole point is that a half-outage is invisible.
    """
    try:
        from automations.icd_alerts import relay as R
        R.report_fault("sales", summary, log=log)
    except Exception:  # noqa: BLE001 — a reporter that throws is worse
        log("could not report the sales fault")


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
    if signin_in_progress():
        # NOT an error, and nothing is lost: the next tick is two minutes
        # away. Taking the profile now would close the window under somebody
        # mid-passcode and leave them certain they had done it wrong.
        #
        # RAISED, NOT AN EMPTY DAY. This used to return {"records": {},
        # "sales": {}}, and cmd_once relays whatever it is handed -- so every
        # pass spent standing back sent "nobody ran a credit check, nobody
        # sold anything" as the day's real totals. Khalil's relay showed 0/0
        # on 9/17, 9/18 and 9/19 while his NDS order log had 23, 24 and 29
        # orders, and it read as a broken SaraPlus read for two days. It was
        # never a read at all: he had not got in once. box_read raises for
        # exactly this and cmd_box returns without sending; this now matches.
        log("someone is signing in to SaraPlus — standing back this pass")
        raise SignInInProgress("a SaraPlus sign-in window is open")
    with sync_playwright() as p:
        ctx, page, base = _heal_and_login(p, headless, log=log)
        try:

            records = S.parse_records(
                S._run_report(page, base, day, C.SERVICE_INTERNET,
                              S.GRID_INTERNET, log=log))
            log("credit-check pass: %d rep(s)" % len(records))

            sales = {}
            try:
                att_rows = S._run_report(page, base, day, "AT&T",
                                         S.GRID_ATT, log=log)
                # IS THIS GRID STILL THE SHAPE WE READ? Every column below
                # is a fixed index. Every SaraPlus account has the same
                # layout (Megan 2026-09-15), which is what makes this worth
                # checking at all: a change to it is not one office's
                # problem, it is every office at once, and a grid we cannot
                # parse reads as a day with no sales rather than as a fault.
                #
                # ASKED TWICE BEFORE IT IS BELIEVED. The first thing this
                # ever caught was Carlos's grid coming back as nine rows all
                # marked History, with no Company, Location or Agent rows at
                # all (2026-09-16) -- which is not a layout that exists, it
                # is a page that had not finished rendering. SaraPlus is slow
                # enough that _run_report already retries its own timeouts
                # for exactly this reason.
                #
                # A half-rendered grid and a moved column look identical from
                # here, and only one of them is worth waking somebody for. So
                # re-read once: a transient will not survive it, and a real
                # change will.
                problem = S.att_shape_problem(att_rows)
                if problem:
                    log("sales grid looks wrong (%s) — reading it again"
                        % problem[:60])
                    att_rows = S._run_report(page, base, day, "AT&T",
                                             S.GRID_ATT, log=log)
                    problem = S.att_shape_problem(att_rows)
                    if problem:
                        _report_sales_fault(problem, log=log)
                    else:
                        log("second read was fine — the first was still "
                            "rendering, not a fault")
                agents = S.parse_att(att_rows)
                log("AT&T pass: %d rep(s)" % len(agents))
                dtv = S.parse_dtv(
                    S._run_report(page, base, day, "All", S.GRID_ALL, log=log))
                log("All pass: DTV for %d rep(s)" % len(dtv))
                for a in S.merge_dtv(agents, dtv):
                    name = S.strip_office(a.get("name"))
                    if name:
                        sales[name] = H.metrics_for(a)
            except Exception as e:  # noqa: BLE001 — credit checks still stand
                # LOGGED IS NOT REPORTED. This wrote one line into a log file
                # on a laptop in another state and told us nothing, so an
                # office whose sales half never worked looked exactly like an
                # office having a slow week -- for as long as it took somebody
                # to wonder. The credit checks genuinely are unaffected, which
                # is why this is not fatal; it is still a fault.
                log("sales passes failed (%s) — credit checks are unaffected"
                    % type(e).__name__)
                _report_sales_fault(
                    "the sales half of the SaraPlus read failed (%s: %s). "
                    "Credit checks are still working."
                    % (type(e).__name__, str(e)[:160]), log=log)

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

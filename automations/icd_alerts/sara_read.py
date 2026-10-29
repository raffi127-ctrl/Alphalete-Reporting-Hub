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

import re
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
        # AND THE FULL BROWSER, not the stripped one. Matching the name was
        # not enough: on 2026-09-21 Khalil's visible window was trusted and
        # the hidden read, presenting the identical name, was still asked for
        # the code. The hidden default is Playwright's "headless shell" -- 0
        # plugins, no window.chrome, no WebGL, 0 media types -- which any
        # fingerprint tells apart from the window a person used. channel=
        # "chromium" runs the real Chrome hidden, and matched the visible
        # window on every one of those, measured before this was written.
        # Only for a machine SaraPlus has challenged, like the name.
        if headless:
            kw["channel"] = "chromium"
    try:
        ctx = p.chromium.launch_persistent_context(str(C.PROFILE_DIR), **kw)
    except Exception:  # noqa: BLE001 -- full Chrome missing: read as before
        if "channel" not in kw:
            raise
        kw.pop("channel")
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
    # RESUME FIRST, LOG IN SECOND. The dealer root from the last successful
    # login is kept next to the profile; if SaraPlus still honours it, no
    # password is typed this sweep (see saraplus.resume_session). Only when
    # it does not -- a new day, a kicked session, a rotated profile -- does
    # the real login run, and its root is remembered for the next sweep.
    remembered = _remembered_session()
    if remembered:
        base = S.resume_session(page, remembered, log=log)
        if base:
            return base
        note_trust("session-lost", page, log=log)
        _forget_session()
    if _RESUME_ONLY["on"]:
        raise SessionLost(
            "SaraPlus session expired (%s) and this read must not log in"
            % ("was %s old" % _age_text(_session_since()) if _session_since()
               else "none remembered"))
    try:
        base = S._login(page, cr["email"], cr["password"],
                        creds_hint="the SaraPlus login saved on this computer",
                        log=log)
    except Exception as e:  # noqa: BLE001 -- only the login-page timeout is ours
        if _is_login_timeout(e):
            n = _note_login_timeout()
            if n >= LOGIN_TIMEOUTS_BEFORE_HOLD:
                raise AccountProblem(LOGIN_TIMEOUT_MESSAGE % n) from e
        raise
    _clear_login_timeouts()
    _remember_session(base)
    note_trust("fresh-login-ok", page, log=log)
    return base


# A LOGIN PAGE THAT NEVER FINISHES LOADING. Cyrus's laptop, 2026-09-29 ->
# 10-01: 148, 214 and 115 sweeps a day, every one a 30-second timeout on the
# login button, no hold between them because a TimeoutError is not an
# AccountProblem. Hundreds of half-logins a day is how a slow link earns a
# throttle. After a few in a row it becomes the owner's problem: the same
# hold the passcode wall gets, and the sign-in window offered to whoever is
# at the machine so a person can SEE what SaraPlus is doing from there.
#
# NOT "CHECK YOUR INTERNET". The page opens fine -- the email and password go
# in -- it is the press of Login that never comes back. Cyrus, 2026-09-26 ->
# 10-05: 75 in a row, starting the evening SaraPlus made him set a new
# password, while the same laptop relayed OwnerVille knocks all day. Telling
# him to check his wifi sent him after the one thing that was working.
LOGIN_TIMEOUTS_BEFORE_HOLD = 3
LOGIN_TIMEOUT_MESSAGE = (
    "SaraPlus will not finish signing in from this computer -- %d times in a "
    "row, pressing Login never got through. Your internet is fine. This "
    "usually starts after a SaraPlus password change.\n\nA SaraPlus window "
    "opens on this computer by itself when someone is at it: sign in there "
    "once (and set a new password or enter the code if it asks), then put "
    "the same password in the Lucy Reports app.")
LOGIN_TIMEOUTS_PATH = C.APP_DIR / "saraplus-login-timeouts.txt"


def _is_login_timeout(e: Exception) -> bool:
    return type(e).__name__ == "TimeoutError"


def _note_login_timeout() -> int:
    try:
        n = int((LOGIN_TIMEOUTS_PATH.read_text() or "0").strip() or 0)
    except (OSError, ValueError):
        n = 0
    n += 1
    try:
        LOGIN_TIMEOUTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOGIN_TIMEOUTS_PATH.write_text(str(n))
    except OSError:
        pass
    return n


def _clear_login_timeouts() -> None:
    try:
        LOGIN_TIMEOUTS_PATH.unlink()
    except OSError:
        pass


SESSION_PATH = C.APP_DIR / "saraplus-session.txt"


def _remembered_session() -> str:
    try:
        return SESSION_PATH.read_text().strip()
    except OSError:
        return ""


SESSION_SINCE_PATH = C.APP_DIR / "saraplus-session-since.txt"


def _remember_session(base: str) -> None:
    try:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(base or "")
        # WHEN THIS SESSION WAS BORN, so a wall can say how old the session
        # it replaced was -- the one fact that tells an idle timeout from a
        # hard lifetime (2026-10-08: every office's wall lands 2-4am and
        # nobody could say whether the keep-alive had been touching it).
        SESSION_SINCE_PATH.write_text(dt.datetime.now().isoformat(timespec="seconds"))
    except OSError:
        pass


def _session_since() -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(SESSION_SINCE_PATH.read_text().strip())
    except (OSError, ValueError):
        return None


# RESUME ONLY, NEVER A LOGIN -- for the overnight catch-up. A fresh headless
# login at 2am is exactly what earns the emailed-code wall with nobody at the
# Mac (Luke 01:37 / 04:00 / 04:33, Rashad 02:02, Carlos 02:00, 2026-10-07/08).
# read_day(resume_only=True) makes _sign_in_raw raise SessionLost instead of
# typing the password; the catch-up stays owed and runs on the first sweep of
# the day, when a wall at least opens the window in front of a person.
_RESUME_ONLY = {"on": False}


class SessionLost(RuntimeError):
    """The remembered session is gone and this read was told not to log in."""


def _forget_session() -> None:
    try:
        SESSION_PATH.unlink()
    except OSError:
        pass


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
        if "page says: REJECTED" in msg:
            return AccountProblem(
                "SaraPlus did not accept that email and password. If you recently "
                "changed your SaraPlus password, open the alerts app and enter "
                "the new one.")
        if "page says: nothing" in msg:
            # THE PAGE SHOWED NO ERROR. A wrong password gets "Invalid login"
            # on the page; a bounce with no message is the redirect not
            # landing, which is ours. Telling an owner to re-enter a good
            # password costs a password change that fixes nothing (Khalil,
            # 2026-09-21, told this 123 times over a timing bug of ours).
            return AccountProblem(
                "SaraPlus sent the login page back without saying why -- "
                "the password was not rejected. Nothing was read. Please do "
                "NOT change your password; tell Megan & Eve, this one is "
                "ours to look at.")
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
        except Exception as e:
            pw = getattr(S, "SaraPasscodeWall", None)
            if pw is not None and isinstance(e, pw):
                note_trust("code-wall", ctx, log=log)
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
        _forget_session()
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


SARA_HOLD_PATH = C.APP_DIR / "sara-hold-until.txt"
SARA_HOLD_MINUTES = 30


def hold_sara(minutes: int = SARA_HOLD_MINUTES, log=print) -> None:
    """After SaraPlus refuses a login, stand back for a while.

    THE AGENT USED TO TRY AGAIN EVERY SWEEP. Khalil's machine: 115 walled
    logins on 2026-09-17, 123 on 2026-09-21, 10 an hour today -- and by
    mid-morning SaraPlus answered the same password with "invalid
    email/password" until a person signed in by hand and reset it, after
    which the next hidden attempt was walled again, not refused. Hammering
    the login page is how a fixable wall turns into a throttle, and it burns
    the fix the moment somebody makes it. One report, then thirty minutes
    of quiet. The sign-in link clears the hold, so a person's fix is tried
    at once, not half an hour later.
    """
    until = dt.datetime.now() + dt.timedelta(minutes=minutes)
    try:
        SARA_HOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
        SARA_HOLD_PATH.write_text(until.isoformat(timespec="seconds"))
    except OSError:
        return
    log("SaraPlus refused this login; not trying again until %s"
        % until.strftime("%H:%M"))


def sara_held_until():
    """The time the current hold ends, or None when there is no hold."""
    try:
        until = dt.datetime.fromisoformat(SARA_HOLD_PATH.read_text().strip())
    except (OSError, ValueError):
        return None
    if until <= dt.datetime.now():
        clear_sara_hold()
        return None
    return until


def clear_sara_hold() -> None:
    try:
        SARA_HOLD_PATH.unlink()
    except OSError:
        pass


def what_saraplus_sees(ctx, page) -> list:
    """What this browser presents to SaraPlus, one line each -- so a photo of
    the sign-in window shows WHY the hidden read is not trusted when the
    visible one is (Khalil, 2026-09-21/22: visible window trusted, hidden
    read walled, same profile, same name). Cookie NAMES only, never values.
    Never raises: a fake page in tests, or a closed tab, just yields less.
    """
    out = []
    try:
        cks = [c for c in ctx.cookies() if "saraplus" in (c.get("domain") or "")]
        out.append("cookies for saraplus (%d): %s" % (len(cks), ", ".join(
            "%s%s" % (c.get("name"), "" if c.get("expires", -1) not in (-1, None, 0)
                      else "[session]") for c in cks) or "none"))
    except Exception as e:  # noqa: BLE001
        out.append("cookies: could not read (%s)" % type(e).__name__)
    try:
        fp = page.evaluate("""() => ({
            ua: navigator.userAgent,
            screen: screen.width + 'x' + screen.height,
            window: innerWidth + 'x' + innerHeight,
            plugins: navigator.plugins.length,
            chrome: !!window.chrome,
            webdriver: navigator.webdriver,
            tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
            lang: navigator.languages.join(','),
            storage: Object.keys(localStorage).slice(0, 12).join(','),
            webgl: (() => { try { const c = document.createElement('canvas');
              const g = c.getContext('webgl'); const d = g.getExtension('WEBGL_debug_renderer_info');
              return d ? g.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'n/a'; } catch (e) { return 'err'; } })()
        })""")
        for k in ("ua", "screen", "window", "plugins", "chrome", "webdriver",
                  "tz", "lang", "webgl", "storage"):
            out.append("%s: %s" % (k, fp.get(k)))
    except Exception as e:  # noqa: BLE001
        out.append("fingerprint: could not read (%s)" % type(e).__name__)
    return out


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
        try:
            ctx, page, base = _heal_and_login(p, headless, log=log)
        except AccountProblem as e:
            # SAY WHAT THIS BROWSER PRESENTED, on the way out. The verdict
            # alone ("wants a code") has been the same for two days; the
            # difference from the trusted window is the whole question.
            try:
                probe_ctx = _context(p, headless)
                pg = probe_ctx.pages[0] if probe_ctx.pages else probe_ctx.new_page()
                pg.goto(S.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                e.presented = what_saraplus_sees(probe_ctx, pg)
                probe_ctx.close()
            except Exception:  # noqa: BLE001
                pass
            raise
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


KEEPALIVE_PATH = C.APP_DIR / "saraplus-keepalive.txt"
KEEPALIVE_EVERY_MIN = 10
# What every keep-alive did, newest last, so a wall can show the night.
KEEPALIVE_LOG_PATH = C.APP_DIR / "saraplus-keepalive-log.json"
KEEPALIVE_LOG_KEEP = 60


def _age_text(since: Optional[dt.datetime], now: Optional[dt.datetime] = None) -> str:
    if since is None:
        return "?"
    mins = int(((now or dt.datetime.now()) - since).total_seconds() // 60)
    return "%dh%02dm" % divmod(max(mins, 0), 60)


def _note_keepalive(result: str, now: dt.datetime) -> None:
    try:
        import json
        try:
            rows = json.loads(KEEPALIVE_LOG_PATH.read_text())
        except (OSError, ValueError):
            rows = []
        if not isinstance(rows, list):
            rows = []
        rows.append({"t": now.isoformat(timespec="seconds"), "r": result,
                     "age": _age_text(_session_since(), now)})
        KEEPALIVE_LOG_PATH.write_text(json.dumps(rows[-KEEPALIVE_LOG_KEEP:]))
    except OSError:
        pass


def session_evidence(now: Optional[dt.datetime] = None) -> str:
    """For a fault's detail: how old the session is (or was) and what the
    keep-alive did lately. Best effort, never raises."""
    now = now or dt.datetime.now()
    out = ["session evidence:"]
    since = _session_since()
    out.append("  remembered session: %s (since %s)"
               % ("yes" if _remembered_session() else "no",
                  since.isoformat(timespec="minutes") if since else "?"))
    if since:
        out.append("  session age: %s" % _age_text(since, now))
    try:
        import json
        rows = json.loads(KEEPALIVE_LOG_PATH.read_text())
        tail = rows[-14:] if isinstance(rows, list) else []
        out.append("  keep-alive (last %d): %s" % (len(tail), ", ".join(
            "%s %s@%s" % (r.get("t", "")[11:16], r.get("r"), r.get("age")) for r in tail)))
    except (OSError, ValueError):
        out.append("  keep-alive: no log")
    return "\n".join(out)


# WHY SOME MACHINES ARE NEVER REMEMBERED (Megan 2026-10-24, Tre). Tre,
# Rashad, carlos-b2batt, Luke, Eveliz and Cyrus get the emailed-code wall on
# every fresh login; the other offices never do. Every sign-in window that
# cleared the code left only .ASPXAUTH and a session-only SARAPlus cookie --
# no lasting "trusted" mark -- and nobody can say whether SaraPlus keys its
# trust on the network ("new location") or the browser. So at each moment
# that matters -- a fresh login that got in, a wall, a session SaraPlus
# stopped honouring -- the machine files what it looked like: its SaraPlus
# cookies (names and expiry dates, NEVER values) and a hash of its public
# IP, which shows a changed network without sending the address itself.
# A probe- stage: filed on the ICD Faults tab, never posted.
TRUST_STAGE = "probe-sara-trust"
TRUST_IP_LOG_PATH = C.APP_DIR / "sara-ip-history.json"
TRUST_IP_LOG_KEEP = 12
IP_LOOKUP_URL = "https://api.ipify.org"
_IP_CACHE: Dict = {}


def _ip_hash(now: dt.datetime) -> str:
    """A short hash of this machine's public IP, cached 10 minutes. '?' when
    the lookup fails -- never raises, never takes more than a few seconds."""
    got = _IP_CACHE.get("v")
    if got and (now - _IP_CACHE["at"]) < dt.timedelta(minutes=10):
        return got
    try:
        import hashlib
        import urllib.request
        from automations.icd_alerts import relay as R
        with urllib.request.urlopen(IP_LOOKUP_URL, timeout=4,
                                    context=R._ssl_context()) as r:
            ip = r.read(64).decode("ascii", "replace").strip()
        if not ip:
            return "?"
        got = hashlib.sha256(("lucy-sara|" + ip).encode()).hexdigest()[:10]
    except Exception:  # noqa: BLE001
        return "?"
    _IP_CACHE.update(v=got, at=now)
    return got


def _ip_history(h: str, now: dt.datetime) -> list:
    """This machine's IP hashes over time, newest last; a new row only when it
    changed. Kept on the machine, sent inside each trust probe."""
    import json
    try:
        rows = json.loads(TRUST_IP_LOG_PATH.read_text())
        if not isinstance(rows, list):
            rows = []
    except (OSError, ValueError):
        rows = []
    if h != "?" and (not rows or rows[-1].get("ip") != h):
        rows.append({"t": now.isoformat(timespec="minutes"), "ip": h})
        rows = rows[-TRUST_IP_LOG_KEEP:]
        try:
            TRUST_IP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            TRUST_IP_LOG_PATH.write_text(json.dumps(rows))
        except OSError:
            pass
    return rows


def _cookie_lines(ctx, now: dt.datetime) -> list:
    """Every saraplus cookie: name, domain, and when it dies. No values."""
    out = []
    for c in ctx.cookies():
        dom = c.get("domain") or ""
        if "saraplus" not in dom:
            continue
        exp = c.get("expires", -1)
        if exp in (-1, None, 0):
            when = "session-only"
        else:
            try:
                left = dt.datetime.fromtimestamp(exp) - now
                when = "expires %s (in %dd)" % (
                    dt.datetime.fromtimestamp(exp).strftime("%Y-%m-%d"), left.days)
            except (OverflowError, OSError, ValueError):
                when = "expires ?"
        out.append("  %s @ %s: %s" % (c.get("name"), dom, when))
    return out or ["  (no saraplus cookies)"]


def trust_snapshot(event: str, ctx, now: Optional[dt.datetime] = None) -> str:
    """The detail text for one trust probe. Best effort, never raises."""
    now = now or dt.datetime.now()
    out = ["event: %s at %s" % (event, now.isoformat(timespec="seconds"))]
    try:
        h = _ip_hash(now)
        out.append("ip hash now: %s" % h)
        out.append("ip history: " + (", ".join(
            "%s %s" % (r.get("t", "")[5:16], r.get("ip")) for r in _ip_history(h, now))
            or "none yet"))
    except Exception as e:  # noqa: BLE001
        out.append("ip: ? (%s)" % type(e).__name__)
    out.append("browser id pinned: %s" % ("yes" if browser_id() else "no"))
    try:
        out.append("cookies:")
        out.extend(_cookie_lines(ctx, now))
    except Exception as e:  # noqa: BLE001
        out.append("cookies: ? (%s)" % type(e).__name__)
    out.append(session_evidence(now))
    return "\n".join(out)


def note_trust(event: str, ctx, log=print) -> None:
    """File one trust probe. NEVER raises and never costs the read.

    `ctx` may be a browser context or a page (its context is used)."""
    try:
        ctx = getattr(ctx, "context", None) or ctx
        from automations.icd_alerts import relay as R
        try:
            from automations.icd_alerts import selfupdate as SU
            release = SU.applied_release() or "?"
        except Exception:  # noqa: BLE001
            release = "?"
        now = dt.datetime.now()
        # STAMPED: the relay folds same-summary rows and keeps the FIRST
        # detail, so an unstamped second event would vanish into the first.
        R.report_fault(TRUST_STAGE,
                       "SaraPlus trust %s %s (release %s)"
                       % (event, now.strftime("%H:%M"), release),
                       detail=trust_snapshot(event, ctx, now), log=None)
    except Exception:  # noqa: BLE001
        pass


def keep_session_alive(*, headless: bool = True, log=print,
                       now: Optional[dt.datetime] = None) -> str:
    """Overnight, touch the remembered session so it never goes idle.

    WHY (Eveliz, 2026-10-05/06): reads stop at midnight and come back for
    the 2am close-out. Two idle hours expire the SaraPlus session, so the
    close-out has to LOG IN -- and on some accounts (Eveliz, Rashad,
    carlos-b2batt; the other twelve offices never) every fresh login gets
    the emailed-code wall. She typed the code at 22:56, reads ran clean until
    midnight, and at 2:01 she was walled again for the whole next day.
    Holding the session open means the morning never needs a login at all.

    RESUME ONLY, NEVER A LOGIN. A login here is exactly the thing that earns
    the wall, at 3am with nobody there to clear it. If SaraPlus no longer
    honours the session, it is forgotten and the next real read logs in as
    it always has. Never raises: this is housekeeping, not a read.

    Returns what it did, for the log: 'kept', 'lost', 'none', 'not-due',
    'busy' or 'error'.
    """
    now = now or dt.datetime.now()
    remembered = _remembered_session()
    if not remembered:
        return "none"
    try:
        last = dt.datetime.fromisoformat(KEEPALIVE_PATH.read_text().strip())
        if (now - last) < dt.timedelta(minutes=KEEPALIVE_EVERY_MIN):
            return "not-due"
    except (OSError, ValueError):
        pass
    if signin_in_progress():
        return "busy"
    try:
        KEEPALIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEEPALIVE_PATH.write_text(now.isoformat(timespec="seconds"))
    except OSError:
        pass
    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = _context(p, headless)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                base = S.resume_session(page, remembered, log=log)
                if not base:
                    note_trust("session-lost-overnight", ctx, log=log)
            finally:
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001 -- housekeeping must never fail a tick
        log("SaraPlus keep-alive skipped: %s" % type(e).__name__)
        _note_keepalive("error", now)
        return "error"
    if base:
        _note_keepalive("kept", now)
        return "kept"
    _note_keepalive("lost", now)
    _forget_session()
    log("SaraPlus session expired overnight -- the next read will log in")
    return "lost"


def _empty_read_evidence(page, day, raw_rows) -> str:
    """What the credit-check grid looked like when it parsed to nobody: row
    counts, the header, a sample row, the page URL and the visible top of the
    page (date filters, office name). Best effort, never raises."""
    out = ["credit-check read for %s parsed to 0 reps" % day]
    try:
        if S.LAST_LOAD_CLICK.get("note"):
            out.append("load-records click: " + S.LAST_LOAD_CLICK["note"][:700])
    except Exception:  # noqa: BLE001
        pass
    # WHAT THE PLACEHOLDER IS. Omar 2026-10-28: three different clicks on
    # "Click to load records." left the sales grid as it was, and nothing in
    # the evidence said what that text sits in -- a link, a row handler, a
    # button elsewhere. The grid's own markup (scripts stripped) and every
    # element around that text, with its handlers, so the next fix is read
    # off the page instead of guessed.
    try:
        out.append("load-records elements: " + page.evaluate(
            """() => {
                 const hits = [];
                 const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                 let n;
                 while ((n = walk.nextNode())) {
                   if (!/load\\s*records/i.test(n.textContent || '')) continue;
                   let el = n.parentElement, chain = [];
                   for (let d = 0; el && d < 5; d++, el = el.parentElement) {
                     const a = Array.from(el.attributes || []).filter(x => /^(id|class|href|onclick|onmousedown|data-|role)/i.test(x.name))
                       .map(x => x.name + '=' + String(x.value).slice(0, 160)).join(' ');
                     chain.push('<' + el.tagName.toLowerCase() + ' ' + a + '>');
                   }
                   hits.push(chain.join(' IN '));
                 }
                 return hits.slice(0, 4).join(' || ') || '(none)';
               }""")[:1400])
    except Exception as e:  # noqa: BLE001
        out.append("load-records elements: ? (%s)" % type(e).__name__)
    try:
        out.append(S.LAST_COMPANY.get("note") or "company combo: (not checked)")
    except Exception:  # noqa: BLE001
        pass
    try:
        out.append("combos: " + page.evaluate(
            """() => Array.from(document.querySelectorAll('input.rcbInput')).map(i => {
                 const st = document.getElementById(i.id + '_ClientState');
                 let empty = '';
                 try { empty = (JSON.parse((st && st.value) || '{}').emptyMessage || ''); } catch (e) {}
                 return i.id.replace('ctl00_MainContent_', '') + '=' + String(i.value || '').slice(0, 40) + (empty ? ' (empty: ' + empty + ')' : '');
               }).join(', ')""")[:1500])
    except Exception as e:  # noqa: BLE001
        out.append("combos: ? (%s)" % type(e).__name__)
    try:
        out.append("selects: " + page.evaluate(
            """() => Array.from(document.querySelectorAll('select')).map(s =>
                 (s.id || s.name) + '=' + ((s.options[s.selectedIndex] || {}).text || '').trim()
                 + '/' + s.options.length).join(', ')""")[:600])
    except Exception as e:  # noqa: BLE001
        out.append("selects: ? (%s)" % type(e).__name__)
    try:
        out.append("sales grid html: " + page.evaluate(
            """() => {
                 const g = document.getElementById('ctl00_MainContent_rgOrderDashboard_ATT_ctl00');
                 if (!g) return '(no grid)';
                 const c = g.cloneNode(true);
                 c.querySelectorAll('script,style').forEach(x => x.remove());
                 return c.outerHTML.replace(/\\s+/g, ' ');
               }""")[:2200])
    except Exception as e:  # noqa: BLE001
        out.append("sales grid html: ? (%s)" % type(e).__name__)
    try:
        rows = list(raw_rows or [])
        out.append("raw grid rows: %d" % len(rows))
        try:
            out.append("agent rows: %d" % len(list(S.agent_rows(rows, S.AGENT_ROW_INTERNET))))
        except Exception as e:  # noqa: BLE001
            out.append("agent rows: ? (%s)" % type(e).__name__)
        # THE WHOLE GRID, not a sample (Steve 2026-10-21: four rows showed
        # day-history lines and nothing else, and whether rep rows sat
        # further down was exactly the question).
        for i, r in enumerate(rows[:40]):
            out.append("row %d: %s" % (i, " | ".join(str(c)[:40] for c in r[:12])))
        if len(rows) > 40:
            out.append("... %d more row(s)" % (len(rows) - 40))
    except Exception as e:  # noqa: BLE001
        out.append("rows: ? (%s)" % type(e).__name__)
    try:
        out.append("page url: %s" % page.url)
        out.append("page title: %s" % page.title())
        # Every table on the page with its id and row count, and what the
        # filters actually hold -- the report we read is picked by id, and a
        # grid that renders under a different id reads as empty.
        try:
            out.append("tables on page: " + page.evaluate(
                """() => Array.from(document.querySelectorAll('table[id]'))
                     .map(t => t.id + ':' + t.querySelectorAll('tbody tr').length)
                     .join(', ')""")[:1200])
            out.append("filters: " + page.evaluate(
                """() => ['%s', '%s', '%s'].map(id => {
                     const el = document.getElementById(id);
                     return id.split('_').pop() + '=' + (el ? el.value : '?');
                   }).join(' ')""" % (S.FIELD_START, S.FIELD_END,
                                      S.COMBO_INPUT.lstrip("#"))))
        except Exception as e:  # noqa: BLE001
            out.append("tables: ? (%s)" % type(e).__name__)
        body = page.inner_text("body", timeout=5000)
        out.append("page text: " + " ".join(body.split())[:700])
    except Exception as e:  # noqa: BLE001
        out.append("page: ? (%s)" % type(e).__name__)
    return "\n".join(out)


def read_day(day: Optional[dt.date] = None, *, headless: bool = True,
             log=print, resume_only: bool = False) -> Dict:
    """{'records': {REP: credit checks}, 'sales': {REP: {Int, Int Up, DTV, NL}}}.

    ONE SESSION, THREE PASSES. A failure in the sales half must not cost the
    credit checks: they are the faster-moving alert and the one this started
    as, so they are read FIRST and the other two are allowed to come back
    empty. An office whose grid has no AT&T rows yet still gets its pings.
    """
    from patchright.sync_api import sync_playwright
    from automations.shared import sale_hype as H

    day = day or C.today()
    # A FRESH BREAKDOWN PER READ, so a slow sweep's fault reports where THIS
    # read went rather than the last one's leftovers (see
    # saraplus.pass_timings_summary).
    try:
        S.reset_pass_timings()
        try:
            words = []
            for r in C.enrollments():
                for f in ("business_name", "owner", "office_key"):
                    for w in re.split(r"[^a-z0-9]+", str(r.get(f) or "").lower()):
                        if len(w) > 3 and w not in ("marketing", "management", "group", "solutions"):
                            words.append(w)
            S.PREFERRED_COMPANY_WORDS = words
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001 — instrumentation must never cost a read
        pass
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
        # resume_only reaches _sign_in_raw through this flag (it sits four
        # calls down, behind the heal/retry). 2026-10-12: this line was
        # MISSING -- the 10/8 patch died before writing it, so every
        # "resume-only" overnight read still typed the password and walled
        # (luke 01:42, carlos-b2batt 02:00, rashad 02:00 on 10/12, all with
        # resume_only=True in their own evidence). Now it is set, and cleared
        # again whatever happens.
        _RESUME_ONLY["on"] = bool(resume_only)
        try:
            ctx, page, base = _heal_and_login(p, headless, log=log)
        finally:
            _RESUME_ONLY["on"] = False
        try:

            try:
                _raw = S._run_report(page, base, day, C.SERVICE_INTERNET,
                                     S.GRID_INTERNET, log=log)
                records = S.parse_records(_raw)
                if not records and len(_raw) <= 1:
                    # ASKED TWICE BEFORE IT IS BELIEVED, same as the sales
                    # grid: a grid with no rows at all is usually a page that
                    # had not finished rendering on a slow machine (Steve's
                    # reads run 36-46s), not an office with nobody on it.
                    log("credit-check grid came back with no rows -- reading it again")
                    _raw = S._run_report(page, base, day, C.SERVICE_INTERNET,
                                         S.GRID_INTERNET, log=log)
                    records = S.parse_records(_raw)
            except Exception:
                # A READ THAT FAILS NEVER KEEPS ITS SESSION. Whatever went
                # wrong, the next sweep types the password instead of
                # resuming the same thing -- so one bad session costs one
                # sweep, not the day (2026-10-02).
                _forget_session()
                raise
            log("credit-check pass: %d rep(s)" % len(records))
            # A ZERO IS NOT EXPLAINED AWAY. Steve McElwee (2026-10-21): the
            # read passed, the relay said 0 reps all afternoon while every
            # other AT&T office relayed 5-54 checks, and nothing said what
            # the grid actually held. Keep what it held, so the fault can.
            empty_evidence = ""
            if not records:
                empty_evidence = _empty_read_evidence(page, day, _raw)
                log("credit-check grid came back EMPTY -- " + empty_evidence[:300].replace("\n", " | "))

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
                if not agents:
                    # THE SALES GRID TOO (Omar 2026-10-28: two sales posted in
                    # his room by 2pm, his relay said 0 reps, and only the
                    # credit-check grid had left any evidence behind).
                    _ev = _empty_read_evidence(page, day, att_rows)
                    _ev = "SALES grid (AT&T) parsed to 0 reps\n" + _ev.split("\n", 1)[-1]
                    # SALES FIRST: the fault's detail cell is cut at 1500
                    # characters and the credit-check dump alone fills it
                    # (Omar 2026-10-28 -- the sales section never showed).
                    empty_evidence = (_ev + "\n\n" + empty_evidence) if empty_evidence else _ev
                    log("sales grid came back EMPTY -- " + _ev[:300].replace("\n", " | "))
                elif empty_evidence:
                    # And when the credit-check grid was empty but this one
                    # was not, say so in the same fault -- "the reps ARE in
                    # his SaraPlus, nobody has sold or run a check yet" is
                    # the answer that stops a chase (Omar, same afternoon).
                    _names = ", ".join(sorted(a.get("name", "") for a in agents)[:12])
                    empty_evidence = ("SALES grid (AT&T): %d rep row(s) present, %d with a sale today -- %s\n\n"
                                      % (len(agents),
                                         sum(1 for a in agents if int(a.get("internet_sales", 0) or 0)
                                             + int(a.get("internet_upgrades", 0) or 0)
                                             + int(a.get("wireless_lines_sold", 0) or 0) > 0),
                                         _names)) + empty_evidence
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

            # THE FOURTH PASS, 'Wireless'. First only for offices on the three
            # credit alerts (Carlos 2026-10-22) -- the one grid with real
            # credit checks -- then NDS / B2B AT&T for their line counts, and
            # since 2026-10-26 EVERY office: it is the only grid that says
            # which lines were tablets or watches, and those no longer count as
            # sales on any scorecard (Megan). Its failure costs only itself:
            # None means "not read this time" and leaves NL as the AT&T grid
            # had it, rather than a day of zeros.
            credit = lines = None
            try:
                w_rows = S._run_report(page, base, day, S.SERVICE_WIRELESS,
                                       S.GRID_WIRELESS, log=log)
                w_head = S.grid_headers(page, S.GRID_WIRELESS)
                if C.credit_tiers_here():
                    credit = S.parse_credit(w_head, w_rows)
                    if credit is None:
                        log("Wireless grid has no Credit Checked / Credit "
                            "Passed labels -- not sending credit checks")
                    else:
                        log("Wireless pass: credit checks for %d rep(s)"
                            % len(credit))
                lines = S.parse_lines(w_head, w_rows)
                if lines is None:
                    log("Wireless grid has no New/Port/Upgrade Lines, "
                        "Tablets, Wearables labels -- NL left as read")
                else:
                    log("Wireless pass: lines for %d rep(s)" % len(lines))
            except Exception as e:  # noqa: BLE001 — the rest still stands
                log("Wireless pass failed (%s) — tablet + sales unaffected"
                    % type(e).__name__)

            return {"empty_evidence": empty_evidence, "records": records,
                    "sales": sales, "credit": credit, "lines": lines}
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

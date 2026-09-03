"""Re-capture the AppStream session BEFORE it dies, with no human.

    python -m automations.shared.appstream_autorenew            # renew + push
    python -m automations.shared.appstream_autorenew --check     # report only

WHY (Megan 2026-09-01, after her THIRD login of the day: "this CANNOT keep
happening"). The rqst token lives ~2h. Logins that day: 05:49, 08:01, 13:28 —
that cadence IS the token's lifetime, because nothing renewed it:

  * the holder's in-loop mint asks ownerville for a token and gets back the one
    it already has ("ownerville's warm page keeps handing back the token it
    already issued"), then re-keys the console with a dead token, so #searchMC
    never renders — every `mint FAILED` line in session_holder.out.log
  * the restart escape hatch, which minted on 8/29, failed twice on 9/1
    (03:35 and 07:59) — ownerville would not issue

THE MEASUREMENT THAT CHANGED THIS. `--appstream-login` re-run against a profile
whose session is STILL ALIVE completes unattended: "✅ Saved AppStream session
(10 cookies, 2 rqst token(s))" in under 55 seconds with nobody at the browser.
The human is only ever needed once the profile has gone COLD — and it goes cold
because we wait for the token to die before trying.

So stop waiting. Renew on a timer while the session is warm, and the login is a
once-in-a-while seed instead of a five-times-a-day interruption.

This does NOT replace the human seed: if the profile has gone cold it exits
non-zero and the existing watcher pages, exactly as before. It removes the
routine case, not the fallback.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import argparse
import contextlib
import datetime as dt
import json
import pathlib
import sys
import time

# Renew when the token has less than this left. Comfortably inside the ~2h TTL
# so a failed attempt still leaves room for the next tick AND for a human, and
# comfortably above the tick interval so we never thrash.
RENEW_UNDER_MIN = 75.0
# A token this fresh means someone/something just renewed — nothing to do.
HEALTHY_MIN = 90.0


def _log(msg: str) -> None:
    print("[%s] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg),
          flush=True)


def token_minutes_left() -> float:
    """Minutes on the saved session's longest-lived rqst token. 0.0 = none.

    Reads the exported storage_state rather than opening a browser: this runs on
    a timer next to real reports, and a browser launch is both slow and a way to
    disturb the session being measured."""
    from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE
    try:
        blob = json.loads(APPSTREAM_STORAGE_STATE.read_text())
    except Exception:  # noqa: BLE001 — missing/unreadable is simply "no session"
        return 0.0
    now = time.time()
    best = 0.0
    for c in blob.get("cookies", []):
        if not str(c.get("name") or "").startswith("rqst"):
            continue
        exp = c.get("expires")
        # A session cookie carries no expiry we can reason about. Treating it as
        # alive is how a dead token gets pushed to three machines.
        if not isinstance(exp, (int, float)) or exp <= 0:
            continue
        best = max(best, (exp - now) / 60.0)
    return max(0.0, best)


def _consumer_of() -> str:
    """Always "". No machine holds AppStream for another one.

    Megan 2026-09-02: "one machine CANNOT depend on another, we don't want 1
    taking them all down." Each Lucy signs in as its own account, so the remedy
    for a dead session is always "log in HERE" — see
    tableau_patchright._appstream_consumer_of for the longer note on why this
    stays as a stub instead of being deleted."""
    return ""


# _push_fleet() DELETED 2026-09-02 — see the note at the renewal site. A fresh
# session belongs to the account that minted it; handing it to another Lucy swaps
# that machine's identity instead of refreshing its session.

def _ownerville_tokens():
    """The rqst token(s) ownerville just issued, newest usable first.

    These are what make applicantstream ISSUE; our own saved token only makes it
    RESTORE. Kept separate from the AppStream cookies on purpose — mixing the two
    is how three days of re-keys asked the console to re-bless a token it had
    already expired."""
    from automations.shared.tableau_patchright import OWNERVILLE_STORAGE_STATE
    try:
        blob = json.loads(OWNERVILLE_STORAGE_STATE.read_text())
    except Exception:  # noqa: BLE001 — no ownerville export is simply "none"
        return []
    return [str(c.get("name"))[5:] for c in blob.get("cookies", [])
            if str(c.get("name") or "").startswith("rqst_")]


def renew_from_state(verbose: bool = True, tokens=None) -> bool:
    """Warm the capture profile from the LIVE storage_state, then save what the
    console hands back. No human, no dependence on a profile anyone signed into.

    This is the piece that was missing. The unattended re-capture works only on a
    profile holding a live session, and the SERVERS never had one — they
    authenticate from the pushed storage_state file, not from a browser session,
    so their capture profile has always been cold. That is why every renewal fell
    to a person on a laptop (Megan, 2026-09-01, three logins before noon).

    But the cookies in that pushed file DO work on those machines: it is exactly
    what every AppStream report reuses, all day, successfully. So seed the
    profile with them, open the office console the same way a report does, and
    export whatever the console returns. A live session renewing itself, instead
    of a cold profile waiting for a human to restart it.

    Returns True only when a token actually came back."""
    from automations.shared.tableau_patchright import (
        APPSTREAM_BASE, APPSTREAM_PROFILE_DIR, APPSTREAM_STORAGE_STATE,
        _launch_persistent)
    from patchright.sync_api import sync_playwright
    try:
        cookies = json.loads(APPSTREAM_STORAGE_STATE.read_text()).get("cookies", [])
    except Exception as e:  # noqa: BLE001
        _log("no saved session to warm from: %s" % str(e)[:120])
        return False
    if not cookies:
        _log("saved session has no cookies — nothing to warm from")
        return False

    APPSTREAM_PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, APPSTREAM_PROFILE_DIR, headless=False,
                                 label="appstream_autorenew", verbose=verbose)
        try:
            try:
                ctx.add_cookies(cookies)
            except Exception as e:  # noqa: BLE001 — a bad cookie must not abort
                _log("add_cookies partial (%s) — continuing" % type(e).__name__)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # THE TOKEN GOES IN THE URL. A bare ?p=701 does NOT restore a
            # session — the form this codebase documents as rendering "every
            # time, which is how every report and every fleet push lands" is
            # ?rqst=<TOKEN>&p=701. The first cut navigated without it and read
            # the empty console as "the session is genuinely dead" while the
            # very same cookies were serving reports on that machine minutes
            # earlier (Lucy 1, 2026-09-01 14:05).
            # RE-KEY WITH THE OWNERVILLE TOKEN, NOT OUR OWN.
            #
            # Re-keying with the token we already hold only RESTORES the session
            # — measured twice on Lucy 1: 77 min before, 77 after; 67 before, 67
            # after. It cannot issue. The token that MAKES applicantstream issue
            # a new one is the one ownerville just minted, which is exactly what
            # the holder's mint path passes. Saved tokens stay as the fallback
            # for when ownerville could not be refreshed.
            toks = list(tokens or [])
            toks += [str(c.get("name"))[5:] for c in cookies
                     if str(c.get("name") or "").startswith("rqst_")]
            if not toks:
                _log("no rqst token available to re-key with")
                return False
            rendered = False
            for tok in toks:
                try:
                    page.goto("%s?rqst=%s&p=701" % (APPSTREAM_BASE, tok),
                              wait_until="domcontentloaded")
                    page.wait_for_selector("#searchMC", timeout=15_000)
                    rendered = True
                    break
                except Exception:  # noqa: BLE001 — try the next saved token
                    continue
            if not rendered:
                _log("console did not render from any saved token (%d tried) — "
                     "the session is genuinely dead, not merely old" % len(toks))
                return False
            state = ctx.storage_state()
            ap = [c for c in state.get("cookies", [])
                  if "applicantstream" in (c.get("domain") or "")]
            n_rqst = sum(1 for c in ap
                         if str(c.get("name") or "").startswith("rqst"))
            if not n_rqst:
                # NEVER clobber a good export with a tokenless one — the same
                # guard _export_appstream has, for the same reason.
                _log("console rendered but carried no rqst token — keeping the "
                     "existing export untouched")
                return False
            APPSTREAM_STORAGE_STATE.write_text(
                json.dumps({"cookies": ap, "origins": []}))
            _log("console warm — exported %d cookie(s), %d rqst token(s)"
                 % (len(ap), n_rqst))
            return True
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


# OWNERVILLE IS ONE SESSION PER ACCOUNT — PAUSE THE HOLDER FIRST (2026-09-01).
#
# A fresh ownerville login BUMPS whatever session that account already has, and
# the holder's session is the one every impersonating report rides on. This
# module logged in without pausing it and took Rep Gap Alerts down: clean ticks
# through 14:15, the login at 14:22, then "Couldn't impersonate 'Calvin Ribera'
# in ownerville: name not found" on every tick until the holder was restarted at
# 16:07. The names were never wrong — the session under them had been bumped.
#
# tableau_patchright says it in as many words: "ownerville is one-session-per-
# account, so this login can still bump a live holder session server-side — stop
# the holder first."
#
# ALWAYS brings the holder back, including on an exception. A holder left down
# is strictly worse than a stale token: the token expires in two hours, a dead
# holder is dark until someone notices.
@contextlib.contextmanager
def _holder_paused(verbose: bool = True):
    """Stop the session holder for the duration, and ALWAYS restart it."""
    import os
    import subprocess
    uid = os.getuid()
    label = "gui/%d/com.alphalete.session-holder" % uid
    plist = (pathlib.Path.home() / "Library" / "LaunchAgents"
             / "com.alphalete.session-holder.plist")
    stopped = False
    try:
        r = subprocess.run(["launchctl", "bootout", label],
                           capture_output=True, text=True, timeout=90)
        stopped = (r.returncode == 0)
        _log("holder paused" if stopped else
             "holder not running (nothing to pause)")
        if stopped:
            time.sleep(5)          # let it release the ownerville session
        yield
    finally:
        if stopped:
            try:
                subprocess.run(["launchctl", "bootstrap", "gui/%d" % uid,
                                str(plist)], capture_output=True, text=True,
                               timeout=90)
                _log("holder restarted")
            except Exception as e:  # noqa: BLE001 — say it loudly, never swallow
                _log("COULD NOT RESTART THE HOLDER (%s) — it is DOWN and needs "
                     "a hand: launchctl bootstrap gui/%d %s"
                     % (type(e).__name__, uid, plist))


def _form_login(verbose: bool = True) -> bool:
    """Sign in to AppStream by driving the form, and keep what it hands back.

    This is the path that recovers a DEAD session with no human. Verified on
    Lucy 1 from a cold profile (no saved session): the form completed and the
    office console rendered. Kept separate from the warm-profile capture so the
    cheap path stays first and this only runs when there is nothing to warm."""
    from automations.shared.tableau_patchright import appstream_direct_session
    try:
        with appstream_direct_session(verbose=verbose, allow_form_login=True,
                                      force_form_login=True) as pg:
            ok = pg.locator("#searchMC").count() > 0
            _log("form login %s" % ("reached the console" if ok
                                    else "did NOT reach the console"))
            return ok
    except Exception as e:  # noqa: BLE001 — report, never take the timer down
        _log("form login failed: %s: %s" % (type(e).__name__, str(e)[:160]))
        return False


def _inside_playwright_loop() -> bool:
    """True when a sync_playwright() is already running in this thread.

    Playwright's sync API refuses to start a second one, so anything that opens
    its own must check first or it turns the caller's real error into a generic
    Playwright message."""
    try:
        import greenlet
        return greenlet.getcurrent().parent is not None
    except Exception:  # noqa: BLE001 — can't tell, so don't block the caller
        return False


def refresh_ownerville(verbose: bool = True) -> bool:
    """Sign in to ownerville fresh, unattended, and EXPORT the new rqst.

    THIS IS THE ROOT-CAUSE FIX (2026-09-01). `.ownerville_storage_state.json`
    had been frozen on rqst_43A275AE… since 2026-08-29 — the same eight
    characters in every `mint FAILED` line for three days. The holder kept
    re-keying the AppStream console with a token that died on the 29th, which is
    why the mint "always failed" and why every recovery fell to a human login.
    Ownerville's page was not "repeating"; we were replaying a stale FILE.

    Ownerville's Cloudflare auto-passes automation — measured again on Lucy 1
    the same afternoon: "ownerville form login reached a LIVE session
    UNATTENDED (rqst present)". The existing --ownerville-form-login proves the
    login but is a smoke test: it never exports, so the stale file survived it.
    This does the same login and writes the result.

    Its OWN throwaway profile: a profile already signed in resumes instead of
    logging in, which is exactly how a stale identity persists."""
    import shutil
    from automations.shared.tableau_patchright import (
        LOGIN_URL, OWNERVILLE_STORAGE_STATE, PROFILE_DIR, _drive_login_form,
        _launch_persistent, _ownerville_session_valid, _PASSWORD_SELECTOR,
        _USERNAME_SELECTOR)
    from patchright.sync_api import sync_playwright

    # CANNOT RUN INSIDE ANOTHER PLAYWRIGHT LOOP. tableau_session's ownerville
    # self-heal calls this from INSIDE its own sync_playwright(), and starting a
    # second one raises "It looks like you are using Playwright Sync API inside
    # the asyncio loop." Seen on Lucy 1 2026-09-01 19:31: a Tableau run whose
    # ownerville session had expired reported "re-mint failed (Error: ...)"
    # instead of the real cause, turning a clear "session expired" into a
    # confusing Playwright error.
    #
    # Say so and decline, so the caller reports ITS diagnosis rather than ours.
    # (The same nesting rule killed the browser-crash rebuild earlier that day —
    # 5 attempts, 5 failures, 0 recoveries.)
    try:
        import greenlet  # noqa: F401 — presence alone proves nothing; the probe is below
    except Exception:  # noqa: BLE001
        pass
    if _inside_playwright_loop():
        _log("refresh_ownerville called from inside a running Playwright loop — "
             "declining (a nested sync_playwright cannot start). The caller's "
             "own error is the real one.")
        return False

    prof = PROFILE_DIR.parent / ".ov_autorenew"
    # EMPTY EVERY TIME. A profile that is already signed in auto-resumes and the
    # login never runs, so the "fresh" session would be the stale one again.
    shutil.rmtree(prof, ignore_errors=True)
    prof.mkdir(parents=True, exist_ok=True)

    with _holder_paused(verbose=verbose), sync_playwright() as p:
        ctx = _launch_persistent(p, prof, headless=False,
                                 label="ov_autorenew", verbose=verbose)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)
            try:
                page.wait_for_selector(
                    "%s, %s" % (_PASSWORD_SELECTOR, _USERNAME_SELECTOR),
                    timeout=20_000)
            except Exception:  # noqa: BLE001 — already signed in is fine too
                pass
            # ALREADY SIGNED IN IS NOT A FAILURE. ownerville can redirect
            # straight past the form (…/index.cfm?p=9197), and then filling the
            # password times out after 30s — which the first cut reported as
            # "renew raised TimeoutError" and gave up on, throwing away a
            # perfectly live session (Lucy 1, 2026-09-01 15:27). Try the form,
            # but judge on whether the SESSION is live, not on whether we got to
            # type into it.
            try:
                _drive_login_form(page, verbose=verbose)
            except Exception as e:  # noqa: BLE001 — the check below is the judge
                _log("login form not driven (%s) — checking whether we are "
                     "already signed in" % type(e).__name__)
            if not _ownerville_session_valid(page, verbose=verbose):
                _log("ownerville login did NOT reach a live session")
                return False
            cookies = [c for c in ctx.storage_state().get("cookies", [])
                       if "ownerville" in (c.get("domain") or "")]
            toks = [c for c in cookies
                    if str(c.get("name") or "").startswith("rqst")]
            if not toks:
                # Never clobber a good export with a tokenless one.
                _log("ownerville session carried no rqst — keeping the existing "
                     "export untouched")
                return False
            OWNERVILLE_STORAGE_STATE.write_text(
                json.dumps({"cookies": cookies, "origins": []}))
            _log("ownerville refreshed — %d cookie(s), token %s"
                 % (len(cookies), str(toks[0].get("name"))[5:13]))
            return True
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report the token's remaining life and exit 0")
    ap.add_argument("--force", action="store_true",
                    help="re-capture even if the token looks healthy")
    ap.add_argument("--under", type=float, default=RENEW_UNDER_MIN,
                    help="renew when fewer than this many minutes remain")
    ap.add_argument("--refresh-ownerville", action="store_true",
                    help="ALSO re-log in to ownerville if the warm profile "
                         "fails. OFF by default: it swaps the machine's "
                         "ownerville identity and breaks impersonating reports, "
                         "and it does not extend the token anyway.")
    a = ap.parse_args(argv)

    left = token_minutes_left()
    _log("saved AppStream token: %.0f min left (renew under %.0f)"
         % (left, a.under))
    if a.check:
        # --check REPORTS; it does not judge. A low token is the normal state
        # this exists to observe, and exiting non-zero for it would post a red
        # incident about a probe that worked perfectly — the same crying-wolf
        # that appstream_selfheal --check had to have removed on 2026-08-31.
        return 0

    if left >= a.under and not a.force:
        _log("still healthy — nothing to do, staying silent")
        return 0

    _log("re-capturing while the profile session is still warm "
         "(this is the whole point: a cold profile is what needs a human)")
    # ORDER MATTERS. Re-keying from the SAVED token only RESTORES a session — it
    # never issues a new one (measured on Lucy 1: 77 min before, 77 after), and
    # this file's own history is three days of re-keying a token that died on
    # 8/29. So refresh ownerville FIRST so there is a genuinely new token to
    # re-key with, and only then open the console.
    # THE WARM PROFILE IS WHAT ACTUALLY RENEWS. Measured on Lucy 1 the day this
    # was built: a capture against the profile a human had seeded came back with
    # a FULL 120 minutes (15:17), while re-keying from cookies only maintained
    # what we already had (110 -> 104). Re-keying restores a session; only a
    # capture on a live profile makes AppStream issue.
    #
    # So try the profile first, and keep the ownerville refresh + re-key as the
    # fallback for a machine whose profile has genuinely gone cold — that path
    # still fixed the three-day-stale ownerville file, which was poisoning
    # everything, so it earns its place even though it cannot issue on its own.
    ok = False
    try:
        from automations.shared.tableau_patchright import _capture_appstream_state
        ok = _capture_appstream_state(verbose=False)
        if ok:
            _log("renewed from the warm profile")
        elif a.refresh_ownerville:
            # OPT-IN ONLY, AND IT COSTS SOMETHING. See refresh_ownerville: it
            # signs in with the creds-file account, which is NOT the identity a
            # runner impersonates through — Lucy 1 is Raf. Running it on
            # 2026-09-01 replaced Raf's ownerville session and Rep Gap Alerts
            # could no longer impersonate Calvin Ribera, Chan Park or Jay
            # Turnage: 18 failed pulls, Partners chat got no cards, and it took
            # a human logging back in as Raf to undo.
            #
            # It also never bought what it was added for — re-keying RESTORES a
            # session, it does not extend the token (77/77, 67/67, 58/57). So
            # the default is off: all risk, no measured benefit.
            _log("warm-profile capture did not land — --refresh-ownerville was "
                 "passed, so re-logging in to ownerville (THIS CHANGES THE "
                 "MACHINE'S OWNERVILLE IDENTITY)")
            refresh_ownerville(verbose=True)
            ok = renew_from_state(verbose=True, tokens=_ownerville_tokens())
        else:
            # DRIVE THE LOGIN FORM. It works unattended — measured on Lucy 1
            # from a COLD profile with no saved session, which is the 4am case
            # exactly: username -> NEXT -> Cloudflare 10s -> password -> submit,
            # then "#searchMC" with a live console. No human, no Turnstile stop.
            #
            # The repo has recorded since 2026-08-20 that this form "cannot
            # complete unattended", and allow_form_login was defaulted False on
            # that basis. So for twelve days no scheduled run even TRIED, and
            # every recovery fell to a person (Megan: "we can't be up at 3am for
            # this... it needs to run on its own"). The premise was wrong, not
            # the mechanism. Megan called it: "if you just give it a min and
            # then hit submit for the PW it clears on its own."
            _log("warm-profile capture did not land — driving the AppStream "
                 "login form (proven unattended from a cold profile)")
            ok = _form_login(verbose=True)
    except Exception as e:  # noqa: BLE001 — never take the timer down
        _log("renew raised %s: %s" % (type(e).__name__, str(e)[:160]))
        ok = False

    after = token_minutes_left()
    # Judge on whether the session is HEALTHY, not on whether the number went up
    # by a minute. A renew that lands at a full TTL is a success even when the
    # clock ticked during it, and demanding a strict increase reported real
    # renewals as failures (Lucy 1, 2026-09-01).
    if not ok or after < a.under:
        # SAY WHICH FAILURE THIS IS. "The profile has gone cold" was printed for
        # both of these, and on 2026-09-02 it was printed at a renew that had
        # just driven the form and reached a live console — the profile was
        # perfectly warm. That sent a human through five manual logins chasing a
        # cold profile that did not exist. The two cases need different fixes:
        if not ok:
            _log("UNATTENDED RENEW FAILED (%.0f min on the token) — never "
                 "reached a live console." % after)
        else:
            # Reached a console, but no usable token came back. MEASURED on
            # Lucy 1 2026-09-02: this is what a form-login-only recovery looks
            # like. The applicantstream form authenticates the ACCOUNT; it does
            # not mint an rqst — that comes from the OWNERVILLE SSO hop
            # (_sso_to_appstream / _ownerville_tokens, "what makes applicantstream
            # ISSUE, while our own saved token only makes it RESTORE"). A console
            # that renders on a re-injected old token reads as success here and
            # is not one.
            _log("UNATTENDED RENEW FAILED — reached a console but the token came "
                 "back with only %.0f min (expected ~120). The applicantstream "
                 "form does not mint an rqst; that comes from the ownerville SSO "
                 "hop, so check the OWNERVILLE session first." % after)
        _log("  PYTHONPATH=. .venv/bin/python -m "
             "automations.shared.tableau_patchright --appstream-login")
        return 1

    _log("renewed: %.0f min on the new token" % after)
    # NOT PUSHED ANYWHERE. This renewal is for THIS machine's own account. Every
    # Lucy runs its own renewal on its own login, so there is no fleet to hand it
    # to — and handing it over would replace the other machine's identity with
    # ours, not refresh it (Megan 2026-09-02: "one machine CANNOT depend on
    # another, we don't want 1 taking them all down").
    _log("renewed for this machine — no human was needed, nothing pushed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

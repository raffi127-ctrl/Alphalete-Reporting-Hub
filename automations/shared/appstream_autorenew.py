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
import datetime as dt
import json
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


def _push_fleet() -> bool:
    """Hand the fresh session to every machine that runs AppStream reports."""
    from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE
    from automations.shared.session_holder import APPSTREAM_FLEET_MACHINES
    from automations.day_orchestrator import mini_control as mc
    try:
        blob = APPSTREAM_STORAGE_STATE.read_text()
    except Exception as e:  # noqa: BLE001
        _log("cannot read the session to push: %s" % str(e)[:120])
        return False
    ok = True
    for machine in APPSTREAM_FLEET_MACHINES:
        try:
            mc.enqueue("set_appstream_state", blob, by="appstream-autorenew",
                       machine=machine)
            _log("queued session -> %s" % machine)
        except Exception as e:  # noqa: BLE001
            _log("could not queue to %s: %s" % (machine, str(e)[:120]))
            ok = False
    return ok


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

    prof = PROFILE_DIR.parent / ".ov_autorenew"
    # EMPTY EVERY TIME. A profile that is already signed in auto-resumes and the
    # login never runs, so the "fresh" session would be the stale one again.
    shutil.rmtree(prof, ignore_errors=True)
    prof.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
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
    ok = False
    try:
        fresh = refresh_ownerville(verbose=True)
        if not fresh:
            _log("could not refresh ownerville — trying the saved session "
                 "anyway, in case it still has life in it")
        ok = renew_from_state(verbose=True, tokens=_ownerville_tokens())
    except Exception as e:  # noqa: BLE001 — never take the timer down
        _log("renew raised %s: %s" % (type(e).__name__, str(e)[:160]))
        ok = False

    after = token_minutes_left()
    if not ok or after <= left:
        _log("UNATTENDED RENEW FAILED (%.0f min on the token) — the profile has "
             "gone cold, so this one genuinely needs a human seed:" % after)
        _log("  PYTHONPATH=. .venv/bin/python -m "
             "automations.shared.tableau_patchright --appstream-login")
        return 1

    _log("renewed: %.0f min on the new token" % after)
    if not _push_fleet():
        _log("renewed but could not push to the whole fleet")
        return 1
    _log("fleet pushed — no human was needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Set Apex up so Lucy can sign in by herself. ONCE, with the owner at the Mac.

    python -m automations.icd_alerts.apex_2fa_setup

WHAT THE OWNER DOES (about 5 minutes):
  1. types his Apex user name and password in two boxes (saved on this Mac
     only -- apex_login.CREDS_PATH, readable by this Mac's user only);
  2. types the text-message code Apex sends him, in Lucy's Apex window,
     like any sign-in;
  3. presses "Verify" on Apex's "Configure authenticator app" page, where
     Lucy has already typed the code in for him;
  4. takes a photo of the backup codes Apex shows, and keeps it.

WHAT LUCY DOES: opens that page, reads the key Apex prints on it (the same key
a phone app would scan), makes the code from it, and after Verify saves the
key with the login. Then she proves it in a separate, empty browser: signs in
alone, password + her own code, and says so.

The CHANGE to Apex (turning the app on) is pressed by the owner, not Lucy.
The window watches under the lock (apex_guard "watch"): nothing is stopped --
it is the owner's own hands -- but every request that is not a read is
written down, so the sign-in requests Lucy's own sign-in needs are on record.
The proof sign-in runs under the lock in "block" mode, like every Lucy run.
"""
from __future__ import annotations

import datetime as dt
import sys
import time

from automations.icd_alerts import apex_login as L

ENABLE_PATH = "Identity/Account/Manage/EnableAuthenticator"
SIGNIN_WAIT_S = 300
VERIFY_WAIT_S = 300

BANNER = "LUCY IS SETTING UP APEX -- PLEASE STAY FOR ABOUT 5 MINUTES"
BANNER_DETAIL = ("Lucy will tell you each step in a small box. "
                 "This window closes by itself when it is done.")

ASK_USER = ("Lucy will sign into Apex by herself for your weekly PNL.\n\n"
            "Your Apex user name:")
ASK_PASSWORD = "Your Apex password (saved on this computer only):"
SAY_TEXT_CODE = ("Apex is sending you a text-message code.\n\n"
                 "Press OK, then type the code in the Apex window.")
SAY_VERIFY = ("Lucy already typed the code in.\n\n"
              "Press OK, then press the blue \"Verify\" button in the Apex window.")
SAY_BACKUP = ("Apex is showing backup codes.\n\n"
              "Take a photo of them with your phone and keep it. "
              "Press OK when you have it.")
SAY_DONE = "Done. Lucy signed into Apex by herself. Nothing else to do."
SAY_SAVED_NOT_PROVEN = ("Saved. Lucy could not prove the sign-in yet -- "
                        "she will try again later. Nothing else to do.")


def _verified(page) -> bool:
    """Off the configure page = Apex took the code (it moves on to the backup
    codes, or back to the 2-step page)."""
    try:
        return ENABLE_PATH.lower() not in page.url.lower()
    except Exception:  # noqa: BLE001
        return False


def _fill_user_pass(page, user: str, pwd: str, log=print) -> None:
    """Best effort: if the form is not what we expect, the owner types it."""
    try:
        u = page.locator(L._USER).first
        u.wait_for(state="visible", timeout=20_000)
        u.fill(user)
        pw = page.locator(L._PASS).first
        if not pw.count() or not pw.is_visible():
            L._submit(page, u)
            pw.wait_for(state="visible", timeout=20_000)
        pw.fill(pwd)
        page.wait_for_timeout(L.PRE_SUBMIT_WAIT_S * 1000)
        L._submit(page, pw)
    except Exception as e:  # noqa: BLE001
        log("  (could not fill the sign-in form: %s -- type it in the window)"
            % type(e).__name__)


def prove(p, login, log=print) -> bool:
    """Sign in alone in an EMPTY browser, under the lock."""
    from automations.icd_alerts import apex_guard as G
    browser = p.chromium.launch(headless=False)
    try:
        ctx = browser.new_context(**G.launch_args())
        guard = G.install(ctx, "block")
        try:
            ok, step = L.sign_in(ctx.new_page(), login, log=log)
            log("  proof sign-in: %s" % step)
            return ok
        finally:
            guard.save()
    finally:
        browser.close()


def run(log=print, ask=None) -> int:
    from patchright.sync_api import sync_playwright
    from automations.carlos_payroll_pull import run as AP
    from automations.icd_alerts import apex_guard as G
    from automations.icd_alerts import apex_signin as AS
    from automations.shared import browser_banner

    if ask is None:
        from automations.icd_alerts import dialogs as ask
    try:
        user = ask.text(ASK_USER).strip()
        pwd = ask.password(ASK_PASSWORD) if user else ""
    except ask.Cancelled:
        log("  Apex setup: skipped for now")
        return 1
    if not (user and pwd):
        log("  Apex setup: skipped -- no user name or password")
        return 1

    AS.APEX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        AS.APEX_SIGNIN_LOCK.write_text(dt.datetime.now().isoformat())
    except OSError:
        pass
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(AS.APEX_PROFILE_DIR), headless=False,
                args=["--disable-sync"], **G.launch_args())
            guard = G.install(ctx, "watch")
            browser_banner.attach(ctx, BANNER, BANNER_DETAIL)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(AP.APEX_URL, wait_until="domcontentloaded",
                          timeout=60_000)
                page.wait_for_timeout(4000)

                # 1. signed in, with HIS text-message code
                if not L._past_login(page):
                    _fill_user_pass(page, user, pwd, log=log)
                    ask.message(SAY_TEXT_CODE)
                    end = time.time() + SIGNIN_WAIT_S
                    while time.time() < end and not L._past_login(page):
                        time.sleep(3)
                if not L._past_login(page):
                    log("  Apex setup: nobody finished signing in")
                    ask.message("Nobody signed in, so nothing changed. "
                                "Lucy will ask again another day.")
                    return 1

                # 2. the configure page: read the key, type the code
                page.goto(AP.APEX_URL + ENABLE_PATH,
                          wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(3000)
                try:
                    key = L.key_from_page(page.inner_text("body", timeout=10_000))
                except ValueError:
                    log("  Apex setup: no key on the configure page (%s)"
                        % page.url.split("?")[0])
                    ask.message("Lucy could not find the setup key on that page, "
                                "so nothing changed. Lucy's team will look at it.",
                                error=True)
                    return 1
                code_box = page.locator(L._CODE).first
                code_box.fill(L.fresh_code(key))
                filled = time.time()
                ask.message(SAY_VERIFY)

                # 3. he presses Verify; a code that went stale is replaced
                end = time.time() + VERIFY_WAIT_S
                while time.time() < end and not _verified(page):
                    time.sleep(2)
                    if time.time() - filled > 25 and not _verified(page):
                        try:
                            page.locator(L._CODE).first.fill(L.fresh_code(key))
                            filled = time.time()
                        except Exception:  # noqa: BLE001 -- page moving on
                            pass
                if not _verified(page):
                    log("  Apex setup: Verify was not pressed")
                    ask.message("Verify was not pressed, so nothing changed. "
                                "Lucy will ask again another day.")
                    return 1

                # 4. saved only now that Apex took the code
                L.save_creds(user, pwd, key)
                log("  Apex setup: the app code is on; login saved on this computer")
                page.wait_for_timeout(2000)
                if "recoverycodes" in page.url.lower().replace("-", ""):
                    ask.message(SAY_BACKUP)
            finally:
                guard.save()
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass

            # 5. the proof, in an empty browser
            ok = prove(p, L.creds(), log=log)
        ask.message(SAY_DONE if ok else SAY_SAVED_NOT_PROVEN)
        return 0
    finally:
        try:
            AS.APEX_SIGNIN_LOCK.unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())

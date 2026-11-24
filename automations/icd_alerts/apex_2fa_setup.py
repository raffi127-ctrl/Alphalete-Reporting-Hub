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

# The bar on top of the window says, at every moment, wait or act (Eve
# 2026-11-23: "que Lucy avise las esperas... lo más sencillo posible").
# RED = Lucy is working, hands off. GREEN = your turn, do exactly this.
WAIT = "WAIT -- DON'T TOUCH ANYTHING"
WAIT_DETAIL = ("Lucy is working. When it is your turn this bar turns green "
               "and tells you what to do.")
TURN_CODE = "YOUR TURN: TYPE THE CODE FROM YOUR PHONE"
TURN_CODE_DETAIL = ("Apex just texted it to you. Type it in the box below and "
                    "press the button. Then wait.")
TURN_VERIFY = "YOUR TURN: PRESS THE BLUE \"VERIFY\" BUTTON"
TURN_VERIFY_DETAIL = "Only that -- Lucy already typed the code. Then wait."
TURN_PHOTO = "YOUR TURN: TAKE A PHOTO OF THESE CODES"
TURN_PHOTO_DETAIL = "With your phone. Then press OK in Lucy's small box."
PROOF_DETAIL = ("Lucy is testing that she can sign in by herself. "
                "This window closes by itself in about a minute.")

ASK_USER = ("Lucy will sign into Apex by herself for your weekly PNL.\n\n"
            "Your Apex user name:")
ASK_PASSWORD = "Your Apex password (saved on this computer only):"
SAY_TEXT_CODE = ("Apex is sending you a text-message code.\n\n"
                 "Press OK, then type the code in the Apex window.")
SAY_VERIFY = ("Lucy already typed the code in.\n\n"
              "Press OK, then press the blue \"Verify\" button in the Apex window. "
              "Then wait.")
SAY_BACKUP = ("Apex is showing backup codes.\n\n"
              "Take a photo of them with your phone and keep it. "
              "Press OK when you have it.\n\n"
              "Then a new window opens for about a minute while Lucy tests "
              "her sign-in. Don't touch it -- it closes by itself.")
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
        from automations.shared import browser_banner
        browser_banner.attach(ctx, WAIT, PROOF_DETAIL)
        try:
            ok, step = L.sign_in(ctx.new_page(), login, log=log)
            log("  proof sign-in: %s" % step)
            return ok
        finally:
            guard.save()
    finally:
        browser.close()


# HOW EACH TRY ENDED, to Eve + Megan (Eve 2026-11-23: two setup windows
# opened for Jairo, nothing got done, and from here nobody could tell why --
# the answer sat in a log on his Mac). One line per try, as fault stage
# SETUP_STAGE; post.notify_faults DMs it to the approvers only, never the
# owner or a channel. The time is in the line so each try is its own row
# (the relay folds identical lines into one, already-posted row).
SETUP_STAGE = "apex-setup"


def _office_key() -> str:
    try:
        from automations.icd_alerts import config as C
        from automations.icd_alerts import pnl
        for rec in C.active_enrollments():
            if rec.get("office_key") in pnl.APEX_SETUP_KEYS:
                return rec["office_key"]
    except Exception:  # noqa: BLE001
        pass
    return ""


def tell_us(what: str, log=print) -> None:
    """Best effort, never raises: the telling is never the work."""
    try:
        from automations.icd_alerts import relay as R
        R.report_fault(SETUP_STAGE, "Apex setup %s: %s"
                       % (dt.datetime.now().strftime("%H:%M"), what),
                       office_key=_office_key(), log=log)
    except Exception:  # noqa: BLE001
        pass


def run(log=print, ask=None) -> int:
    end = ["stopped before the end, no reason recorded"]
    try:
        return _run(log, ask, end)
    except BaseException as e:  # noqa: BLE001 -- said, then raised as before
        end[0] = "Lucy's setup crashed (%s)" % type(e).__name__
        raise
    finally:
        tell_us(end[0], log=log)


def _run(log, ask, end) -> int:
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
        end[0] = ("the email/password box was closed or timed out -- "
                  "nothing typed")
        return 1
    if not (user and pwd):
        log("  Apex setup: skipped -- no user name or password")
        end[0] = "the email or password box was left empty"
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
            browser_banner.attach(ctx, WAIT, WAIT_DETAIL)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(AP.APEX_URL, wait_until="domcontentloaded",
                          timeout=60_000)
                page.wait_for_timeout(4000)

                # 1. signed in, with HIS text-message code
                if not L._past_login(page):
                    _fill_user_pass(page, user, pwd, log=log)
                    browser_banner.show(page, TURN_CODE, TURN_CODE_DETAIL,
                                        browser_banner.GREEN)
                    ask.message(SAY_TEXT_CODE)
                    deadline = time.time() + SIGNIN_WAIT_S
                    while time.time() < deadline and not L._past_login(page):
                        time.sleep(3)
                if not L._past_login(page):
                    log("  Apex setup: nobody finished signing in")
                    end[0] = ("email + password typed, but Apex sign-in was "
                              "not finished in 5 min (text code not entered, "
                              "or wrong password)")
                    ask.message("Nobody signed in, so nothing changed. "
                                "Lucy will ask again another day.")
                    return 1
                browser_banner.show(page, WAIT, WAIT_DETAIL)

                # 2. the configure page: read the key, type the code
                page.goto(AP.APEX_URL + ENABLE_PATH,
                          wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(3000)
                try:
                    key = L.key_from_page(page.inner_text("body", timeout=10_000))
                except ValueError:
                    log("  Apex setup: no key on the configure page (%s)"
                        % page.url.split("?")[0])
                    end[0] = ("signed in, but Lucy found no setup key on "
                              "Apex's page (%s) -- needs us"
                              % page.url.split("?")[0])
                    ask.message("Lucy could not find the setup key on that page, "
                                "so nothing changed. Lucy's team will look at it.",
                                error=True)
                    return 1
                code_box = page.locator(L._CODE).first
                code_box.fill(L.fresh_code(key))
                filled = time.time()
                browser_banner.show(page, TURN_VERIFY, TURN_VERIFY_DETAIL,
                                    browser_banner.GREEN)
                ask.message(SAY_VERIFY)

                # 3. he presses Verify; a code that went stale is replaced
                deadline = time.time() + VERIFY_WAIT_S
                while time.time() < deadline and not _verified(page):
                    time.sleep(2)
                    if time.time() - filled > 25 and not _verified(page):
                        try:
                            page.locator(L._CODE).first.fill(L.fresh_code(key))
                            filled = time.time()
                        except Exception:  # noqa: BLE001 -- page moving on
                            pass
                if not _verified(page):
                    log("  Apex setup: Verify was not pressed")
                    end[0] = ("signed in, code typed by Lucy, but Verify was "
                              "not pressed in 5 min")
                    ask.message("Verify was not pressed, so nothing changed. "
                                "Lucy will ask again another day.")
                    return 1

                # 4. saved only now that Apex took the code
                browser_banner.show(page, WAIT, WAIT_DETAIL)
                L.save_creds(user, pwd, key)
                log("  Apex setup: the app code is on; login saved on this computer")
                page.wait_for_timeout(2000)
                if "recoverycodes" in page.url.lower().replace("-", ""):
                    browser_banner.show(page, TURN_PHOTO, TURN_PHOTO_DETAIL,
                                        browser_banner.GREEN)
                    ask.message(SAY_BACKUP)
                    browser_banner.show(page, WAIT, WAIT_DETAIL)
            finally:
                guard.save()
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass

            # 5. the proof, in an empty browser
            ok = prove(p, L.creds(), log=log)
            end[0] = ("DONE -- code app on, login saved, Lucy signed in "
                      "by herself" if ok else
                      "code app on + login saved, but Lucy's own test "
                      "sign-in did not work yet (%s)"
                      % (L._state().get("last") or "no step recorded"))
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

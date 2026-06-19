"""Trust test: a fresh login reusing the persistent profile. Tells us whether
Sara Plus skips the OTP now that the profile cleared it once.

Logged-in detection: any in-app .aspx URL that is NOT login.aspx / VerifyPasscode.
"""
from __future__ import annotations

import json
from pathlib import Path

from patchright.sync_api import sync_playwright

from automations.shared.tableau_patchright import _launch_persistent
from automations.shared import creds

HERE = Path(__file__).resolve().parent
PROFILE = HERE / ".saraplus_profile"
STORAGE = HERE / ".saraplus_storage_state.json"
LOGIN_URL = "https://www.saraplus.com/e/servicepages/login.aspx"


def classify(url: str) -> str:
    u = url.lower()
    if "verifypasscode" in u:
        return "OTP_REQUIRED"
    if "login.aspx" in u:
        return "STILL_ON_LOGIN"
    if ".aspx" in u and "/e/" in u:
        return "LOGGED_IN"
    return f"UNKNOWN ({url})"


def main() -> int:
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, PROFILE, headless=False, label="saraplus-trust")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"[trust] initial url={page.url}", flush=True)

        # If a login form is shown, submit creds. If the session is already live,
        # login.aspx may redirect straight into the app.
        if page.query_selector("#ctl00_MainContent_txtUserName"):
            print("[trust] login form present — submitting creds", flush=True)
            page.fill("#ctl00_MainContent_txtUserName", creds.saraplus_username())
            page.fill("#ctl00_MainContent_txtPassword", creds.saraplus_password())
            page.click("#MainContent_btnLogin")
            page.wait_for_load_state("networkidle", timeout=45000)
        else:
            print("[trust] no login form — session likely already active", flush=True)
            page.wait_for_load_state("networkidle", timeout=20000)

        page.wait_for_timeout(2000)
        result = classify(page.url)
        print(f"[trust] RESULT={result} | final_url={page.url}", flush=True)
        try:
            page.screenshot(path=str(HERE.parents[1] / "output" / "saraplus_trust_test.png"),
                            full_page=True)
        except Exception:
            pass
        if result == "LOGGED_IN":
            STORAGE.write_text(json.dumps(ctx.storage_state()))
            print(f"[trust] saved storage_state ({len(ctx.storage_state().get('cookies', []))} cookies)",
                  flush=True)
        ctx.close()
    return 0 if result == "LOGGED_IN" else 5


if __name__ == "__main__":
    raise SystemExit(main())

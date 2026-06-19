"""One-time, HUMAN-DRIVEN OTP bootstrap for Sara Plus on the persistent
automation profile.

The VerifyPasscode page is an ASP.NET WebForms page with auto-postback radios —
too brittle to drive blindly. So we let the human complete the verification in
the open browser window (pick Email/Mobile, Get Code, type the 6 digits, submit)
while this script:
  1. opens the persistent profile + pre-fills the login form (so you only do the
     OTP, not retype creds),
  2. polls until the dashboard nav (#AS) appears,
  3. saves storage_state so the profile is trusted for future runs.

Run in background (headed window appears for you to interact with):
  PYTHONUTF8=1 .venv/Scripts/python.exe -m automations.b2b_sales_board._bootstrap_otp
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

from automations.shared.tableau_patchright import _launch_persistent
from automations.shared import creds

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROFILE = HERE / ".saraplus_profile"
STORAGE = HERE / ".saraplus_storage_state.json"
LOGIN_URL = "https://www.saraplus.com/e/servicepages/login.aspx"

OUT = ROOT / "output"
STATUS = OUT / "saraplus_bootstrap_status.txt"


def setstatus(msg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(msg)
    print(f"[bootstrap] {msg}", flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, PROFILE, headless=False, label="saraplus-otp")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

        # Pre-fill + submit the login so the human only handles the OTP.
        if page.query_selector("#AS") is None and page.query_selector("#ctl00_MainContent_txtUserName"):
            setstatus("pre-filling login form")
            try:
                page.fill("#ctl00_MainContent_txtUserName", creds.saraplus_username())
                page.fill("#ctl00_MainContent_txtPassword", creds.saraplus_password())
                page.click("#MainContent_btnLogin")
                page.wait_for_load_state("networkidle", timeout=45000)
            except Exception as e:
                print(f"[bootstrap] login pre-fill issue: {e}", flush=True)

        if page.query_selector("#AS") is not None:
            setstatus("already trusted — landed on dashboard without OTP")
        else:
            setstatus("ACTION NEEDED — in the browser window: pick Email or Mobile, "
                      "click Get Code, type the 6-digit code, submit. Waiting up to 12 min…")

        # Poll for the dashboard nav (#AS) — i.e. a completed login.
        ok = False
        for _ in range(240):  # 240 * 3s = 12 min
            try:
                if page.query_selector("#AS") is not None:
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(3)

        if ok:
            try:
                page.wait_for_timeout(1500)
                page.screenshot(path=str(OUT / "saraplus_dashboard.png"), full_page=True)
            except Exception:
                pass
            STORAGE.write_text(json.dumps(ctx.storage_state()))
            setstatus(f"DASHBOARD_OK — saved storage_state ({len(ctx.storage_state().get('cookies', []))} cookies). url={page.url}")
        else:
            setstatus(f"TIMEOUT — never reached dashboard. url={page.url}")
        ctx.close()
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())

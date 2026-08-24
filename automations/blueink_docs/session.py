"""Blue Ink web session — seeded by a human once, replayed by the runner.

Why the UI at all: on the "Blueink Unlimited Annual" plan, ANY bundle the API
creates is billed as a **Bulk Envelope** and that allowance is 50 PER YEAR
(spent; resets 12/20/26). Both API paths were tested and both 403. Sends made
in the web app come out of the **Envelopes** bucket, which is unlimited and is
where the team's ~50-90/week already go. So this drives the same screens a
person does.

NOTHING HERE TYPES A PASSWORD. `--login` opens a real browser and waits for a
human to sign in (including Google SSO and any 2FA), then saves the resulting
cookies to a gitignored storage_state file. Every later run replays that file.
When it expires, a human re-seeds -- there is deliberately no automated
password path, because the repo is public and this session can SEND documents.

    # once per machine, at the keyboard:
    python -m automations.blueink_docs.session --login

    # anytime, to see whether the runner still has a usable session:
    python -m automations.blueink_docs.session --check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = "https://secure.blueink.com"
DASHBOARD = f"{APP_ROOT}/dashboard/"
LOGIN_URL = f"{APP_ROOT}/login/"

STORAGE_STATE = Path(__file__).resolve().parent / ".blueink_storage_state.json"
PROFILE_DIR = Path(__file__).resolve().parent / ".blueink_profile"


def _sync_api():
    """patchright if present (stealth), else plain playwright."""
    try:
        from patchright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        from playwright.sync_api import sync_playwright
        return sync_playwright


def have_session() -> bool:
    return STORAGE_STATE.exists() and STORAGE_STATE.stat().st_size > 0


def _require_session() -> None:
    if not have_session():
        raise RuntimeError(
            "No Blue Ink session. At the keyboard on THIS machine run:\n"
            "    python -m automations.blueink_docs.session --login\n"
            "sign in as alphaletemarketing@gmail.com, and leave the browser "
            "open until it says saved.")


def login() -> int:
    """Open a real browser, let a human sign in, save the session."""
    sync_playwright = _sync_api()
    print("Opening Blue Ink. Sign in as alphaletemarketing@gmail.com --\n"
          "Google SSO and 2FA are all fine, take as long as you need.\n"
          "This waits until it sees the dashboard, then saves the session.\n")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False, no_viewport=True,
            args=["--window-size=1440,1000", "--window-position=0,0",
                  "--disable-sync"])          # never sync into a human's Chrome
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("waiting for sign-in...", flush=True)
        try:
            # 10 minutes of patience -- SSO + 2FA on a phone is not quick.
            page.wait_for_url(f"{APP_ROOT}/dashboard/**", timeout=600_000)
        except Exception:
            print("\nDidn't reach the dashboard. Nothing saved -- rerun when "
                  "you're ready.", file=sys.stderr)
            ctx.close()
            return 1
        ctx.storage_state(path=str(STORAGE_STATE))
        STORAGE_STATE.chmod(0o600)
        cookies = len(json.loads(STORAGE_STATE.read_text()).get("cookies", []))
        ctx.close()
    print(f"\nSaved {cookies} cookie(s) to {STORAGE_STATE.name} (owner-only). "
          "This machine can now send without anyone signing in again.")
    return 0


def open_context(p, *, headless: bool = True):
    """A browser context already logged into Blue Ink. Raises if unseeded."""
    _require_session()
    browser = p.chromium.launch(
        headless=headless,
        args=["--window-size=1440,1000", "--disable-sync"])
    return browser, browser.new_context(storage_state=str(STORAGE_STATE),
                                        viewport={"width": 1440, "height": 1000})


def check(headless: bool = True) -> int:
    """Is the saved session still good? Loads the dashboard and looks."""
    if not have_session():
        print("No session file -- run --login first.")
        return 1
    sync_playwright = _sync_api()
    with sync_playwright() as p:
        browser, ctx = open_context(p, headless=headless)
        page = ctx.new_page()
        page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60_000)
        url = page.url
        ok = "/login" not in url
        print(f"landed on {url}")
        print("session is GOOD" if ok else
              "session EXPIRED -- rerun --login at the keyboard")
        browser.close()
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true",
                    help="open a browser so a human can sign in once")
    ap.add_argument("--check", action="store_true",
                    help="report whether the saved session still works")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser during --check")
    args = ap.parse_args(argv)
    if args.login:
        return login()
    if args.check:
        return check(headless=not args.headed)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

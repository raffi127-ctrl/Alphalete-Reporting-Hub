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

    # once per machine, at the keyboard (or on ANY machine that then runs the
    # read-only sweep itself -- Blue Ink is one shared account, so unlike
    # ownerville/AppStream this session does not encode WHICH machine you are):
    python -m automations.blueink_docs.session --login

    # anytime, to see whether the runner still has a usable session:
    python -m automations.blueink_docs.session --check
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

APP_ROOT = "https://secure.blueink.com"
DASHBOARD = f"{APP_ROOT}/dashboard/"

# The ROOT, not "/login/" -- that path is a hard HTTP 404 (checked 2026-09-08,
# and it is what the first person to actually run --login saw: "page not
# found"). It had never been exercised: everything else here replays a session
# somebody seeded by hand, so the one URL nothing tested was the one that mints
# it. Blue Ink is a single-page app; unauthenticated, the root renders its own
# sign-in, the same way ownerville only logs in at its root domain. (The page
# it actually redirects to is /auth/login -- seen 2026-09-08 when a replayed
# session landed there. The root is what we open, so a future move of that
# path costs nothing.)
LOGIN_URL = f"{APP_ROOT}/"

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


# Where the app parks you when you are NOT signed in.
LOGGED_OUT = "/auth/"


def signed_in(page) -> bool:
    """Is this browser looking at the signed-in app right now?

    Every cheaper test was tried on 2026-09-08 and every one of them lied:

      url contains "/dashboard"   true within a second of opening, while the
                                  SPA is still on its way to /auth/login
      a blueink.com cookie        the site sets cookies before you log in (the
                                  saved "session" also carried a doubleclick
                                  one -- page-load junk, not a login)
      localStorage is non-empty   same problem, the app writes to it logged out

    So: the app decides, and it says so by ROUTING. Being on /dashboard and NOT
    on /auth is the thing every caller actually means, and it is what --check
    has always tested. Nothing here reports a session that --check would then
    call expired.
    """
    url = page.url or ""
    return "/dashboard" in url and LOGGED_OUT not in url


def have_session() -> bool:
    """Is there a SAVED session worth replaying?

    Not just "the file exists": an empty storage_state is a real file of 30
    bytes, and treating it as a session sends every later run off to fail
    somewhere less obvious (2026-09-08).
    """
    if not STORAGE_STATE.exists() or STORAGE_STATE.stat().st_size == 0:
        return False
    try:
        state = json.loads(STORAGE_STATE.read_text())
    except (ValueError, OSError):
        return False
    return bool(state.get("cookies")
                or any(o.get("localStorage") for o in state.get("origins") or []))


def _require_session() -> None:
    if not (have_session() or have_profile()):
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
        # WHAT COUNTS AS SIGNED IN. Not the URL. The app routes itself to
        # /dashboard while still logged out (it renders the sign-in over that
        # route), so "is /dashboard in the url" is true within a second of
        # opening the browser and proves nothing -- it saved an EMPTY state
        # and reported success on 2026-09-08. The only honest test is that the
        # browser is actually holding a Blue Ink session: a cookie for this
        # host, or a token the app put in localStorage.
        deadline = time.time() + 600            # SSO + 2FA is not quick
        ok = False
        stable = 0
        while time.time() < deadline:
            try:
                # TWICE, three seconds apart. A single look catches the moment
                # the SPA is passing THROUGH /dashboard on its way to the login
                # screen, which is exactly how this reported success twice on
                # 2026-09-08 while nobody had signed in.
                stable = stable + 1 if signed_in(page) else 0
                if stable >= 2:
                    ok = True
                    break
            except Exception:                   # noqa: BLE001
                stable = 0                      # mid-navigation; look again
            page.wait_for_timeout(3000)
        if not ok:
            print("\nNo Blue Ink session appeared -- NOTHING was saved.\n"
                  f"The browser was left at: {page.url}\n"
                  "If that says 'page not found', the app moved and LOGIN_URL "
                  "in this file needs updating. If you were still typing, just "
                  "rerun it.", file=sys.stderr)
            ctx.close()
            return 1
        ctx.storage_state(path=str(STORAGE_STATE))
        state = json.loads(STORAGE_STATE.read_text())
        cookies = len(state.get("cookies") or [])
        items = sum(len(o.get("localStorage") or [])
                    for o in state.get("origins") or [])
        # Refuse to leave an empty file behind. have_session() only asks
        # whether the file is there, so an empty one is WORSE than none: every
        # later run reads it as a good session and fails somewhere further in.
        if not cookies and not items:
            STORAGE_STATE.unlink(missing_ok=True)
            print("\nThe browser reported a session but saved nothing -- "
                  "removed the empty file rather than leave a fake one. "
                  "Rerun.", file=sys.stderr)
            ctx.close()
            return 1
        STORAGE_STATE.chmod(0o600)
        ctx.close()
    print(f"\nSaved {cookies} cookie(s) and {items} stored item(s) to "
          f"{STORAGE_STATE.name} (owner-only). This machine can now read and "
          "send without anyone signing in again.")
    return 0


def have_profile() -> bool:
    """Did a --login here leave a real browser profile behind?"""
    return PROFILE_DIR.is_dir() and any(PROFILE_DIR.iterdir())


def open_context(p, *, headless: bool = True):
    """A browser context already logged into Blue Ink. Raises if unseeded.

    THE PROFILE FIRST, the storage_state file only as a fallback. Replaying
    storage_state does not restore this app's login: --login on 2026-09-08
    saved 5 cookies and 4 localStorage items, and a --check that replayed them
    into a fresh browser still landed on /auth/login. storage_state carries
    cookies and localStorage and nothing else -- no IndexedDB, no
    sessionStorage -- so for an app that keeps its token anywhere else the file
    looks convincingly full and authenticates nothing. The profile directory is
    the whole browser and does not have that hole.

    The file is still written and still read, because it is what tells another
    machine (and have_session) that a login happened at all; it is just not the
    thing this replays when the profile is right here.

    Returns (closeable, context) either way. With a persistent profile those
    are the same object -- it has .close() and .new_page(), so every caller's
    `browser, ctx = open_context(...)` keeps working unchanged.
    """
    _require_session()
    if have_profile():
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=headless,
            viewport={"width": 1440, "height": 1000},
            args=["--window-size=1440,1000", "--disable-sync"])
        return ctx, ctx
    browser = p.chromium.launch(
        headless=headless,
        args=["--window-size=1440,1000", "--disable-sync"])
    return browser, browser.new_context(storage_state=str(STORAGE_STATE),
                                        viewport={"width": 1440, "height": 1000})


def check(headless: bool = True) -> int:
    """Is the saved session still good? Loads the dashboard and looks."""
    if not (have_session() or have_profile()):
        print("No session here -- run --login first.")
        return 1
    sync_playwright = _sync_api()
    with sync_playwright() as p:
        browser, ctx = open_context(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # The 4th copy of "wait a fixed moment, then read the URL" lived
        # here. Same race, same wrong answer: the SPA routes through an auth
        # check on the way in, so a URL read too early calls a healthy
        # session EXPIRED. Imported locally -- recent_ui imports this module.
        from automations.blueink_docs.recent_ui import open_dashboard
        try:
            open_dashboard(page)
            ok = True
            print(f"landed on {page.url}")
            print("session is GOOD")
        except RuntimeError as exc:
            ok = False
            print(f"landed on {page.url}")
            print(str(exc).splitlines()[0])
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

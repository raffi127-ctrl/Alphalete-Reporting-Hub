"""Credico (arc.credico.com) browser session — RUNS ON LUCY 1.

Credico is the second source for the DD Bulletin: its direct deposits are ADDED
to each owner's weekly figure (see override_bulletin/DD_SOURCES.md).

AUTH MODEL — the same one the ownerville reports use, and deliberately so:
a human logs in ONCE by hand, we save the resulting cookies, and every later run
replays them. **No password ever lives in this repo, in an env var, or in the
automation.** Claude never types it. When the cookies expire the run FAILS FAST
with instructions rather than trying to log in unattended.

    # ONE-TIME, on Lucy 1, with someone at the screen:
    python -m automations.credico.session --login

    # thereafter, in code:
    with credico_session() as page:
        page.goto(REPORTS_URL)

The saved state lives next to the ownerville one and is gitignored.
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

BASE = "https://arc.credico.com"
DASHBOARD = f"{BASE}/#/dashboard/sales-management"
STATE = Path(__file__).resolve().parents[1] / "shared" / ".credico_storage_state.json"
PROFILE_DIR = Path(__file__).resolve().parents[2] / "output" / "_credico_profile"


def _looks_logged_in(page, verbose=True):
    """True when the app shell is up rather than a login screen. Credico is a
    hash-router SPA, so the URL alone is unreliable — check for a login form."""
    try:
        url = (page.url or "").lower()
        if "login" in url or "signin" in url:
            if verbose:
                print(f"-> still on a login URL: {page.url}", flush=True)
            return False
        # a visible password field means we're not authenticated
        if page.locator("input[type=password]").count() > 0:
            if verbose:
                print("-> password field present — not logged in", flush=True)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"-> login check failed: {type(e).__name__}: {e}", flush=True)
        return False


def save_login(timeout_min: int = 10, verbose: bool = True) -> Path:
    """Open a HEADED browser for a human to log into Credico, then save cookies.

    Interactive and one-time. Waits until the login screen is gone (or the
    timeout), then writes the storage state. Nothing is typed by the automation —
    the person at the keyboard enters the credentials."""
    from patchright.sync_api import sync_playwright
    STATE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("\n=== Credico one-time login ===")
    print("A browser window will open at arc.credico.com.")
    print("Log in BY HAND (Carlos's login). Do not share the password with the")
    print("automation — it only needs the session cookies afterwards.")
    print(f"Waiting up to {timeout_min} min for the dashboard to appear...\n",
          flush=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False,
            viewport={"width": 1500, "height": 950})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(DASHBOARD, wait_until="domcontentloaded")
        deadline = timeout_min * 60
        waited = 0
        while waited < deadline:
            page.wait_for_timeout(2000)
            waited += 2
            if not _looks_logged_in(page, verbose=False):
                continue
            page.wait_for_timeout(3000)          # let the SPA settle / set its token
            # "No password field" alone is too weak — a still-loading SPA passes it.
            # Require the auth token to actually exist in localStorage.
            try:
                has_token = sum(len(o.get("localStorage", []))
                                for o in ctx.storage_state().get("origins", [])) > 0
            except Exception:  # noqa: BLE001
                has_token = False
            if _looks_logged_in(page, verbose=False) and has_token:
                break
            if waited % 20 == 0:
                print("   ...waiting for the dashboard to finish loading", flush=True)
        else:
            ctx.close()
            raise RuntimeError("timed out waiting for a Credico login")
        state = ctx.storage_state()
        STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
        n = len(state.get("cookies", []))
        n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
        url = page.url
        ctx.close()
    print(f"\n✓ saved {n} cookie(s) + {n_ls} localStorage item(s) → {STATE}")
    print(f"  final URL: {url}")
    if n_ls == 0 or "login" in url.lower():
        # The SPA keeps its token in localStorage; saving none means the login
        # never completed, and a cookies-only state silently fails later.
        print("\n⚠ THIS LOOKS INCOMPLETE — no localStorage was captured (that's "
              "where Credico keeps the auth token).\n  Re-run --login and wait "
              "until the Sales Management dashboard is fully on screen before "
              "closing anything.")
    else:
        print("  Verify with:  python -m automations.credico.session --check")
    return STATE


@contextmanager
def credico_session(headless: bool = True, verbose: bool = True):
    """Yield a logged-in Credico page by replaying the saved cookies.

    Fails fast with instructions when the state file is missing or stale — it
    never attempts an unattended login (that would need the password)."""
    from patchright.sync_api import sync_playwright
    if not STATE.exists():
        raise RuntimeError(
            f"no Credico session at {STATE.name}. Run ONCE on Lucy 1 with someone "
            f"at the screen:\n    python -m automations.credico.session --login")
    state = json.loads(STATE.read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        # Hand the state file to new_context rather than add_cookies(): Credico is
        # a hash-router SPA and keeps its auth token in localStorage, which lives
        # in state["origins"], NOT in cookies. Injecting cookies alone restored
        # nothing and landed straight back on #/login.
        ctx = browser.new_context(viewport={"width": 1500, "height": 950},
                                  storage_state=str(STATE))
        if verbose:
            n_c = len(state.get("cookies", []))
            n_ls = sum(len(o.get("localStorage", []))
                       for o in state.get("origins", []))
            print(f"-> credico: {n_c} cookie(s) + {n_ls} localStorage item(s) restored",
                  flush=True)
            if n_ls == 0:
                print("   ⚠ no localStorage captured — if this fails, the login "
                      "didn't complete; re-run --login and wait for the dashboard",
                      flush=True)
        page = ctx.new_page()
        page.goto(DASHBOARD, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        if not _looks_logged_in(page, verbose=verbose):
            ctx.close(); browser.close()
            raise RuntimeError(
                "Credico session expired. Re-run ON LUCY 1 with someone at the "
                "screen:\n    python -m automations.credico.session --login")
        try:
            yield page
        finally:
            ctx.close()
            browser.close()


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Credico session (Lucy 1)")
    ap.add_argument("--login", action="store_true",
                    help="one-time interactive login; saves the session cookies")
    ap.add_argument("--check", action="store_true",
                    help="verify the saved session still works (no writes)")
    ap.add_argument("--minutes", type=int, default=10)
    a = ap.parse_args(argv)
    if a.login:
        save_login(timeout_min=a.minutes)
        return 0
    if a.check or True:
        try:
            with credico_session(headless=True) as page:
                print(f"✓ Credico session OK — {page.url}")
            return 0
        except RuntimeError as e:
            print(f"✗ {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

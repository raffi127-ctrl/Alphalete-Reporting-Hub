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

HOW LONG A LOGIN LASTS — the thing that kept surprising us. Credico issues a
**14-day bearer token and no refresh token**, so a session cannot renew itself:
it dies on a date that is fixed the moment someone logs in. credico_fetch runs
WEEKLY (Thursdays), so one login covers about TWO runs and then the job starts
failing. The date is written inside the saved state, so read it and warn while
there is still runway instead of finding out at 8am — `--check` prints it, and
every run prints it on the restore line.
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://arc.credico.com"
DASHBOARD = f"{BASE}/#/dashboard/sales-management"
STATE = Path(__file__).resolve().parents[1] / "shared" / ".credico_storage_state.json"
PROFILE_DIR = Path(__file__).resolve().parents[2] / "output" / "_credico_profile"

# The localStorage item that actually holds the login. Everything in `cookies`
# is Google Analytics (_ga / _gid / _gat / _ga_*), which is why a cookie count
# says nothing at all about whether the session works.
AUTH_KEY = "CredicoArcAuth"
# Warn while a run's worth of runway is left. credico_fetch is weekly, so under
# 8 days means the NEXT run is the one that breaks, not this one.
WARN_DAYS = 8

# What to do about a dead session, in one place. The incident post offers
# `lucy rerun <report>` for every failure; for this one a re-run replays the
# same dead token and fails identically, so say so.
RELOGIN_STEPS = (
    "A RE-RUN CANNOT FIX THIS — every run replays the same saved file. It needs "
    "a headed login by a human (no password lives in this repo, so nothing can "
    "do it unattended):\n"
    "    python -m automations.credico.session --login\n"
    "Any machine will do: the state is plain JSON (localStorage, no OS key) and "
    "replays anywhere — it is not pinned to Lucy 1 nor to its IP. Then ship it "
    "to Lucy 1, which is where credico_fetch runs:\n"
    "    mini_control.enqueue('set_credico_state', <contents of the state file>)"
)


def _auth_blob(state):
    """The parsed CredicoArcAuth localStorage item, or None."""
    for origin in state.get("origins", []) or []:
        for item in origin.get("localStorage", []) or []:
            if item.get("name") == AUTH_KEY:
                try:
                    return json.loads(item.get("value") or "")
                except Exception:  # noqa: BLE001
                    return None
    return None


def _state_expiry(state):
    """When this saved session stops working (tz-aware UTC), or None.

    Two independent sources, both inside CredicoArcAuth: the `.expires` string
    Credico writes next to the token, and the `exp` claim of the JWT itself.
    They have always agreed; the JWT is the fallback because it cannot be
    reformatted away."""
    blob = _auth_blob(state)
    if not isinstance(blob, dict):
        return None
    raw = blob.get(".expires")
    if raw:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(raw)
            if dt is not None:
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001 — fall through to the JWT
            pass
    tok = blob.get("access_token") or ""
    parts = tok.split(".")
    if len(parts) == 3:
        try:
            import base64
            pad = parts[1] + "=" * (-len(parts[1]) % 4)
            exp = json.loads(base64.urlsafe_b64decode(pad)).get("exp")
            if exp:
                return datetime.fromtimestamp(int(exp), timezone.utc)
        except Exception:  # noqa: BLE001
            return None
    return None


def _days_left(exp):
    if exp is None:
        return None
    return (exp - datetime.now(timezone.utc)).total_seconds() / 86400.0


def session_expiry(path=None):
    """(expiry, days_left) for the saved state — (None, None) if unreadable.

    Public so a preflight elsewhere can ask without launching a browser."""
    path = Path(path) if path else STATE
    if not path.exists():
        return None, None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None, None
    exp = _state_expiry(state)
    return (exp, _days_left(exp)) if exp is not None else (None, None)


def _expiry_note(exp, days=None):
    """One line a human can act on, for logs and error messages."""
    if exp is None:
        return "UNKNOWN (no token found in the saved state)"
    days = _days_left(exp) if days is None else days
    when = f"{exp:%Y-%m-%d %H:%M UTC}"
    if days < 0:
        n = abs(days)
        return f"{when} ({'today' if n < 1 else f'{int(n)} day(s) ago'})"
    return f"{when} ({int(days)} day(s) left)"


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
        exp = _state_expiry(state)
        url = page.url
        ctx.close()
    print(f"\n[OK] saved {n} cookie(s) + {n_ls} localStorage item(s) -> {STATE}")
    print(f"  final URL: {url}")
    if n_ls == 0 or "login" in url.lower():
        # The SPA keeps its token in localStorage; saving none means the login
        # never completed, and a cookies-only state silently fails later.
        print("\n[!] THIS LOOKS INCOMPLETE — no localStorage was captured (that's "
              "where Credico keeps the auth token).\n  Re-run --login and wait "
              "until the Sales Management dashboard is fully on screen before "
              "closing anything.")
    else:
        # Say the date out loud at the one moment someone is watching: this is a
        # 14-day token, and whoever just logged in is the person who can put the
        # next login on a calendar.
        print(f"  good until: {_expiry_note(exp)}  — Credico tokens last 14 days "
              f"and do not refresh")
        print("  Verify with:  python -m automations.credico.session --check")
    return STATE


@contextmanager
def credico_session(headless: bool = True, verbose: bool = True):
    """Yield a logged-in Credico page by replaying the saved cookies.

    Fails fast with instructions when the state file is missing or stale — it
    never attempts an unattended login (that would need the password)."""
    # Every cheap check runs BEFORE patchright is even imported: a dead token
    # costs no browser launch, no page load, and no 45-minute job slot.
    if not STATE.exists():
        raise RuntimeError(f"no Credico session at {STATE.name}.\n" + RELOGIN_STEPS)
    state = json.loads(STATE.read_text())
    # Read the clock first and name the DATE, so an expiry is never again
    # mistaken for a transient blip somebody re-runs three times.
    exp = _state_expiry(state)
    days = _days_left(exp)
    if exp is not None and days <= 0:
        raise RuntimeError(
            f"Credico session EXPIRED {_expiry_note(exp, days)}.\n"
            f"Credico issues a 14-day token with no refresh, so one login covers "
            f"about two of these weekly runs.\n" + RELOGIN_STEPS)
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        # Hand the state file to new_context rather than add_cookies(): Credico is
        # a hash-router SPA and keeps its auth token in localStorage, which lives
        # in state["origins"], NOT in cookies. Injecting cookies alone restored
        # nothing and landed straight back on #/login.
        # accept_downloads: the Fee Report file arrives as a download event
        # (the office node is an ng-click handler, not an href). Explicit rather
        # than relying on the Playwright default.
        ctx = browser.new_context(viewport={"width": 1500, "height": 950},
                                  storage_state=str(STATE),
                                  accept_downloads=True)
        if verbose:
            n_c = len(state.get("cookies", []))
            n_ls = sum(len(o.get("localStorage", []))
                       for o in state.get("origins", []))
            # Say what the numbers MEAN. Every one of those cookies is Google
            # Analytics, so "4 cookie(s) restored" reads healthy on a state with
            # no login left in it. The token is in localStorage, and it has a date.
            print(f"-> credico: {n_c} analytics cookie(s) + {n_ls} localStorage "
                  f"item(s) restored; login good until {_expiry_note(exp, days)}",
                  flush=True)
            if n_ls == 0:
                print("   [!] no localStorage captured — if this fails, the login "
                      "didn't complete; re-run --login and wait for the dashboard",
                      flush=True)
            elif days is not None and days < WARN_DAYS:
                # Loud on the LAST run that still works, rather than on the one
                # that breaks: weekly job, so under 8 days means next Thursday.
                print(f"   [!] RENEW NOW — this login dies before the next weekly "
                      f"run.\n{RELOGIN_STEPS}", flush=True)
        page = ctx.new_page()
        page.goto(DASHBOARD, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        if not _looks_logged_in(page, verbose=verbose):
            ctx.close(); browser.close()
            # The token had not run out by the clock, so this is a rejection —
            # revoked, password changed, or the account logged out elsewhere.
            # Same fix, but don't blame an expiry that hasn't happened.
            raise RuntimeError(
                "Credico REJECTED the saved session (landed back on the login "
                f"screen). The token is still dated {_expiry_note(exp, days)}, "
                "so it was revoked rather than aged out.\n" + RELOGIN_STEPS)
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
    ap.add_argument("--expiry", action="store_true",
                    help="print when the saved login dies — no browser, no network")
    ap.add_argument("--minutes", type=int, default=10)
    a = ap.parse_args(argv)
    if a.login:
        save_login(timeout_min=a.minutes)
        return 0
    if a.expiry:
        # Cheap enough to run anywhere, including from a preflight or by hand on
        # a machine with no browser: it only reads the JSON.
        exp, days = session_expiry()
        if exp is None:
            print(f"[FAIL] no readable Credico token in {STATE.name}")
            return 1
        print(f"Credico login good until {_expiry_note(exp, days)}")
        if days <= 0:
            print(RELOGIN_STEPS)
            return 1
        if days < WARN_DAYS:
            print(f"[!] under {WARN_DAYS} days — the next weekly credico_fetch "
                  f"will fail.\n{RELOGIN_STEPS}")
        return 0
    if a.check or True:
        try:
            with credico_session(headless=True) as page:
                print(f"[OK] Credico session OK — {page.url}")
            return 0
        except RuntimeError as e:
            print(f"[FAIL] {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

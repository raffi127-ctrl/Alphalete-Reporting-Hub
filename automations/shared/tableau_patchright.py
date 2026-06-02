"""Patchright-based Tableau driver for Crosstab downloads.

Why this exists: Tableau's Download → Crosstab dialog silently no-ops
clicks on certain worksheets (SARAPLUSSALESSUMMARY's
'Sara Plus Sales Summary (2)', ECBONUSAWARENESS's 'Consultant ORG Title',
and the NDS OPT '5 metrics + Rep Breakdown chart' set) when driven over
a CDP-attached Chrome session. The same dialogs accept the clicks fine
in a regular browser. Theory: Tableau detects the devtools/CDP channel
and disables selection state to suppress automation.

Patchright is a Playwright fork with stealth patches; it launches a
fresh Chrome instance that Tableau doesn't recognize as automated.
Combined with a persistent profile, ownerville's Cloudflare check stays
quiet between runs.

Profile re-use: we point at order_log.py's existing .browser_profile so
Megan's logged-in session carries across both reports (no duplicate
login). The profile is gitignored.

The session manager handles login lazily — first run drives the
ownerville form; subsequent runs find an already-authenticated session
in the profile and skip straight to Tableau.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from patchright.sync_api import (
    sync_playwright,
    Page,
    TimeoutError as PWTimeout,
)

from automations.recruiting_report.opt_phase import (
    drive_crosstab_dialog,
    _scrape_one_view_data,
)
from automations.shared import creds


PROFILE_DIR = (
    Path(__file__).resolve().parent.parent / "uploaded" / ".browser_profile"
)

LOGIN_URL = "https://ownerville.com"
# v2 is the internal dashboard that holds the 'Login to Tableau' SSO
# link. The CDP-attached path (opt_phase._reauth_tableau) navigates
# here to extract the rqst token and ride it through to Tableau.
OWNERVILLE_V2_URL = "https://v2.ownerville.com/index.cfm"
# Ownerville login is read from a gitignored local file (automations.shared.
# creds → ownerville-creds.json at the repo root), NOT hardcoded — the repo was
# public, so the password must never live in source. creds.ownerville_*() raise
# a clear error if the file is missing.

# Form selectors (mirror order_log.py — kept stable since 2026-05).
_USERNAME_SELECTOR = (
    'input[type="email"], input[name="username"], input[name="email"], '
    'input[type="text"]'
)
_PASSWORD_SELECTOR = 'input[type="password"]'
_LOGIN_BUTTON_NAME = re.compile(r"log\s*in|sign\s*in", re.IGNORECASE)
_NEXT_BUTTON_NAME = re.compile(r"^\s*next\s*$", re.IGNORECASE)
_FINAL_SUBMIT_NAME = re.compile(
    r"sign\s*in|log\s*in|submit|continue|enter", re.IGNORECASE
)

_CLOUDFLARE_WAIT_MS = 10_000
_PRE_SUBMIT_PAUSE_MS = 3_000

# Selector for the SSO link on ownerville that opens an authenticated
# Tableau tab. Matches what _reauth_tableau already targets in opt_phase.
_TABLEAU_SSO_HREF_RE = re.compile(r"viewable\.cfm.*tableau", re.IGNORECASE)


@contextmanager
def tableau_session(headless: bool = False, verbose: bool = True) -> Iterator[Page]:
    """Yield a Page logged into Tableau via ownerville SSO.

    Uses Order Log's persistent profile so the login survives across runs.
    First call may drive the login form + Cloudflare; subsequent calls
    skip straight to the post-login state."""
    PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=headless,
                no_viewport=True,
            )
        except Exception as e:
            if verbose:
                print(f"[tableau_patchright] system Chrome unavailable ({e!r}) — "
                      "falling back to bundled Chromium", flush=True)
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=headless,
                no_viewport=True,
            )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _ensure_tableau_authenticated(page, verbose=verbose)
            yield page
        finally:
            ctx.close()


def _ensure_tableau_authenticated(page: Page, verbose: bool = True) -> None:
    """Make sure `page` has a Tableau session cookie. Two steps:
      1. Ensure ownerville is logged in (drives the form if not).
      2. Visit v2.ownerville.com, extract the rqst SSO token, and
         redirect via the Tableau SSO URL. After this returns, any
         subsequent goto() to a Tableau view URL will load the viz
         instead of bouncing to login.
    """
    if verbose:
        print(f"-> Loading {LOGIN_URL}", flush=True)
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3_000)

    # Drive the form if either the password OR the standalone username
    # field is visible (some flows split into two pages).
    if (page.locator(_PASSWORD_SELECTOR).count() > 0
            or page.locator(_USERNAME_SELECTOR).count() > 0):
        _drive_login_form(page, verbose=verbose)
    elif verbose:
        print("-> ownerville session reused from profile", flush=True)

    _sso_to_tableau(page, verbose=verbose)


def _sso_to_tableau(page: Page, verbose: bool = True) -> None:
    """Seed a Tableau session by following ownerville's 'Login to Tableau'
    SSO link. Mirrors opt_phase._reauth_tableau."""
    if verbose:
        print(f"-> Fetching SSO token from {OWNERVILLE_V2_URL}", flush=True)
    page.goto(OWNERVILLE_V2_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6_000)
    m = re.search(r"rqst=([A-Za-z0-9_]+)", page.url or "")
    if not m:
        href = page.evaluate(
            "() => { const a=[...document.querySelectorAll('a')]"
            ".find(x=>/p=81/.test(x.getAttribute('href')||'')); "
            "return a?a.getAttribute('href'):''; }")
        m = re.search(r"rqst=([A-Za-z0-9_]+)", href or "")
    if not m:
        raise RuntimeError(
            "Couldn't find Tableau SSO token (rqst=...) on v2.ownerville.com — "
            "ownerville login state isn't valid. Delete "
            f"{PROFILE_DIR} and retry to force a fresh login."
        )
    sso_url = f"{OWNERVILLE_V2_URL}?p=81&rqst={m.group(1)}&ssook=1"
    if verbose:
        print("-> Following SSO link to Tableau…", flush=True)
    page.goto(sso_url, wait_until="domcontentloaded")
    page.wait_for_timeout(15_000)
    if verbose:
        print(f"-> Tableau session established (page at {(page.url or '')[:80]})",
              flush=True)


def _drive_login_form(page: Page, verbose: bool,
                      username: Optional[str] = None,
                      password: Optional[str] = None) -> None:
    """Drive the two-step username→NEXT→password login form. Defaults to the
    ownerville login; AppStream uses the SAME form, so pass its (rcaptain) creds
    to reuse this for the direct AppStream login. Mirrors order_log.login."""
    username = username if username is not None else creds.ownerville_username()
    password = password if password is not None else creds.ownerville_password()
    if verbose:
        print("-> Filling username", flush=True)
    # Open form if it's behind a 'Log in' click.
    for role in ("link", "button"):
        try:
            cand = page.get_by_role(role, name=_LOGIN_BUTTON_NAME).first
            if cand.is_visible(timeout=2_000):
                cand.click()
                break
        except PWTimeout:
            continue
    page.wait_for_selector(_USERNAME_SELECTOR, timeout=15_000)
    page.fill(_USERNAME_SELECTOR, username)

    if verbose:
        print("-> Clicking NEXT", flush=True)
    page.get_by_role("button", name=_NEXT_BUTTON_NAME).first.click()
    page.wait_for_selector(_PASSWORD_SELECTOR, timeout=60_000)

    if verbose:
        print(f"-> Letting Cloudflare run for {_CLOUDFLARE_WAIT_MS}ms…",
              flush=True)
    page.wait_for_timeout(_CLOUDFLARE_WAIT_MS)

    if verbose:
        print("-> Filling password", flush=True)
    page.fill(_PASSWORD_SELECTOR, password)
    page.wait_for_timeout(_PRE_SUBMIT_PAUSE_MS)

    if verbose:
        print("-> Submitting", flush=True)
    # The submit fires a Cloudflare->SSO redirect chain that can outlast
    # patchright's 30s post-click navigation auto-wait, so .click() would raise
    # a TimeoutError even though the form already submitted. no_wait_after skips
    # that auto-wait; the explicit waits below handle settling. The try/except is
    # belt-and-suspenders in case a future patchright still auto-waits.
    try:
        page.get_by_role("button", name=_FINAL_SUBMIT_NAME).first.click(
            no_wait_after=True)
    except PWTimeout:
        if verbose:
            print("-> submit click navigation-wait timed out; continuing",
                  flush=True)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(5_000)


def download_crosstab_patchright(
    view_url: str,
    crosstab_sheet: str,
    out_path: Path,
    verbose: bool = True,
    page: Optional[Page] = None,
) -> Path:
    """Download a Tableau Crosstab via the patchright stealth session.

    If `page` is provided, reuses it (caller manages browser lifecycle —
    use this when downloading multiple crosstabs in one run to avoid
    relaunching Chrome each time). Otherwise launches its own session,
    runs the download, and closes."""
    if page is not None:
        return drive_crosstab_dialog(page, view_url, crosstab_sheet, out_path,
                                     verbose=verbose)
    with tableau_session(verbose=verbose) as pg:
        return drive_crosstab_dialog(pg, view_url, crosstab_sheet, out_path,
                                     verbose=verbose)


def requests_session_from_page(page: Page):
    """Build a requests.Session pre-loaded with the patchright context's
    Tableau cookies, so HTTP-direct CSV pulls (tableau_http.download_view_csv)
    work off the same unattended session — no CDP / Report Chrome needed.
    Mirrors tableau_http._grab_session but sources cookies from patchright."""
    import requests
    s = requests.Session()
    for c in page.context.cookies():
        s.cookies.set(c["name"], c["value"], domain=c["domain"])
    return s


def scrape_view_data_patchright(
    view_url: str,
    out_path: Path,
    verbose: bool = True,
    activate_xy: Optional[tuple] = None,
    scrape_kwargs: Optional[dict] = None,
    page: Optional[Page] = None,
):
    """Scrape Tableau's Download → Data 'View Data' window via patchright.

    Used as a fallback for dashboards whose Crosstab dialog silently
    no-ops the thumbnail click (SARA, Money Lost). The View Data path
    goes through a different Tableau UI mechanism that isn't subject
    to the same CDP-detection bug — and works in patchright even when
    Crosstab doesn't.

    Writes the scraped rows to `out_path` as UTF-8 tab-delimited so
    `_read_tab_csv` parses it without changes.

    Args:
      view_url: Tableau view URL.
      out_path: where to write the .csv (tab-delimited).
      activate_xy: fractional (x, y) within the viz to click before
        opening Download — required on multi-worksheet dashboards
        where Download → Data is disabled until a worksheet is active.
      scrape_kwargs: tuning knobs forwarded to `_scrape_view_data_grid`
        (jump_every, scroll_step, scroll_wait_ms, stale_max, max_iter).
        For sparse single-group grids that the default alternating
        incremental+jump strategy skips middle rows on, pass
        {'jump_every': None, 'scroll_step': 0.35, 'scroll_wait_ms': 1800,
         'stale_max': 30}.
      page: reuse a tableau_session() page (caller manages lifecycle).
    """
    def _do(pg):
        ctx = pg.context
        fields, records = _scrape_one_view_data(
            pg, ctx, view_url, verbose=verbose,
            activate_xy=activate_xy, scrape_kwargs=scrape_kwargs)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["\t".join(fields)] + ["\t".join(r) for r in records]
        out_path.write_text("\n".join(lines), encoding="utf-8")
        if verbose:
            print(f"saved View Data: {out_path} ({len(records)} rows)", flush=True)
        return out_path

    if page is not None:
        return _do(page)
    with tableau_session(verbose=verbose) as pg:
        return _do(pg)


# ---------------------------------------------------------------------------
# AppStream (ApplicantStream) — same ownerville SSO as Tableau, p=701.
# ---------------------------------------------------------------------------
# fetch_office._attach() needs a human-launched debug Chrome with an AppStream
# tab already logged in. But AppStream auth rides the SAME ownerville 'rqst'
# SSO token as Tableau — just p=701 instead of p=81 (see fetch_office.
# _ensure_on_retention_report). So the patchright stealth profile that already
# beats ownerville's Cloudflare for Tableau can seed AppStream too, with no
# manual Chrome. UNVERIFIED LIVE as of 2026-05-25 — smoke-test first with:
#   python -m automations.shared.tableau_patchright --appstream
# before wiring fetch_office / the recruiting run to it.

APPSTREAM_BASE = "https://applicantstream.com/index.cfm"
# AppStream rqst tokens can carry hyphens + uppercase (fetch_office matches
# [A-Z0-9-]); broaden the charset vs the Tableau token regex.
_APPSTREAM_RQST_RE = re.compile(r"rqst=([A-Za-z0-9_-]+)")


def _sso_to_appstream(page: Page, verbose: bool = True) -> Page:
    """Seed an AppStream session by following ownerville's SSO link with
    p=701. Mirrors _sso_to_tableau (which uses p=81 for Tableau). Leaves the
    page on an authenticated applicantstream.com URL and returns it."""
    if verbose:
        print(f"-> Fetching AppStream SSO token from {OWNERVILLE_V2_URL}", flush=True)
    page.goto(OWNERVILLE_V2_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6_000)
    m = _APPSTREAM_RQST_RE.search(page.url or "")
    if not m:
        href = page.evaluate(
            "() => { const a=[...document.querySelectorAll('a')]"
            ".find(x=>/p=701/.test(x.getAttribute('href')||'')); "
            "return a?a.getAttribute('href'):''; }")
        m = _APPSTREAM_RQST_RE.search(href or "")
    if not m:
        # Fall back to any rqst token in the page HTML — it's an ownerville
        # session token that works for both p=81 and p=701.
        m = _APPSTREAM_RQST_RE.search(
            page.evaluate("() => document.documentElement.innerHTML") or "")
    if not m:
        raise RuntimeError(
            "Couldn't find an ownerville SSO token (rqst=...) for AppStream — "
            f"ownerville login isn't valid. Delete {PROFILE_DIR} and retry to "
            "force a fresh login.")
    sso_url = f"{APPSTREAM_BASE}?rqst={m.group(1)}&p=701"
    if verbose:
        print("-> Following SSO link to AppStream…", flush=True)
    page.goto(sso_url, wait_until="domcontentloaded")
    page.wait_for_timeout(12_000)
    if verbose:
        print(f"-> AppStream session established (page at {(page.url or '')[:80]})",
              flush=True)
    return page


@contextmanager
def appstream_session(headless: bool = False, verbose: bool = True) -> Iterator[Page]:
    """Yield a Page logged into AppStream via ownerville SSO — the unattended
    replacement for fetch_office._attach() (which needs a human-launched debug
    Chrome with an AppStream tab). Uses the shared persistent profile, so the
    ownerville login carries across runs.

    UNVERIFIED LIVE (2026-05-25) — smoke-test before wiring it in."""
    PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), channel="chrome",
                headless=headless, no_viewport=True)
        except Exception as e:
            if verbose:
                print(f"[appstream_session] system Chrome unavailable ({e!r}) — "
                      "falling back to bundled Chromium", flush=True)
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), headless=headless, no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            # Ensure ownerville is logged in (drives the form if not), then SSO.
            if verbose:
                print(f"-> Loading {LOGIN_URL}", flush=True)
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)
            if (page.locator(_PASSWORD_SELECTOR).count() > 0
                    or page.locator(_USERNAME_SELECTOR).count() > 0):
                _drive_login_form(page, verbose=verbose)
            elif verbose:
                print("-> ownerville session reused from profile", flush=True)
            _sso_to_appstream(page, verbose=verbose)
            yield page
        finally:
            ctx.close()


@contextmanager
def ownerville_session(headless: bool = False,
                      verbose: bool = True) -> Iterator[Page]:
    """Yield a Page logged into ownerville.com via patchright — WITHOUT the
    Tableau SSO hop. For reports that scrape ownerville's own pages (e.g.
    focus_office_att rep breakdowns). Same login + shared profile as
    tableau_session; the caller navigates to the ownerville URLs it needs."""
    PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), channel="chrome",
                headless=headless, no_viewport=True)
        except Exception:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), headless=headless,
                no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if verbose:
                print(f"-> Loading {LOGIN_URL}", flush=True)
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)
            if (page.locator(_PASSWORD_SELECTOR).count() > 0
                    or page.locator(_USERNAME_SELECTOR).count() > 0):
                _drive_login_form(page, verbose)
            elif verbose:
                print("-> ownerville session reused from profile", flush=True)
            yield page
        finally:
            ctx.close()


# Dedicated profile for the DIRECT AppStream login, kept separate from the
# Tableau/ownerville profile: applicantstream.com auto-SSOs off an ownerville
# cookie (the short-lived p=701 report view) instead of showing the rcaptain
# login form, so the recruiting console needs its own clean profile.
APPSTREAM_PROFILE_DIR = (
    Path(__file__).resolve().parent.parent / "uploaded" / ".appstream_profile"
)
_APPSTREAM_USERNAME_SELECTOR = 'input[name="userName"], ' + _USERNAME_SELECTOR


@contextmanager
def appstream_direct_session(headless: bool = False,
                             verbose: bool = True,
                             profile_dir: Optional[Path] = None,
                             username: Optional[str] = None,
                             password: Optional[str] = None) -> Iterator[Page]:
    """Yield a Page logged DIRECTLY into AppStream as the recruiting account
    (rcaptain) via patchright stealth — a FULL, sustained console session with
    the #searchMC office switcher. This is the unattended replacement for
    fetch_office._attach() (debug-Chrome CDP, broken on Chrome 148).

    NOT appstream_session(): that rides the ownerville SSO and lands on a
    short-lived p=701 report view that times out within ~30s and has no office
    switcher. This logs in on AppStream's own two-step form (same shape as
    ownerville) and the session persists in a dedicated profile.

    Override args (used by daily_focus --alt-appstream for ICDs visible only
    from a different AppStream account):
      - profile_dir: use a separate profile (so rcaptain's cookies aren't
                     overwritten by the alternate account's session).
      - username / password: skip creds.py lookup; pass these directly to
                             the login form (lets the caller load them from
                             env without touching keychain/file)."""
    profile = profile_dir or APPSTREAM_PROFILE_DIR
    profile.mkdir(exist_ok=True, parents=True)
    user = username or creds.appstream_username()
    pwd  = password or creds.appstream_password()
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile), channel="chrome",
                headless=headless, no_viewport=True)
        except Exception as e:
            if verbose:
                print(f"[appstream_direct] system Chrome unavailable ({e!r}) — "
                      "bundled Chromium", flush=True)
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile), headless=headless,
                no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if verbose:
                print("-> Loading https://applicantstream.com/", flush=True)
            page.goto("https://applicantstream.com/",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(3_000)
            if (page.locator(_PASSWORD_SELECTOR).count() > 0
                    or page.locator(_APPSTREAM_USERNAME_SELECTOR).count() > 0):
                _drive_login_form(page, verbose, username=user, password=pwd)
            elif verbose:
                print("-> AppStream session reused from profile", flush=True)
            page.wait_for_timeout(3_000)
            if verbose:
                print(f"-> AppStream console ready "
                      f"(page at {(page.url or '')[:72]})", flush=True)
            yield page
        finally:
            ctx.close()


if __name__ == "__main__":
    # Smoke tests for the patchright sessions. Run headed so you can watch
    # Cloudflare + SSO. --appstream verifies the new (unverified) AppStream
    # login; default verifies the Tableau login.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--appstream", action="store_true",
                    help="Smoke-test the AppStream patchright login.")
    args = ap.parse_args()
    if args.appstream:
        with appstream_session(verbose=True) as pg:
            url = pg.url or ""
            print(f"\nAppStream page URL: {url}")
            ok = "applicantstream.com" in url and "login" not in url.lower()
            print("✅ AppStream login looks good" if ok else
                  "❌ AppStream login did NOT land on an authed page — check above")
    else:
        with tableau_session(verbose=True) as pg:
            url = pg.url or ""
            print(f"\nTableau page URL: {url}")
            print("✅ Tableau login looks good" if "online.tableau.com" in url
                  else "❌ Tableau login did NOT land on Tableau — check above")

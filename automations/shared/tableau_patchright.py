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


PROFILE_DIR = (
    Path(__file__).resolve().parent.parent / "uploaded" / ".browser_profile"
)

LOGIN_URL = "https://ownerville.com"
# v2 is the internal dashboard that holds the 'Login to Tableau' SSO
# link. The CDP-attached path (opt_phase._reauth_tableau) navigates
# here to extract the rqst token and ride it through to Tableau.
OWNERVILLE_V2_URL = "https://v2.ownerville.com/index.cfm"
# Hardcoded per the order_log.py convention. Local-only Hub means this
# is acceptable; if the repo ever goes public, switch to env vars / keyring.
OWNERVILLE_USERNAME = "rhidalgo"
OWNERVILLE_PASSWORD = "Alphalete123!"

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


def _drive_login_form(page: Page, verbose: bool) -> None:
    """Drive the ownerville two-step login form. Mirrors order_log.login."""
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
    page.fill(_USERNAME_SELECTOR, OWNERVILLE_USERNAME)

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
    page.fill(_PASSWORD_SELECTOR, OWNERVILLE_PASSWORD)
    page.wait_for_timeout(_PRE_SUBMIT_PAUSE_MS)

    if verbose:
        print("-> Submitting", flush=True)
    page.get_by_role("button", name=_FINAL_SUBMIT_NAME).first.click()
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

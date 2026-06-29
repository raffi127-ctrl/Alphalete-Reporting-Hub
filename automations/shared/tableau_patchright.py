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

Auth (since 2026-06-17): the default path restores a manually-exported
ownerville session (.ownerville_storage_state.json) — inject the login
cookies, let v2.ownerville mint a fresh rqst SSO token, ride it to
Tableau. No login form is driven, because ownerville's 'verify you are
human' check can't be cleared unattended. A missing/expired session
FAILS FAST (re-export via output/_scratch_ownerville_export_state.py).
The legacy form-drive survives behind allow_form_login=True for
interactive/debug use only.
"""

from __future__ import annotations

import json
import re
import time
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

# A manually-exported ownerville session — the ColdFusion login cookies
# (CFID/CFTOKEN/…) from which v2.ownerville mints a fresh rqst SSO token.
# Produced by a one-time manual login via
# output/_scratch_ownerville_export_state.py. GITIGNORED — live session
# cookies. This is how unattended runs authenticate WITHOUT driving the login
# form, whose Cloudflare 'verify you are human' check can't be cleared headless.
OWNERVILLE_STORAGE_STATE = (
    Path(__file__).resolve().parent / ".ownerville_storage_state.json"
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

# Browser-launch collision handling. When two reports run at once they share
# one persistent profile dir; the second launch fails with "profile already
# in use" / "existing browser session" and the run crashes (Eve glitches:
# rows 7,23,46,58,60,61,65,66). Wait + retry so the second run rides out the
# first's release instead of failing.
_LAUNCH_RETRIES = 4
_LAUNCH_WAIT_S = 8.0


def _is_profile_in_use(exc: Exception) -> bool:
    s = str(exc).lower()
    return ("already in use" in s or "existing browser session" in s
            or "processsingleton" in s
            or ("profile" in s and "in use" in s))


def _launch_persistent(p, user_data_dir, *, headless: bool, label: str,
                       verbose: bool = True):
    """launch_persistent_context with the existing system-chrome → bundled-
    chromium fallback UNCHANGED, wrapped in a wait+retry for the "profile
    already in use" collision.

    INERT on a normal launch: a healthy launch returns on the first try with
    byte-identical behavior to before. The retry only triggers on the exact
    profile-in-use failure that otherwise crashes the run — so it cannot
    affect a working patchright run."""
    # Force a large window so multi-sheet Tableau dashboards render fully
    # in-view (the Program Summary DOWNLINE VIEW's downline worksheet sits
    # below the fold at the old ~784x449 default, which made its header
    # unclickable for the activate_xy download path). Fractional activate_xy
    # coords (e.g. FIBER_OVERVIEW_XY) are resolution-independent, so the other
    # scrape sources are unaffected. no_viewport stays True (real window).
    base = dict(user_data_dir=str(user_data_dir), headless=headless,
                no_viewport=True,
                args=["--window-size=1680,1280", "--window-position=0,0"])
    prefer_chrome = True
    last: Optional[Exception] = None
    for attempt in range(_LAUNCH_RETRIES):
        try:
            if prefer_chrome:
                try:
                    return p.chromium.launch_persistent_context(
                        channel="chrome", **base)
                except Exception as e:
                    if _is_profile_in_use(e):
                        raise  # bundled won't help (same profile); wait+retry
                    if verbose:
                        print(f"[{label}] system Chrome unavailable ({e!r}) — "
                              "falling back to bundled Chromium", flush=True)
                    prefer_chrome = False
            return p.chromium.launch_persistent_context(**base)
        except Exception as e:
            last = e
            if _is_profile_in_use(e) and attempt < _LAUNCH_RETRIES - 1:
                if verbose:
                    print(f"[{label}] browser profile is in use by another run "
                          f"— waiting {_LAUNCH_WAIT_S:.0f}s then retrying "
                          f"({attempt + 1}/{_LAUNCH_RETRIES})", flush=True)
                time.sleep(_LAUNCH_WAIT_S)
                continue
            raise
    assert last is not None
    raise last


@contextmanager
def tableau_session(headless: bool = False, verbose: bool = True,
                    allow_form_login: bool = False) -> Iterator[Page]:
    """Yield a Page logged into Tableau via ownerville SSO.

    Uses Order Log's persistent profile + the exported ownerville
    storage_state so the login survives across runs without driving the
    Turnstile form. allow_form_login=True re-enables the legacy form-drive
    (interactive/debug ONLY)."""
    PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, PROFILE_DIR, headless=headless,
                                 label="tableau_patchright", verbose=verbose)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _ensure_tableau_authenticated(page, verbose=verbose,
                                          allow_form_login=allow_form_login)
            yield page
        finally:
            ctx.close()


def _ensure_tableau_authenticated(page: Page, verbose: bool = True,
                                  allow_form_login: bool = False) -> None:
    """Make sure `page` has a Tableau session cookie. Two steps:
      1. Ensure ownerville is logged in (storage_state reuse; form only if
         allow_form_login=True).
      2. Visit v2.ownerville.com, extract the rqst SSO token, and
         redirect via the Tableau SSO URL. After this returns, any
         subsequent goto() to a Tableau view URL will load the viz
         instead of bouncing to login.
    """
    _ensure_ownerville_logged_in(page, verbose=verbose,
                                 allow_form_login=allow_form_login)
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


def _ownerville_session_valid(page: Page, verbose: bool = True) -> bool:
    """True only if the ownerville session is GENUINELY authenticated — i.e.
    visiting v2.ownerville.com yields a real rqst SSO token (in the URL or an
    in-page SSO link). A 'reused from profile' landing page with no rqst is a
    STALE cookie, not a live session — the bug behind the 'no rqst' glitches
    (Eve rows 38/69). This is the same token _sso_to_tableau relies on."""
    try:
        page.goto(OWNERVILLE_V2_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(4_000)
    except Exception:
        return False
    if re.search(r"rqst=([A-Za-z0-9_]+)", page.url or ""):
        return True
    try:
        href = page.evaluate(
            "() => { const a=[...document.querySelectorAll('a')]"
            ".find(x=>/rqst=/.test(x.getAttribute('href')||'')); "
            "return a?a.getAttribute('href'):''; }")
        return bool(re.search(r"rqst=([A-Za-z0-9_]+)", href or ""))
    except Exception:
        return False


def _reuse_ownerville_storage_state(ctx, page: Page, verbose: bool) -> bool:
    """Restore a manually-exported ownerville session onto the stealth context.
    Inject the saved cookies (the ColdFusion login session: CFID/CFTOKEN/…),
    then validate via _ownerville_session_valid — v2.ownerville mints a FRESH
    rqst SSO token from the login cookie. Unlike the AppStream twin there is NO
    token replay: the exported rqst is ephemeral, so we persist the login cookie
    and let v2 re-mint. Returns True iff a live rqst appears.

    A missing / unreadable state file returns False so the caller fails fast
    instead of falling to the Turnstile form unattended."""
    if not OWNERVILLE_STORAGE_STATE.exists():
        if verbose:
            print(f"-> no storage_state at {OWNERVILLE_STORAGE_STATE.name}",
                  flush=True)
        return False
    try:
        state = json.loads(OWNERVILLE_STORAGE_STATE.read_text())
    except Exception as e:
        if verbose:
            print(f"-> storage_state unreadable ({e!r}) — ignoring", flush=True)
        return False
    cookies = state.get("cookies", [])
    if cookies:
        try:
            ctx.add_cookies(cookies)
        except Exception as e:
            if verbose:
                print(f"-> add_cookies failed ({e!r})", flush=True)
    if verbose:
        print(f"-> storage_state: {len(cookies)} cookie(s) injected", flush=True)
    return _ownerville_session_valid(page, verbose=verbose)


def _ensure_ownerville_logged_in(page: Page, verbose: bool = True,
                                 allow_form_login: bool = False) -> None:
    """Guarantee a LIVE ownerville session.

    Auth path (since 2026-06-17): restore a manually-exported session
    (OWNERVILLE_STORAGE_STATE) rather than driving the login form. ownerville's
    form hits a Cloudflare 'verify you are human' check that can't be cleared
    unattended, so a missing/expired session FAILS FAST with a clear error
    (re-export via output/_scratch_ownerville_export_state.py) instead of
    stalling on the check.

    Steps:
      1. Reuse the exported storage_state (inject cookies → rqst check).
      2. Failing that, try whatever cookie the persistent profile already holds.
      3. Unless allow_form_login=True, fail fast — never touch the Turnstile.
      4. allow_form_login=True re-enables the legacy two-step form-drive
         (interactive/debug ONLY — it hits the Turnstile and stalls unattended).
    """
    # (1) Primary automated path: exported session, no form / Turnstile.
    if _reuse_ownerville_storage_state(page.context, page, verbose):
        if verbose:
            print("-> ownerville session restored from storage_state "
                  "(rqst present)", flush=True)
        return

    # (2) Fall back to the persistent-profile cookie, if it's still live.
    if _ownerville_session_valid(page, verbose=verbose):
        if verbose:
            print("-> ownerville session reused from profile (rqst present)",
                  flush=True)
        return

    # (3) Unattended default: fail loud + clear, pointing at the re-export.
    if not allow_form_login:
        raise RuntimeError(
            "ownerville session expired or missing — run "
            "output/_scratch_ownerville_export_state.py to re-export "
            f"{OWNERVILLE_STORAGE_STATE.name}. (storage_state reuse path; the "
            "login form is disabled because its Cloudflare 'verify you are "
            f"human' check can't be cleared unattended.) Profile: {PROFILE_DIR}")

    # (4) Legacy opt-in form-drive — interactive/debug ONLY (hits the Turnstile).
    if verbose:
        print("-> [allow_form_login] driving ownerville login form (hits the "
              "Cloudflare check — interactive use only)", flush=True)
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3_000)
    try:
        page.wait_for_selector(
            f"{_PASSWORD_SELECTOR}, {_USERNAME_SELECTOR}", timeout=20_000)
    except Exception:
        pass
    _drive_login_form(page, verbose=verbose)
    if _ownerville_session_valid(page, verbose=verbose):
        if verbose:
            print("-> ownerville form login succeeded (rqst present)", flush=True)
        return
    raise RuntimeError(
        "ownerville form login failed — still no rqst after driving the form. "
        "Check ownerville-creds.json (username/password) or a Cloudflare block. "
        f"Profile: {PROFILE_DIR}")


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
    runs the download, and closes.

    SELF-HEAL (Megan 2026-06-08): retry on any failure. The dominant
    failure mode across every report is a transient Tableau load/render
    flake — '0 thumbs', a 120s toolbar timeout, a half-rendered crosstab —
    that clears on a fresh attempt. drive_crosstab_dialog re-navigates
    (about:blank → goto) each call, so the retry is a clean reload. A
    genuinely broken/stale view fails every attempt and the error still
    propagates, so callers' skip+flag resilience is unchanged.

    BUMPED 2->3 attempts (2026-06-14): one retry wasn't enough for the
    heaviest vizzes — Fiber Activations hit 120s wait_for timeouts on two
    back-to-back runs (6/11) and again 6/12. A 3rd attempt with a short
    backoff (lets Tableau's server-side render settle) clears most of the
    remainder. Retries only fire on failure, so happy-path runtime is
    unchanged."""
    MAX_ATTEMPTS = 3
    BACKOFF_S = 3
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if page is not None:
                return drive_crosstab_dialog(page, view_url, crosstab_sheet,
                                             out_path, verbose=verbose)
            with tableau_session(verbose=verbose) as pg:
                return drive_crosstab_dialog(pg, view_url, crosstab_sheet,
                                             out_path, verbose=verbose)
        except Exception as e:
            last_err = e
            if attempt < MAX_ATTEMPTS:
                if verbose:
                    print(f"  ⚠ crosstab pull failed ({str(e).splitlines()[0][:90]})"
                          f" — retry {attempt}/{MAX_ATTEMPTS - 1} after {BACKOFF_S}s…",
                          flush=True)
                time.sleep(BACKOFF_S)
    raise last_err


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
def appstream_session(headless: bool = False, verbose: bool = True,
                      allow_form_login: bool = False) -> Iterator[Page]:
    """Yield a Page logged into AppStream via ownerville SSO — the unattended
    replacement for fetch_office._attach() (which needs a human-launched debug
    Chrome with an AppStream tab). Uses the shared persistent profile +
    ownerville storage_state, so the login carries across runs.

    allow_form_login=True re-enables the legacy form-drive (interactive/debug
    ONLY). UNVERIFIED LIVE (2026-05-25) — smoke-test before wiring it in."""
    PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, PROFILE_DIR, headless=headless,
                                 label="appstream_session", verbose=verbose)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _ensure_ownerville_logged_in(page, verbose=verbose,
                                         allow_form_login=allow_form_login)
            _sso_to_appstream(page, verbose=verbose)
            yield page
        finally:
            ctx.close()


@contextmanager
def ownerville_session(headless: bool = False,
                      verbose: bool = True,
                      allow_form_login: bool = False) -> Iterator[Page]:
    """Yield a Page logged into ownerville.com via patchright — WITHOUT the
    Tableau SSO hop. For reports that scrape ownerville's own pages (e.g.
    focus_office_att rep breakdowns). Same login + shared profile +
    storage_state as tableau_session; the caller navigates to the ownerville
    URLs it needs. allow_form_login=True re-enables the legacy form-drive
    (interactive/debug ONLY)."""
    PROFILE_DIR.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, PROFILE_DIR, headless=headless,
                                 label="ownerville_session", verbose=verbose)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _ensure_ownerville_logged_in(page, verbose=verbose,
                                         allow_form_login=allow_form_login)
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

# A manually-exported AppStream session (cookies incl. CFID/CFTOKEN + the
# rqst_<TOKEN> SSO cookies). Produced by a one-time human login via
# output/_scratch_appstream_export_state.py. GITIGNORED — carries live session
# cookies. This is how the unattended path authenticates WITHOUT driving the
# login form, whose Cloudflare Turnstile can't be cleared unattended.
APPSTREAM_STORAGE_STATE = (
    Path(__file__).resolve().parent / ".appstream_storage_state.json"
)


def _reuse_appstream_storage_state(ctx, page: Page, verbose: bool) -> bool:
    """Restore a manually-exported AppStream session onto the persistent stealth
    context. Inject the saved cookies, then for each saved rqst SSO token
    navigate to index.cfm?rqst=<TOKEN>&p=701 — the URL form AppStream keys the
    authenticated console to (cookies alone land on Login; a bare index.cfm or a
    stale token bounces back). Returns True once #searchMC appears.

    Tokens can be stale (the export may hold several rqst_* cookies, only one
    live) — we try each and take the first that loads the console."""
    if not APPSTREAM_STORAGE_STATE.exists():
        if verbose:
            print(f"-> no storage_state at {APPSTREAM_STORAGE_STATE.name}",
                  flush=True)
        return False
    try:
        state = json.loads(APPSTREAM_STORAGE_STATE.read_text())
    except Exception as e:
        if verbose:
            print(f"-> storage_state unreadable ({e!r}) — ignoring", flush=True)
        return False
    cookies = state.get("cookies", [])
    if cookies:
        try:
            ctx.add_cookies(cookies)
        except Exception as e:
            if verbose:
                print(f"-> add_cookies failed ({e!r})", flush=True)
    tokens = [c["name"][len("rqst_"):] for c in cookies
              if c.get("name", "").startswith("rqst_")]
    if verbose:
        print(f"-> storage_state: {len(cookies)} cookies, "
              f"{len(tokens)} rqst token(s)", flush=True)
    for tok in tokens:
        url = f"{APPSTREAM_BASE}?rqst={tok}&p=701"
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector("#searchMC", timeout=8_000)
            if verbose:
                print(f"-> AppStream console restored from storage_state "
                      f"(rqst={tok[:8]}…, page at {(page.url or '')[:72]})",
                      flush=True)
            return True
        except PWTimeout:
            continue
        except Exception:
            continue
    return False


@contextmanager
def appstream_direct_session(headless: bool = False,
                             verbose: bool = True,
                             profile_dir: Optional[Path] = None,
                             username: Optional[str] = None,
                             password: Optional[str] = None,
                             allow_form_login: bool = False) -> Iterator[Page]:
    """Yield a Page on the AppStream recruiting console (#searchMC office
    switcher) for the rcaptain account, via patchright stealth. Unattended
    replacement for fetch_office._attach() (debug-Chrome CDP, broken on Chrome
    148).

    Auth path (since 2026-06-16): restore a manually-exported session
    (APPSTREAM_STORAGE_STATE) instead of driving the login form. AppStream's
    login form now hits a Cloudflare Turnstile that can't be cleared
    unattended, so a missing/expired session FAILS FAST with a clear error
    rather than stalling on the check. Re-export with
    output/_scratch_appstream_export_state.py after a one-time manual login.

    allow_form_login=True re-enables the legacy two-step form-drive (the path
    that hits the Turnstile) — interactive/debug use ONLY; never the default
    automated path.

    Override args (used by daily_focus --alt-appstream for ICDs visible only
    from a different AppStream account):
      - profile_dir: use a separate profile (so rcaptain's cookies aren't
                     overwritten by the alternate account's session).
      - username / password: skip creds.py lookup; pass these directly to
                             the login form (only relevant with
                             allow_form_login=True)."""
    profile = profile_dir or APPSTREAM_PROFILE_DIR
    profile.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, profile, headless=headless,
                                 label="appstream_direct", verbose=verbose)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            # Primary (automated) path: restore the exported session. Never
            # touches the login form / Turnstile.
            if _reuse_appstream_storage_state(ctx, page, verbose):
                yield page
                return

            # NOTE (Megan 2026-06-22): unlike Tableau, AppStream can't be
            # seeded by an ownerville URL hop — applicantstream.com sits behind
            # its OWN Cloudflare challenge, so a token-in-URL navigation just
            # bounces to its login page (verified 4 ways). The only path that
            # establishes the session is a one-time interactive login that
            # clears the Turnstile; the session is then kept warm so scheduled
            # runs don't hit the wall. See _capture_appstream_state() below.
            if not allow_form_login:
                raise RuntimeError(
                    "AppStream session expired or missing. The saved session "
                    "(.appstream_storage_state.json) has no live token. Re-seed "
                    "it with a one-time login:\n"
                    "    PYTHONPATH=. .venv/bin/python -m "
                    "automations.shared.tableau_patchright --appstream-login\n"
                    "(a browser opens; clear the Cloudflare check + log in as "
                    "rcaptain once, and it saves the session). The session "
                    "holder then keeps it warm for scheduled runs.")

            # Legacy opt-in form-drive (interactive/debug only — hits the
            # Cloudflare Turnstile, so it stalls in unattended runs).
            user = username or creds.appstream_username()
            pwd  = password or creds.appstream_password()
            if verbose:
                print("-> [allow_form_login] driving AppStream login form",
                      flush=True)
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


def _capture_appstream_state(verbose: bool = True) -> bool:
    """One-time interactive capture of the AppStream session. Opens a HEADED
    browser on the persistent .appstream_profile; the human clears the
    Cloudflare check + logs in as rcaptain. Once the office console (#searchMC)
    appears, the session (cookies incl. CFID/CFTOKEN + the rqst_<TOKEN> SSO
    cookies) is written to APPSTREAM_STORAGE_STATE for the unattended runs to
    reuse. AppStream's own Cloudflare can't be cleared headlessly, so this
    interactive seed is the only way to (re)establish the session; the session
    holder keeps it warm afterward."""
    profile = APPSTREAM_PROFILE_DIR
    profile.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, profile, headless=False,
                                 label="appstream_login", verbose=verbose)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # Land on the LOGIN page, not ?p=701. p=701 is a deep report page
        # that needs an already-authenticated session — opening it cold shows
        # "Valid User ID Not Obtained! Cannot Proceed!", which the human then
        # has to work around by retyping the URL (Megan 2026-06-26). The bare
        # site root serves the login form, so the human can sign in directly.
        try:
            page.goto("https://applicantstream.com/", wait_until="domcontentloaded")
        except Exception:
            pass
        print("\n" + "=" * 64)
        print("  LOG INTO APPLICANTSTREAM IN THE BROWSER WINDOW THAT OPENED")
        print("  • clear the Cloudflare check if shown")
        print("  • sign in as rcaptain")
        print("  • THEN go to:  applicantstream.com/index.cfm?p=701")
        print("    (that loads the office search box — which is what gets saved)")
        print("  Waiting for the office console to load (up to 5 min)…")
        print("=" * 64 + "\n", flush=True)
        seen = False
        for _ in range(60):
            try:
                if page.locator("#searchMC").count() > 0:
                    seen = True
                    break
                # NO auto-nudge to p=701. The old code jumped there whenever the
                # login form was absent — but that also fires DURING the
                # Cloudflare check (no form on screen), bouncing to the "Valid
                # User ID Not Obtained" error mid-login (Megan 2026-06-26). The
                # human navigates to p=701 themselves once logged in (see the
                # printed instructions); we just watch for #searchMC to appear.
            except Exception:
                pass
            page.wait_for_timeout(5_000)
        if not seen:
            print("❌ Didn't detect the office console (#searchMC) within 5 min — "
                  "nothing saved. Re-run and finish the login.", flush=True)
            ctx.close()
            return False
        state = ctx.storage_state()
        APPSTREAM_STORAGE_STATE.write_text(json.dumps(state))
        cookies = state.get("cookies", [])
        n_rqst = sum(1 for c in cookies if c.get("name", "").startswith("rqst_"))
        print(f"✅ Saved AppStream session ({len(cookies)} cookies, {n_rqst} "
              f"rqst token(s)) → {APPSTREAM_STORAGE_STATE.name}", flush=True)
        if n_rqst == 0:
            print("⚠ No rqst_ token captured — the unattended reuse needs one. "
                  "Make sure you reached the office switcher before this saved.",
                  flush=True)
        ctx.close()
        return n_rqst > 0


if __name__ == "__main__":
    # Smoke tests for the patchright sessions. Run headed so you can watch
    # Cloudflare + SSO. --appstream verifies the new (unverified) AppStream
    # login; default verifies the Tableau login.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--appstream", action="store_true",
                    help="Smoke-test the AppStream patchright login.")
    ap.add_argument("--appstream-login", action="store_true",
                    help="One-time interactive AppStream login → saves the "
                         "session for unattended runs.")
    args = ap.parse_args()
    if args.appstream_login:
        import sys as _sys
        _sys.exit(0 if _capture_appstream_state(verbose=True) else 1)
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

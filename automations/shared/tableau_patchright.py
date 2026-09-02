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

import atexit
import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
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

# The 'verify you are human' box on the password step clears ITSELF — but only
# if you leave it alone long enough. Megan 2026-09-01: "you just wait 30 sec
# before hitting submit on the PW". At the old 3s the submit landed while the
# check was still running and the login failed, which is what made ownerville
# look like it needed a person at the screen: the session holder gave up and
# opened a window, and Lucy 1 sat with no session for an afternoon.
#
# 30s of waiting per login is cheap — a report logs in once and rides the
# session for hours, and the alternative is a human walking to a Mac mini.
# 30s, NOT 10 (Megan 2026-09-01: "ownerville can work the same way as app
# stream you just have to wait 30 seconds before submitting PW for the
# cloudfare to clear").
#
# At 10s the form submitted BEFORE Cloudflare had cleared, so the login looked
# like it worked — "-> Submitting" with no error — and then the session came
# back invalid. That is exactly what happened driving ownerville into the
# holder profile on Lucy 1 that evening: the whole form ran, then
# "SESSION VALID: False". It reads as a credential or gating problem and is
# neither; the check simply had not finished.
#
# This is the same mechanism that made AppStream look "human-gated since
# 2026-08-20" for twelve days. The check clears itself — it just needs longer
# than we were giving it. Costs 20 extra seconds on a path that runs at most
# a couple of times an hour.
# Set once a process has already tried to self-heal the ownerville session, so
# a bad credential produces ONE failed login and a clear error rather than a
# retry loop against the account.
_OV_SELFHEAL_TRIED = False

_CLOUDFLARE_WAIT_MS = 30_000
_PRE_SUBMIT_PAUSE_MS = 30_000

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


class AppStreamBusy(Exception):
    """Raised by appstream_direct_session(yield_if_busy=True) when the profile is
    already in use by another run — so a LOW-PRIORITY caller (resume_pushing) can
    step aside and retry later instead of making the other run wait."""


# ---------------------------------------------------------------------------
# Cross-process profile lock.
#
# The wait+retry above only rides out a collision for ~32s (4x8s). A report
# that runs 6-15min will starve a sibling that fires mid-run: on 2026-07-20
# THREE browser reports fired at 7:00 on Lucy 2 (BOX Order Log, Vantura Churn,
# Carlos Captainship Headcount) sharing ONE profile — BOX held it ~6min, the
# headcount waited 32s and died.
#
# Lucy 1 never hits this: its orchestrator runs reports SEQUENTIALLY in one
# process. This lock gives Lucy 2's independently-scheduled LaunchAgents the
# same property — every browser launch takes an exclusive OS lock on its
# profile dir and HOLDS it until the context closes, so a second report that
# fires mid-run waits its turn instead of racing. Keyed on the profile PATH, so
# reports on different profiles (.browser_profile vs .appstream_profile vs the
# holder's .browser_profile_holder) never block each other — only same-profile
# launches serialize.
#
# flock is advisory and released automatically when the fd closes OR the owning
# process dies, so a crashed report can never leave a stuck lock. Unix-only; on
# Windows (fcntl absent) it degrades to a no-op and the wait+retry still guards.
try:
    import fcntl as _fcntl
except ImportError:            # Windows — no flock; keep the wait+retry behavior
    _fcntl = None

_PROFILE_LOCK_WAIT_S = 1800.0  # ceiling: wait up to 30min for a long report
_PROFILE_LOCK_POLL_S = 2.0
# Of its own budget, how much a run may spend WAITING for a busy profile before
# it gives up and lets the launch fail loudly. The rest is the work itself.
_PROFILE_WAIT_SHARE = 0.4
_PROFILE_WAIT_FLOOR_S = 60.0


def _profile_wait_budget() -> float:
    """How long THIS run may sit waiting for a profile someone else holds.

    WHY THIS ISN'T THE FLAT 1800s ANY MORE (2026-08-28): 30 minutes is longer
    than most reports are allowed to live. `mobrium_list` has a 12-minute
    timeout, and on 2026-08-28 it spent BOTH of its attempts inside this wait —
    killed mid-wait each time, so it wrote nothing, posted nothing, and left no
    error in the log at all (the kill lands before the launch that would have
    raised). Waiting past your own deadline can produce nothing else: a silent
    death, and a retry burned on the same wait.

    Capping the wait at a share of the run's budget converts that into a FAST,
    named failure ("Opening in existing browser session") with attempts 2 and 3
    still intact — and a retry twelve minutes later is exactly the thing most
    likely to find the profile free.

    The orchestrator exports HUB_REPORT_TIMEOUT_S (mini_control's `rerun` too).
    Without it — a hand run, a module driven directly — nothing changes and the
    full ceiling applies.
    """
    raw = os.environ.get("HUB_REPORT_TIMEOUT_S", "").strip()
    if not raw:
        return _PROFILE_LOCK_WAIT_S
    try:
        budget = float(raw)
    except ValueError:
        return _PROFILE_LOCK_WAIT_S
    if budget <= 0:
        return _PROFILE_LOCK_WAIT_S
    return max(_PROFILE_WAIT_FLOOR_S,
               min(_PROFILE_LOCK_WAIT_S, budget * _PROFILE_WAIT_SHARE))
# How often, while waiting, to re-check whether the thing holding this profile is
# an ORPHAN Chrome rather than a live run. See _clear_orphan_holder.
_ORPHAN_RECHECK_S = 60.0


def _lock_holder(path) -> str:
    """Best-effort 'pid 1234 (Google Chrome)' for whoever holds `path`, for the
    log line only. Empty string when lsof isn't there or says nothing — this is
    a diagnostic, never a decision."""
    try:
        out = subprocess.run(["lsof", "-t", str(path)], capture_output=True,
                             text=True, timeout=10).stdout.split()
    except Exception:          # noqa: BLE001 — diagnostics never raise
        return ""
    parts = []
    for pid in out[:3]:
        try:
            cmd = subprocess.run(["ps", "-p", pid, "-o", "comm="],
                                 capture_output=True, text=True,
                                 timeout=10).stdout.strip()
        except Exception:      # noqa: BLE001
            cmd = ""
        parts.append(f"pid {pid}" + (f" ({Path(cmd).name})" if cmd else ""))
    return ", ".join(parts)


def _clear_orphan_holder(profile_dir, *, verbose: bool, label: str) -> bool:
    """Kill a Chrome of OURS that outlived its run and still holds `profile_dir`.

    WHY (2026-08-19): a browser report killed at its timeout leaves its Chrome
    behind, and that orphan keeps the profile — so the next run sits in the wait
    below until ITS timeout kills it too, leaving one more orphan. Three
    tableau_screenshots runs burned their full 30 minutes on this exact wait that
    morning and the Country Trackers reached no channel at all. Nothing will ever
    release an orphan's hold, so waiting for it is pure dead time.

    ORPHANS ONLY (PPID 1, exact profile-dir name): a live sibling legitimately
    holding the profile is still waited for — that wait is the whole point of the
    lock. Best-effort and silent on failure; a cleanup that raises would take out
    the run it was trying to rescue."""
    try:
        from automations.day_orchestrator import chrome_guard
        freed = chrome_guard.unstick_profile(Path(profile_dir).name,
                                             verbose=False)
    except Exception:          # noqa: BLE001 — never let cleanup sink a launch
        return False
    if freed and verbose:
        print(f"[{label}] the profile was held by an ORPHAN Chrome from a killed "
              f"run (PID(s) {freed}) — closed it and taking the lock", flush=True)
    return bool(freed)


def _profile_lock_path(profile_dir) -> Path:
    """Sibling lockfile for a profile dir (…/.browser_profile.launchlock). Kept
    OUTSIDE the profile so Chrome never touches it."""
    p = Path(profile_dir)
    return p.parent / (p.name + ".launchlock")


def _acquire_profile_lock(profile_dir, *, busy_retries, verbose, label):
    """Take an exclusive lock on `profile_dir` before launching a browser on it.
    Returns an open fd to hold (release with _release_profile_lock), or None when
    locking is unavailable (Windows) or declined — in which case the caller just
    proceeds and the existing wait+retry handles any collision.

    Yield-fast callers (resume_pushing passes busy_retries=1) do NOT wait: if the
    profile is busy they get None immediately and fall through to collide+yield,
    exactly as before."""
    if _fcntl is None:
        return None
    yield_fast = busy_retries is not None and busy_retries <= 1
    wait_s = 0.0 if yield_fast else _profile_wait_budget()
    path = _profile_lock_path(profile_dir)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    except Exception:          # noqa: BLE001 — locking is best-effort
        return None
    start = time.monotonic()
    announced = False
    last_orphan_check = 0.0
    while True:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            if announced and verbose:
                print(f"[{label}] profile free — acquired lock, launching",
                      flush=True)
            return fd
        except OSError:
            # Held — but by WHAT? A live sibling is worth waiting for; a Chrome
            # orphaned by a killed run never lets go, and waiting on it costs the
            # caller its whole timeout. Check on the way in and once a minute
            # after, not every poll (each check shells out to ps).
            now = time.monotonic()
            if not yield_fast and now - last_orphan_check >= _ORPHAN_RECHECK_S:
                last_orphan_check = now
                if _clear_orphan_holder(profile_dir, verbose=verbose, label=label):
                    continue          # retry the flock immediately
            if time.monotonic() - start >= wait_s:
                try:
                    os.close(fd)
                except Exception:  # noqa: BLE001
                    pass
                if not yield_fast:
                    print(f"[{label}] {path.name} still held after {int(wait_s)}s "
                          "— launching anyway (wait+retry will guard)", flush=True)
                return None
            if not announced and not yield_fast:
                # NAME the holder: without it this line reads as "Tableau is
                # slow" and sends you to the wrong place (2026-08-19).
                who = _lock_holder(path)
                print(f"[{label}] another run holds {path.name}"
                      + (f" ({who})" if who else "")
                      + " — waiting up to "
                      f"{int(wait_s // 60)}m for it to finish before launching "
                      "(avoids a profile collision)", flush=True)
                announced = True
            time.sleep(_PROFILE_LOCK_POLL_S)


def _release_profile_lock(lock_fd, verbose=False):
    """Release + close a profile lock fd. Idempotent-safe and never raises."""
    if lock_fd is None:
        return
    try:
        if _fcntl is not None:
            _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
    except Exception:          # noqa: BLE001
        pass
    try:
        os.close(lock_fd)
    except Exception:          # noqa: BLE001
        pass


def _hold_profile_lock_until_close(ctx, lock_fd, verbose):
    """Release the profile lock when the context is closed, so the lock spans the
    whole session — not just the launch (the profile stays IN USE until close, so
    releasing at launch time would let a sibling collide). If close can't be
    hooked, release now: degrades to serializing only the launch, which is still
    no worse than before."""
    if lock_fd is None:
        return ctx
    try:
        _orig_close = ctx.close

        def _close_and_release(*a, **k):
            try:
                return _orig_close(*a, **k)
            finally:
                _release_profile_lock(lock_fd, verbose)

        ctx.close = _close_and_release
    except Exception:          # noqa: BLE001 — unusual object; don't leak the lock
        _release_profile_lock(lock_fd, verbose)
    return ctx


# PIN CHROME, DON'T RIDE WHATEVER GOOGLE SHIPPED LAST NIGHT (Megan 2026-09-01).
#
# Chrome auto-updated to 152.0.7977.65 at 01:45 and started crashing:
# EXC_BREAKPOINT in ChromeMain on macOS 26.6.2, 26 crashes that day against zero
# on every prior day. One crash took harvest_prime from 17/17 to 1/17; the same
# error killed the captainship reports, fiber_activations, the B2B tracker boards
# and org_sales_board's delta boxes. It is the single root cause of that morning.
#
# Rolling the app back is not available to us: Google publishes no old stable
# installer, the framework symlink alone does not downgrade (the launcher reads
# CFBundleShortVersionString from Info.plist), and two of the three runners take
# no SSH. Chrome for Testing is the supported answer — Google's own versioned
# builds, published for exactly this, installed BESIDE the team's Chrome so
# nobody's browser is touched.
#
# Install (per machine, ~179 MB):
#   mkdir -p ~/chrome-for-testing && cd ~/chrome-for-testing
#   curl -sSLO https://storage.googleapis.com/chrome-for-testing-public/\
#              151.0.7922.138/mac-arm64/chrome-mac-arm64.zip
#   unzip -q chrome-mac-arm64.zip
#
# CONSERVATIVE: with no pinned build installed this returns channel="chrome" and
# the launch is byte-identical to before, so a machine that has not been set up
# keeps working exactly as it did. CHROME_BINARY overrides for a one-off test.
_CFT_DIRS = ("chrome-mac-arm64", "chrome-mac-x64")


def _pinned_chrome() -> Optional[str]:
    """Path to a pinned Chrome build, or None to use the system channel."""
    env = (os.environ.get("CHROME_BINARY") or "").strip()
    if env and Path(env).exists():
        return env
    root = Path.home() / "chrome-for-testing"
    for d in _CFT_DIRS:
        exe = (root / d / "Google Chrome for Testing.app" / "Contents"
               / "MacOS" / "Google Chrome for Testing")
        if exe.exists():
            return str(exe)
    return None


def _chrome_launch_kwargs(base: dict, verbose: bool = False) -> dict:
    """base + either a pinned executable_path or the system chrome channel.

    executable_path and channel are mutually exclusive in Playwright, so this
    picks exactly one."""
    kw = dict(base)
    exe = _pinned_chrome()
    if exe:
        kw["executable_path"] = exe
    else:
        kw["channel"] = "chrome"
    return kw


def _launch_persistent(p, user_data_dir, *, headless: bool, label: str,
                       verbose: bool = True, window_size: tuple = (1680, 1280),
                       device_scale: float | None = None,
                       extra_args: Optional[list] = None,
                       busy_retries: int | None = None,
                       enable_extensions: bool = False):
    """launch_persistent_context with the existing system-chrome → bundled-
    chromium fallback UNCHANGED, wrapped in a wait+retry for the "profile
    already in use" collision.

    INERT on a normal launch: a healthy launch returns on the first try with
    byte-identical behavior to before. The retry only triggers on the exact
    profile-in-use failure that otherwise crashes the run — so it cannot
    affect a working patchright run.

    window_size (default 1680x1280, unchanged for every existing caller): a
    bigger window makes Tableau's Download→Image export a higher-resolution image
    (the tableau_screenshots module passes a large size for crisper posts)."""
    # Force a large window so multi-sheet Tableau dashboards render fully
    # in-view (the Program Summary DOWNLINE VIEW's downline worksheet sits
    # below the fold at the old ~784x449 default, which made its header
    # unclickable for the activate_xy download path). Fractional activate_xy
    # coords (e.g. FIBER_OVERVIEW_XY) are resolution-independent, so the other
    # scrape sources are unaffected. no_viewport stays True (real window).
    _args = [f"--window-size={window_size[0]},{window_size[1]}",
             "--window-position=0,0"]
    # Force 2x (or N x) device pixels so Tableau's Download→Image comes back at
    # higher resolution (the screenshots module passes device_scale=2 for crisper
    # posts). Default None = no flag = byte-identical launch for every other caller.
    if device_scale:
        _args += [f"--force-device-scale-factor={device_scale}",
                  "--high-dpi-support=1"]
    # Opt-in extra Chrome flags (e.g. --load-extension for resume_pushing's
    # extractor plugin). Default None = byte-identical launch for every other
    # caller.
    if extra_args:
        _args += list(extra_args)
    base = dict(user_data_dir=str(user_data_dir), headless=headless,
                no_viewport=True, args=_args)
    # Chrome EXTENSIONS: patchright's DEFAULT chromium args include
    # "--disable-extensions", which switches off any extension installed in the
    # persistent profile. ApplicantStream's resume extractor ("the robot" in
    # Carlos's walkthrough) IS a Chrome extension — installed into the profile it
    # still never appears, because this default flag kills it. Dropping the flag
    # is what makes the robot show up for resume_pushing. OPT-IN: default False
    # keeps every other caller's launch byte-identical.
    if enable_extensions:
        base["ignore_default_args"] = ["--disable-extensions"]
    # Serialize same-profile launches across processes so independently-scheduled
    # reports (Lucy 2's LaunchAgents) don't collide on the shared Chrome profile
    # the way three 7:00 reports did on 2026-07-20. Held until ctx.close(); None
    # when locking is unavailable (Windows) or declined (yield-fast) — then the
    # wait+retry below still guards. See _acquire_profile_lock.
    lock_fd = _acquire_profile_lock(user_data_dir, busy_retries=busy_retries,
                                    verbose=verbose, label=label)
    try:
        prefer_chrome = True
        last: Optional[Exception] = None
        # Low-priority callers (resume_pushing) pass busy_retries=1 to fail fast on
        # a profile-in-use collision (yield) instead of waiting for the other run.
        retries = busy_retries if busy_retries is not None else _LAUNCH_RETRIES
        for attempt in range(retries):
            try:
                if prefer_chrome:
                    try:
                        return _hold_profile_lock_until_close(
                            p.chromium.launch_persistent_context(
                                **_chrome_launch_kwargs(base, verbose)),
                            lock_fd, verbose)
                    except Exception as e:
                        if _is_profile_in_use(e):
                            raise  # bundled won't help (same profile); wait+retry
                        if verbose:
                            print(f"[{label}] system Chrome unavailable ({e!r}) — "
                                  "falling back to bundled Chromium", flush=True)
                        prefer_chrome = False
                return _hold_profile_lock_until_close(
                    p.chromium.launch_persistent_context(**base), lock_fd, verbose)
            except Exception as e:
                last = e
                if _is_profile_in_use(e) and attempt < retries - 1:
                    if verbose:
                        print(f"[{label}] browser profile is in use by another run "
                              f"— waiting {_LAUNCH_WAIT_S:.0f}s then retrying "
                              f"({attempt + 1}/{retries})", flush=True)
                    time.sleep(_LAUNCH_WAIT_S)
                    continue
                raise
        assert last is not None
        raise last
    except BaseException:
        # Any failure escaping the launch: drop the lock so we don't wedge every
        # sibling behind a run that never opened a context. (A success returns
        # through the try above with the lock attached to ctx, not released here.)
        _release_profile_lock(lock_fd, verbose)
        raise


@contextmanager
def tableau_session(headless: bool = False, verbose: bool = True,
                    allow_form_login: bool = True,
                    window_size: tuple = (1680, 1280),
                    device_scale: float | None = None,
                    profile_dir=None) -> Iterator[Page]:
    """Yield a Page logged into Tableau via ownerville SSO.

    Uses Order Log's persistent profile + the exported ownerville
    storage_state so the login survives across runs without driving the
    Turnstile form. When that session is stale/missing, self-heal by
    driving the OV login form unattended — verified 2026-07-01 that
    ownerville's Cloudflare now auto-passes the automation (mirrors the
    AppStream self-heal from 6/30). allow_form_login defaults True (the
    self-heal); pass False for a reuse-only run that fails fast.

    window_size (default 1680x1280, unchanged for existing callers): pass a
    larger size for a higher-resolution Download→Image (tableau_screenshots).

    device_scale (default None = unchanged for every existing caller): render
    at N device pixels per CSS pixel, so a SCREENSHOT of an ownerville page
    comes back at N× the detail. The same knob tableau_screenshots already
    passes for crisper Tableau posts.

    This is NOT the same thing as CSS zoom, and the difference is the whole
    point: zoom scales the LAYOUT — columns narrow, names wrap, the page grows
    taller — which is exactly how gap_alerts turned Raf's roster into 29
    near-empty pages on 2026-08-27. device_scale changes only how many pixels
    the same layout is painted with, so text gets sharper and nothing reflows.

    window_size (default 1680x1280, unchanged for every existing caller): the
    window is in DEVICE pixels, so it must be scaled ALONGSIDE device_scale or
    the layout silently narrows — window 1680 at device_scale 3 is a 560px CSS
    viewport, i.e. a phone-width page. gap_alerts hit exactly that: its rep-list
    column measured 331 CSS px and the "sharper" capture came back barely wider
    than before. Pass (1680*N, 1280*N) with device_scale=N to keep the desktop
    layout and simply paint it with N times the pixels.

    profile_dir (default None = the shared PROFILE_DIR): give a job its OWN
    profile so it never queues behind the morning batch. Different profiles
    don't block each other — only same-profile runs do. Added for the Owner
    Showdown 8am preview (Megan 2026-08-03), which sits inside the batch window
    and was dying on "profile is already in use by another instance of
    Chromium". Login still comes from the shared ownerville storage_state, so a
    fresh profile authenticates the same way."""
    prof = Path(profile_dir) if profile_dir else _job_profile_dir()
    prof.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, prof, headless=headless,
                                 label="tableau_patchright", verbose=verbose,
                                 window_size=window_size, device_scale=device_scale)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _ensure_tableau_authenticated(page, verbose=verbose,
                                          allow_form_login=allow_form_login)
            # Every entry into this context manager runs _sso_to_tableau, i.e. it
            # is ONE Tableau login. That is the number eStream is counting, so
            # the ledger records it separately from data pulls (Megan 2026-08-17).
            _ledger("login", "tableau_session", sheet=str(prof.name))
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
    # No profile_dir here: this helper does not take one, and passing an
    # undefined name would NameError. The default in the message is right for
    # this path, which runs on the shared profile.
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
    # CHECK BOTH DOMAINS, v2 FIRST (2026-09-01, Megan: "the V2 has a secondary
    # pass encryption on it").
    #
    # This only ever looked at v2.ownerville.com — the page behind the extra
    # password check — so a session established on ownerville.com could be
    # perfectly live and still read as dead. That is not theoretical: on the
    # evening of 9/1 Megan signed in at the holder's window three times and the
    # holder rejected every one, sitting at "waiting for ownerville login" while
    # a good session existed. One accepted seed at 19:05 was declared STALE six
    # minutes later by this same check.
    #
    # The signal is unchanged — a real rqst SSO token, in the URL or an in-page
    # link. Only the set of pages we look on widens, so this can accept sessions
    # it used to reject and can never accept one with no token at all.
    for url in (OWNERVILLE_V2_URL, LOGIN_URL):
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(4_000)
        except Exception:  # noqa: BLE001 — try the other domain
            continue
        if re.search(r"rqst=([A-Za-z0-9_]+)", page.url or ""):
            if verbose:
                print(f"-> ownerville session valid (rqst in URL at {url})",
                      flush=True)
            return True
        try:
            href = page.evaluate(
                "() => { const a=[...document.querySelectorAll('a')]"
                ".find(x=>/rqst=/.test(x.getAttribute('href')||'')); "
                "return a?a.getAttribute('href'):''; }")
            if re.search(r"rqst=([A-Za-z0-9_]+)", href or ""):
                if verbose:
                    print(f"-> ownerville session valid (rqst link at {url})",
                          flush=True)
                return True
        except Exception:  # noqa: BLE001 — try the other domain
            continue
    return False


def _ownerville_seed_hint() -> str:
    """What to actually DO about a dead ownerville session on THIS machine.

    The old error named output/_scratch_ownerville_export_state.py — a scratch
    file that no longer exists, so anyone who hit this was sent to a missing
    path (found 2026-08-24). The real refresh path is the session holder: a
    human clears Cloudflare in its window ONCE, then it re-exports the live
    cookies every few minutes.

    The key thing the old message never said: this file is gitignored and
    MACHINE-LOCAL. A holder keeping ownerville warm on the mini does nothing
    for a laptop, so a machine that never runs one just ages out — that is
    expected, not a fault to repair. Hence the two branches below.
    """
    try:
        days = (_dt.datetime.now() - _dt.datetime.fromtimestamp(
            OWNERVILLE_STORAGE_STATE.stat().st_mtime)).days
        when = f"was last exported {days} day(s) ago on this machine"
    except OSError:
        when = "has never been exported on this machine"
    return (
        f"{OWNERVILLE_STORAGE_STATE.name} {when}. On a machine that RUNS the "
        "session holder (mini / Lucy boxes): log back in inside its window, or "
        "restart it — `python -m automations.shared.session_holder` locally, "
        "`lucy restart_holder` remotely. On a machine with NO holder (e.g. a "
        "laptop) this file only ever ages, and reseeding it by hand is not the "
        "fix: run browser reports through `lucy` on the mini instead. Note "
        "`lucy reseed_appstream` is a DIFFERENT login (AppStream) and does not "
        "touch this file.")


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
                                 allow_form_login: bool = False,
                                 profile_dir=None) -> None:
    """Guarantee a LIVE ownerville session.

    Auth path: reuse a saved session where there is one, and LOG IN when there
    is not. The Cloudflare 'verify you are human' box on ownerville's password
    step clears ITSELF — type the username, NEXT, let the check run, fill the
    password, wait ~30s, submit (Megan 2026-09-01, and again 2026-09-02: "the
    delay causes the human box to auto check"). Nobody has to be at the screen.

    THE OLD DOCSTRING SAID THE OPPOSITE and it was measured wrong, not merely
    out of date: "the form hits a Cloudflare check that can't be cleared
    unattended" was a conclusion drawn from a 3-SECOND pre-submit pause. The
    submit landed while the check was still running, the login failed, and that
    read as "impossible" instead of "too fast". The whole fleet was built around
    that sentence — the form disabled by default, the holder opening a window
    and waiting for a person — and it is the same mistake that made AppStream
    look human-gated for twelve days.

    Steps:
      1. Reuse the exported storage_state (inject cookies → rqst check).
      2. Failing that, try whatever cookie the persistent profile already holds.
      3. Failing that, MINT A NEW SESSION by driving the login form unattended
         (refresh_ownerville, once per process so a bad password costs one
         attempt and not a loop against the account).
      4. Only then fail — with the remedy, not with a claim that a human is
         required.
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

    # (2b) SELF-HEAL: mint a new session rather than fail.
    #
    # This step did not exist because the form login was believed impossible
    # unattended ("the Cloudflare 'verify you are human' check can't be cleared
    # headless"). It can: the box clears ITSELF if you leave it alone before
    # submitting. Megan, 2026-09-01: "you can clear it without a human..you
    # just wait 30 sec before hitting submit on the PW". At the old 3s pause
    # the submit landed mid-check and the login failed, which is what made the
    # whole fleet believe a person was required.
    #
    # The cost of not having this was an entire evening. The ownerville token
    # died twice; each time every board stopped, the log filled with "session
    # expired or missing", and it stayed dead until a human re-minted it by
    # hand. A fresh mint is good for ~60 hours, so this should fire rarely —
    # but when it does, nobody should have to be awake for it.
    #
    # ONCE PER PROCESS. A wrong password must produce one failed login and a
    # clear error, never a retry loop against the account.
    global _OV_SELFHEAL_TRIED
    if not _OV_SELFHEAL_TRIED:
        _OV_SELFHEAL_TRIED = True
        if verbose:
            print("-> ownerville session dead — minting a new one", flush=True)
        try:
            from automations.shared.appstream_autorenew import refresh_ownerville
            if refresh_ownerville(verbose=verbose) and \
                    _reuse_ownerville_storage_state(page.context, page, verbose):
                if verbose:
                    print("-> ownerville session re-minted and restored",
                          flush=True)
                return
        except Exception as e:  # noqa: BLE001 — fall through to the real error
            if verbose:
                print("-> re-mint failed (%s: %s)"
                      % (type(e).__name__, str(e).splitlines()[0][:120]),
                      flush=True)

    # (3) Everything above failed. Fail loud + clear, pointing at the real
    # remedy — and NOT at a human. The old text here said the login form "is
    # disabled because its Cloudflare check can't be cleared unattended", which
    # is false (step 2b just tried it) and sends whoever reads it looking for
    # somebody to go clear a checkbox instead of at the actual failure: a wrong
    # credential, a poisoned profile, or ownerville itself being down.
    if not allow_form_login:
        raise RuntimeError(
            f"ownerville session expired or missing, and the unattended login "
            f"at {LOGIN_URL} did not reach a live session either — "
            f"{_ownerville_seed_hint()} "
            "(the Cloudflare check clears itself given ~30s before submit, so "
            "reaching here means something else failed: check the credential "
            "first, then the profile.) "
            # NAME THE PROFILE ACTUALLY IN USE. This printed the module-level
            # default whatever profile the caller passed, so a gap_alerts
            # failure pointed at `.browser_profile` while the poisoned profile
            # was `.browser_profile_gap_alerts` — an hour of looking at the
            # wrong directory on 2026-09-01.
            f"Profile: {profile_dir or PROFILE_DIR}")

    # (4) Opt-in form-drive on THIS page, for a caller that wants the login
    # driven here rather than in refresh_ownerville's throwaway profile.
    if verbose:
        print("-> [allow_form_login] driving ownerville login form "
              "(the Cloudflare check clears itself — see _drive_login_form)",
              flush=True)
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


# --- Shared session (login reuse) --------------------------------------------
# Megan 2026-08-17: eStream flagged how many times we sign in to Tableau. Every
# entry into tableau_session() is one ownerville->Tableau SSO login, and
# download_crosstab_patchright opens its OWN session per call unless the caller
# passes page=. So a report doing 5 pulls signs in 5 times.
#
# With TABLEAU_SHARED_SESSION=1 the process keeps ONE authenticated context alive
# and gives each pull a FRESH PAGE inside it. That collapses N logins to 1
# without sharing viz state between pulls.
#
# Fresh page (not a shared page) is deliberate. fiber_activations documented a
# real Tableau bug (2026-05-27): reusing one page across pulls of the
# CaptainsBonus view makes the Weekending URL filter silently stop applying on
# the 3rd+ call — it returned last-completed-week 3,072 instead of current-week
# 221. WRONG NUMBERS, no error. A new page per pull rebuilds the viz from
# scratch, which is much closer to a full session restart than the about:blank
# that was tried and failed. It is NOT proven equivalent — that is why this is
# DEFAULT OFF and flipped per report only after a same-run diff proves the
# output is identical. See automations/harvest/proof_session.py.
#
# OFF (env unset) => byte-identical to today for every report.
_SHARED_CTX = {"pw": None, "ctx": None, "lock_fd": None}


def shared_session_enabled() -> bool:
    return os.environ.get("TABLEAU_SHARED_SESSION", "").strip() in ("1", "on", "true")


def _shared_context(verbose: bool = False):
    """The one authenticated context for this process. Built on first use."""
    if _SHARED_CTX["ctx"] is not None:
        return _SHARED_CTX["ctx"]
    prof = PROFILE_DIR
    prof.mkdir(exist_ok=True, parents=True)
    p = sync_playwright().start()
    ctx = _launch_persistent(p, prof, headless=False,
                             label="tableau_patchright(shared)", verbose=verbose)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    _ensure_tableau_authenticated(page, verbose=verbose, allow_form_login=True)
    _ledger("login", "tableau_session(shared)", sheet=str(prof.name))
    _SHARED_CTX["pw"], _SHARED_CTX["ctx"] = p, ctx
    atexit.register(close_shared_session)
    return ctx


def close_shared_session() -> None:
    """Close the shared context. Safe to call twice; runs at process exit."""
    ctx, pw = _SHARED_CTX.get("ctx"), _SHARED_CTX.get("pw")
    _SHARED_CTX["ctx"] = _SHARED_CTX["pw"] = None
    try:
        if ctx is not None:
            ctx.close()
    except Exception:
        pass
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass


@contextmanager
def shared_page(verbose: bool = False):
    """A FRESH page inside the process's one authenticated context.

    Falls back to a normal one-off tableau_session() if the shared context can't
    be built, so enabling the flag can never leave a report with no session."""
    try:
        ctx = _shared_context(verbose=verbose)
    except Exception as e:  # noqa: BLE001 — never let login reuse break a report
        print(f"  ⚠ shared Tableau session unavailable ({type(e).__name__}: "
              f"{str(e).splitlines()[0][:80]}) — falling back to a per-pull login",
              flush=True)
        with tableau_session(verbose=verbose) as pg:
            yield pg
        return
    pg = ctx.new_page()
    try:
        yield pg
    finally:
        try:
            pg.close()
        except Exception:
            pass


# --- Access ledger -----------------------------------------------------------
# Passive counter for the Tableau access-volume work (Megan 2026-08-17). Never
# changes behaviour; import is lazy + swallowed so this file keeps working even
# if the ledger module is missing on an out-of-date checkout.
def _freshness(path, view_url, sheet="", verbose=False):
    """Judge a downloaded export's data date and alert loudly if it's stale.

    Hung off the SHARED download (2026-08-17) so every Tableau-pulling report
    inherits it — ~120 modules, ~156 call sites, none of which had to change.
    A report can still call tableau_freshness.check_export itself with a stricter
    `needs`/`max_days_behind`; this is the floor, not the ceiling.

    Opt out for one process with ALPHALETE_SKIP_FRESHNESS=1 — for probes and
    backfills that deliberately pull an old window and would otherwise report
    themselves as stale. Never raises: a report whose data is fine must not fail
    because the freshness check tripped."""
    try:
        import os
        if (os.environ.get("ALPHALETE_SKIP_FRESHNESS") or "").strip() in ("1", "true", "yes"):
            return
        from automations.shared import tableau_freshness
        tableau_freshness.check_export(path, view_url=view_url, sheet=sheet,
                                       verbose=verbose)
    except Exception:  # noqa: BLE001
        pass


def _ledger(kind, view_url, sheet="", cache="miss", extra="", t0=None, ok=True):
    try:
        from automations.shared import tableau_ledger
        tableau_ledger.record(
            view_url, sheet=sheet, kind=kind, cache=cache, extra=extra, ok=ok,
            elapsed_ms=int((time.time() - t0) * 1000) if t0 else None)
    except Exception:
        pass


# --- Opt-in cross-run crosstab cache -----------------------------------------
# The per-office metrics feeds each pull the SAME org-wide crosstabs (Order Log,
# Canceled Orders, Disconnects, Scheduled-6+) and filter to their owner — so with
# N offices the same view is downloaded N times. Set METRICS_XTAB_CACHE=<dir> and
# download_crosstab_patchright caches each (view_url, sheet) to a dated folder;
# the next run that asks for the same view + sheet the same day reads the cache
# and skips the browser entirely. OFF by default (env unset) → identical to
# before for every other report. Self-keying: it dedupes only genuinely-identical
# pulls (same URL + sheet + day) and is a harmless no-op for owner-specific views.
# Fail-safe throughout: any cache error falls through to a normal live download.
_XTAB_CACHE_TTL_S = 12 * 3600     # a same-day snapshot; ignore anything older


def _xtab_cache_dir() -> Optional[Path]:
    d = os.environ.get("METRICS_XTAB_CACHE")
    return Path(d) if d else None


def _xtab_cache_key(view_url: str, sheet: str) -> str:
    # :iid is a UI tab index, not identity — drop it so the same view matches.
    norm = re.sub(r"[?&]:iid=\d+", "", (view_url or "").strip())
    return hashlib.sha256(f"{norm}\0{sheet}".encode("utf-8")).hexdigest()[:32]


def _xtab_cache_path(root: Path, view_url: str, sheet: str) -> Path:
    return root / _dt.date.today().isoformat() / f"{_xtab_cache_key(view_url, sheet)}.csv"


def _xtab_cache_lookup(view_url: str, sheet: str, verbose: bool) -> Optional[Path]:
    root = _xtab_cache_dir()
    if root is None:
        return None
    try:
        p = _xtab_cache_path(root, view_url, sheet)
        if (p.exists() and p.stat().st_size > 0
                and (time.time() - p.stat().st_mtime) < _XTAB_CACHE_TTL_S):
            # ALWAYS print the hit, even when the caller pulls with verbose=False
            # (canceled_orders/disconnects do) — a silent dedup is impossible to
            # verify or debug. This only ever fires when the cache is enabled AND
            # hits, so it adds no noise to any other report.
            print(f"  ↺ crosstab cache HIT ({sheet}) — served from "
                  f"{p.parent.name}/{p.name}, skipped the browser download",
                  flush=True)
            return p
    except Exception:
        return None
    return None


def _xtab_cache_store(view_url: str, sheet: str, produced: Path) -> None:
    root = _xtab_cache_dir()
    if root is None:
        return
    try:
        produced = Path(produced)
        if not (produced.exists() and produced.stat().st_size > 0):
            return
        dest = _xtab_cache_path(root, view_url, sheet)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".csv.tmp")
        shutil.copyfile(produced, tmp)
        os.replace(tmp, dest)          # atomic publish — no half-written cache file
        _xtab_cache_prune(root)
    except Exception:
        pass                            # caching is best-effort; the pull succeeded


def _xtab_cache_prune(root: Path, keep_days: int = 3) -> None:
    """Drop dated cache folders older than keep_days. Only removes YYYY-MM-DD dirs
    directly under our own cache root, so it can't touch anything else."""
    try:
        cutoff = _dt.date.today() - _dt.timedelta(days=keep_days)
        for child in root.iterdir():
            if not child.is_dir():
                continue
            try:
                d = _dt.date.fromisoformat(child.name)
            except ValueError:
                continue                # not a dated dir — leave it alone
            if d < cutoff:
                shutil.rmtree(child, ignore_errors=True)
    except Exception:
        pass


# A DEAD BROWSER IS NOT A PAGE FLAKE (2026-09-01).
#
# Every retry ladder in this repo was built for a transient Tableau
# load/render flake, which a fresh navigation clears. It cannot clear a
# browser that has EXITED: re-issuing page.goto into a closed context can only
# reproduce the same TargetClosedError, so all three attempts burn in
# milliseconds and the caller sees a hard failure.
#
# That is exactly what Chrome 152.0.7977.65 did on 2026-09-01 (auto-updated
# 01:45, 22 crashes that day, zero on any prior day — EXC_BREAKPOINT in
# ChromeMain on macOS 26.6.2). harvest_prime lost 17/17 pulls to ONE crash,
# because harvester.py opens one session per isolation group and every need in
# the group then retried into the corpse. The tracker boards lost the same way.
#
# The tell that this is recoverable: a FRESH PROCESS succeeded on the first
# try (the --only re-capture of four tracker boards, 06:34 the same morning).
# The crash is intermittent; only our reuse of the dead context was
# deterministic. So the ladders now rebuild the session instead of retrying
# into a corpse, and a crash costs one relaunch rather than a whole report.
#
# Deliberately NOT a Chrome pin: the runners' Chrome auto-updates, one of them
# (Lucy 3) takes no SSH, and the same crash-mid-run can arrive with any future
# version. This heals the class, not the version.
_DEAD_CONTEXT_MARKERS = (
    "target page, context or browser has been closed",
    "target closed",
    "browser has been closed",
    "browser closed",
    "connection closed",
)


# WHERE A REBUILD RELAUNCHES (2026-09-01, same morning, second lesson).
#
# The first cut of the rebuild reopened tableau_session() on the SHARED profile
# — the one the crashed Chrome was using. That cannot work: a crashed Chrome
# leaves its Singleton* lock behind, so the relaunch hits "profile is already in
# use" and the recovery fails at the moment it is needed. Observed live on Lucy 1
# minutes after deploy, in org_sales_board:
#
#   ↻ browser died — rebuilding the session for the remaining attempt(s)
#   (rebuild failed: Error) — reporting the original failure
#
# tableau_session already documents the way out: "give a job its OWN profile so
# it never queues behind the morning batch. Different profiles don't block each
# other — only same-profile runs do." The login still comes from the shared
# ownerville storage_state, so a fresh profile authenticates identically.
REBUILD_PROFILE_DIR = PROFILE_DIR.parent / ".browser_profile_rebuild"


# ONE PROFILE PER JOB, NOT ONE PROFILE PER FLEET (Megan 2026-09-01: "do the
# profile fix").
#
# Every browser report defaulted to the SAME .browser_profile, and Chrome's
# singleton means concurrent runs evict each other — the survivor keeps the
# profile and the loser's context dies mid-run as TargetClosedError. Lucy 1
# routinely has four patchright drivers up at once (orchestrator pass +
# standalone LaunchAgents + reruns), so this was a standing collision, not an
# edge case. Measured 08:56 on 2026-09-01: 4 drivers, 8 Chromes on
# .browser_profile, and org_sales_board losing its delta boxes to
# "Download.save_as: Target page, context or browser has been closed" in an hour
# with ZERO Chrome crash reports — the crash wave had already passed; this was
# pure contention.
#
# The remedy is already proven in this file, twice, as a per-job escape hatch:
# Owner Showdown's 8am preview (2026-08-03, dying on "profile is already in use")
# and other_office_knocks (2026-08-18, "Opening in existing browser session").
# Both fixed by handing that job its own profile. This makes the escape hatch
# the DEFAULT instead of something each job has to remember.
#
# Keyed on HUB_REPORT_ID, which both runners already set (run.py sets it for the
# orchestrator pass, mini_control for every `lucy rerun`) — so the name is stable
# per report and the profile stays warm across runs instead of paying a cold
# login every time. Login still comes from the shared ownerville storage_state,
# so a fresh profile authenticates identically.
#
# CONSERVATIVE: with no HUB_REPORT_ID (a hand-run script, a test, the REPL) the
# behaviour is byte-identical to before — the shared profile. Only labelled jobs
# get isolated, which is exactly the set that collides.
def _job_profile_dir() -> Path:
    """The profile this JOB should use: its own when the runner labelled it."""
    job = (os.environ.get("HUB_REPORT_ID") or "").strip()
    if not job:
        return PROFILE_DIR
    slug = re.sub(r"[^a-z0-9_-]+", "-", job.lower()).strip("-")[:60]
    if not slug:
        return PROFILE_DIR
    return PROFILE_DIR.parent / (".browser_profile__" + slug)


def is_dead_context(exc) -> bool:
    """True when `exc` means the browser/context DIED, not that the page misbehaved.

    Matched on the exception's class name AND its text: patchright raises
    TargetClosedError for a crash, but the same condition surfaces through
    wrapped/re-raised errors whose type is generic while the message still
    names the closed target."""
    if exc is None:
        return False
    if type(exc).__name__ in ("TargetClosedError", "BrowserClosedError"):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _DEAD_CONTEXT_MARKERS)


def download_crosstab_patchright(
    view_url: str,
    crosstab_sheet: str,
    out_path: Path,
    verbose: bool = True,
    page: Optional[Page] = None,
    pre_export=None,
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
    # Opt-in cache — serve a same-day pull of this exact (view, sheet) without a
    # browser. Skipped when pre_export is set: that callback customizes the export
    # (e.g. drives date fields), so the URL+sheet don't fully determine the output.
    cacheable = pre_export is None
    if cacheable:
        hit = _xtab_cache_lookup(view_url, crosstab_sheet, verbose)
        if hit is not None:
            try:
                out_path = Path(out_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(hit, out_path)
                _ledger("crosstab", view_url, crosstab_sheet, cache="hit",
                        extra="" if cacheable else "pre_export")
                # Judge cache HITS too. The per-office metrics feeds pull one
                # org-wide view once and serve it to ~20 offices from cache, so
                # checking only the miss would mean a stale source is heard for
                # office #1 and silent for the other nineteen — and on a day the
                # first office is skipped, silent for every one of them.
                _freshness(out_path, view_url, crosstab_sheet, verbose)
                return out_path
            except Exception:
                pass            # copy failed → fall through to a live download

    MAX_ATTEMPTS = 3
    BACKOFF_S = 3
    last_err = [None]

    def _try(pg, attempt):
        """One attempt on `pg`. Returns the path, or None after recording the
        failure so the caller can decide whether to retry."""
        t0 = time.time()
        try:
            result = drive_crosstab_dialog(pg, view_url, crosstab_sheet,
                                           out_path, verbose=verbose,
                                           pre_export=pre_export)
        except Exception as e:  # noqa: BLE001 — retried below, re-raised at the end
            last_err[0] = e
            # A failed attempt still LOADED the view — Tableau counts it, so the
            # ledger has to as well, or retries hide from the access census.
            _ledger("crosstab", view_url, crosstab_sheet, cache="miss",
                    extra="" if cacheable else "pre_export", t0=t0, ok=False)
            if attempt < MAX_ATTEMPTS:
                if verbose:
                    print(f"  ⚠ crosstab pull failed ({str(e).splitlines()[0][:90]})"
                          f" — retry {attempt}/{MAX_ATTEMPTS - 1} after {BACKOFF_S}s…",
                          flush=True)
                time.sleep(BACKOFF_S)
            return None
        if cacheable:
            _xtab_cache_store(view_url, crosstab_sheet, result)
        _ledger("crosstab", view_url, crosstab_sheet, cache="miss",
                extra="" if cacheable else "pre_export", t0=t0)
        _freshness(result, view_url, crosstab_sheet, verbose)
        return result

    if page is not None:
        # Caller owns the browser: retry on their page, no login either way —
        # UNLESS the browser itself died. See is_dead_context: retrying into a
        # closed context reproduces the same error every time, which is how ONE
        # Chrome crash cost harvest_prime all 17 pulls on 2026-09-01. A rebuild
        # costs one login and is only reached on a crash, so the happy path and
        # the ordinary-flake path are both byte-identical to before.
        for attempt in range(1, MAX_ATTEMPTS + 1):
            r = _try(page, attempt)
            if r is not None:
                return r
            if is_dead_context(last_err[0]):
                # FAIL FAST — do not spend the rest of the ladder on a corpse.
                #
                # An in-process rebuild is IMPOSSIBLE here, and the first cut of
                # this tried anyway: tableau_session opens its own
                # sync_playwright(), and starting one INSIDE a running one raises
                # "It looks like you are using Playwright Sync API inside the
                # asyncio loop." Measured 2026-09-01: 5 rebuilds fired, 5 failed,
                # 0 recovered — while printing a generic "Error" that read like a
                # transient and hid the real reason for two hours.
                #
                # The recovery that DOES work is a fresh PROCESS, which the
                # orchestrator already provides as a whole-report retry and which
                # carried every recovery that day: harvest_prime 1/17 -> 17/17,
                # the four tracker boards, captainship churn, abp_6days. Failing
                # fast hands the run back to that sooner, instead of burning two
                # more attempts against a browser that is already gone.
                if verbose:
                    print("  ✗ the browser died — this run cannot recover in "
                          "process; failing fast so the report retries on a "
                          "fresh one", flush=True)
                break
        raise last_err[0]

    if shared_session_enabled():
        # ONE login for this process; a fresh page per attempt keeps the viz
        # state isolated the way a per-attempt session did.
        for attempt in range(1, MAX_ATTEMPTS + 1):
            with shared_page(verbose=verbose) as pg:
                r = _try(pg, attempt)
            if r is not None:
                return r
        raise last_err[0]

    # LEGACY PATH — LOGIN BUDGET (Megan 2026-08-18). This used to open a NEW
    # tableau_session per ATTEMPT, so one flaky view cost up to 3 logins. The
    # access ledger measured 17 failed/retried pulls in a day, each an extra
    # sign-in that bought nothing. Now the retry ladder rides ONE login with a
    # fresh PAGE per attempt — which is what actually clears the flake, since the
    # dominant failure is a transient load/render and drive_crosstab_dialog
    # re-navigates (about:blank -> goto) on every call anyway.
    #
    # The LAST attempt still gets a genuinely fresh login. That is the escape
    # hatch for the one failure a page reload cannot fix: a session that has
    # itself gone stale/unauthenticated, where only a re-auth helps.
    #
    # INERT ON THE HAPPY PATH: attempt 1 succeeding costs one login and one page,
    # exactly as before. Nothing changes unless a pull actually fails.
    try:
        with tableau_session(verbose=verbose) as pg0:
            for attempt in range(1, MAX_ATTEMPTS):        # attempts 1..MAX-1
                pg = pg0 if attempt == 1 else pg0.context.new_page()
                try:
                    r = _try(pg, attempt)
                finally:
                    if pg is not pg0:
                        try:
                            pg.close()
                        except Exception:                 # noqa: BLE001
                            pass
                if r is not None:
                    return r
    except Exception as e:  # noqa: BLE001 — a dead session falls through to re-auth
        if last_err[0] is None:
            last_err[0] = e
        if verbose:
            print(f"  ⚠ retry session unusable ({str(e).splitlines()[0][:80]}) "
                  f"— final attempt on a fresh login…", flush=True)

    with tableau_session(verbose=verbose) as pg:           # final: fresh login
        r = _try(pg, MAX_ATTEMPTS)
    if r is not None:
        return r
    raise last_err[0]


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
        t0 = time.time()
        try:
            fields, records = _scrape_one_view_data(
                pg, ctx, view_url, verbose=verbose,
                activate_xy=activate_xy, scrape_kwargs=scrape_kwargs)
        except Exception:
            _ledger("viewdata", view_url, t0=t0, ok=False)
            raise
        _ledger("viewdata", view_url, t0=t0)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["\t".join(fields)] + ["\t".join(r) for r in records]
        out_path.write_text("\n".join(lines), encoding="utf-8")
        if verbose:
            print(f"saved View Data: {out_path} ({len(records)} rows)", flush=True)
        # Same freshness gate as the crosstab path — the View Data fallback is a
        # different Tableau mechanism but the same data, and a report that falls
        # back to it (SARA, Money Lost) must not lose its staleness cover.
        _freshness(out_path, view_url, "view-data", verbose)
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
            # This context launches on PROFILE_DIR itself, so the default in
            # the error message is already the profile in use.
            _ensure_ownerville_logged_in(page, verbose=verbose,
                                         allow_form_login=allow_form_login)
            _sso_to_appstream(page, verbose=verbose)
            yield page
        finally:
            ctx.close()


@contextmanager
def ownerville_session(headless: bool = False,
                      verbose: bool = True,
                      allow_form_login: bool = False,
                      profile_dir=None,
                      device_scale: float | None = None,
                      window_size: tuple = (1680, 1280)) -> Iterator[Page]:
    """Yield a Page logged into ownerville.com via patchright — WITHOUT the
    Tableau SSO hop. For reports that scrape ownerville's own pages (e.g.
    focus_office_att rep breakdowns). Same login + shared profile +
    storage_state as tableau_session; the caller navigates to the ownerville
    URLs it needs. allow_form_login=True re-enables the legacy form-drive
    (interactive/debug ONLY).

    profile_dir (default None = the shared PROFILE_DIR): give a job its OWN
    profile so it never queues behind — or collide with — another run on the
    shared one. Exactly the escape hatch tableau_session already has (Megan
    2026-08-03, Owner Showdown preview); added here 2026-08-18 because
    other_office_knocks kept dying on "Opening in existing browser session"
    while another session held the shared profile. Login still comes from the
    shared ownerville storage_state, so a fresh profile authenticates the
    same way."""
    prof = Path(profile_dir) if profile_dir else _job_profile_dir()
    prof.mkdir(exist_ok=True, parents=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, prof, headless=headless,
                                 label="ownerville_session", verbose=verbose,
                                 device_scale=device_scale,
                                 window_size=window_size)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _ensure_ownerville_logged_in(page, verbose=verbose,
                                         allow_form_login=allow_form_login,
                                         profile_dir=profile_dir)
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


def _profile_extension_paths(profile) -> list:
    """Unpacked-extension dirs installed in a persistent Chrome profile
    (<profile>/Default/Extensions/<id>/<version>/). Playwright launches Chrome
    with extensions DISABLED by default, so an extension a human installed into
    the profile won't load unless we point --load-extension at it. Returns the
    newest version dir per extension id ([] if none)."""
    out = []
    for root in (Path(profile) / "Default" / "Extensions",
                 Path(profile) / "Extensions"):
        if not root.is_dir():
            continue
        for ext_id in sorted(root.iterdir()):
            if not ext_id.is_dir():
                continue
            versions = [v for v in ext_id.iterdir()
                        if v.is_dir() and (v / "manifest.json").exists()]
            if versions:
                versions.sort(key=lambda pp: pp.name)
                out.append(str(versions[-1]))
    return out


APPSTREAM_RESEED_CMD = ("    PYTHONPATH=. .venv/bin/python -m "
                        "automations.shared.tableau_patchright --appstream-login")


def _appstream_consumer_of() -> Optional[str]:
    """Always None. NO MACHINE CONSUMES ANOTHER'S AppStream SESSION.

    Megan 2026-09-02: "one machine CANNOT depend on another, we don't want 1
    taking them all down." Every Lucy signs in as its own account and mints its
    own token; there is no donor and no consumer.

    WHY THE FUNCTION SURVIVES AS A STUB rather than being deleted with its
    callers: what it used to return went into an ERROR MESSAGE, and that message
    told whoever read it "Do NOT run --appstream-login on this machine". Once
    each Lucy holds its own, that sentence is not merely obsolete — it talks a
    person out of the one command that fixes their machine. It already did:
    on 2026-09-02 Lucy 1 raised it and a human chased a phantom donor through
    five manual logins between 06:36 and 07:22.

    It also used to guess. `_this_machine()` answers a hostname, and any box not
    in APPSTREAM_HOLD_MACHINES — Megan's laptop, a renamed Lucy, a machine whose
    .machine-profile marker is missing — was declared a CONSUMER of whatever
    machine happened to be first in the tuple. A wrong guess there produces that
    same do-not-log-in instruction on a machine nobody is donating to.

    Returning None is the honest answer for every machine now, so the callers
    give the one remedy that works everywhere: log in here."""
    return None


def _appstream_reseed_error(reason: str,
                            detail: str = "") -> RuntimeError:
    """The ONE message every dead-session path must give.

    WHY (Megan 2026-08-24). Four 4am reports — daily_focus, applicant_sync_
    morning, recruiter_retention_daily/_weekly — plus alphalete-org-run's
    Recruiting pull all died the same morning, and what they told the channel
    was `Missing AppStream credential 'appstream_username'`. That reads like a
    setup mistake and sends whoever picks up the ticket looking for a keychain
    entry. It wasn't: the saved session had gone stale, and the credential was
    only wanted by the form-login fallback that stale sessions used to fall
    into. The actionable sentence — RE-SEED THE SESSION — never appeared.

    So every path that ends in "this run has no live AppStream session" raises
    THIS, with `reason` naming which way it got here.

    `reason` stays SHORT and goes on the first line, because that first line is
    what the alert quotes as "Likely cause" — the whole point is that the line
    the channel shows is about the session. Anything longer (a wrapped
    exception, a page dump) belongs in `detail`, which trails the message."""
    # NAME THE RIGHT FIX FOR THIS MACHINE. On a consumer the re-seed command is
    # not just useless, it is HARMFUL: a fresh login here invalidates the token
    # the whole fleet is holding (session_holder says the same thing in as many
    # words — "do NOT --appstream-login here"). On 2026-09-02 Lucy 1 raised this
    # error and a human chased that command through five manual logins between
    # 06:36 and 07:22 while the real answer was a push from Lucy 2.
    # ONE REMEDY, ON THIS MACHINE. There is no donor to defer to (see
    # _appstream_consumer_of) — every Lucy holds its own session, so the fix is
    # always here, and naming the account by its configured value rather than a
    # literal keeps this line from going stale the way "log in as rcaptain" did.
    try:
        _who = creds.appstream_username()
    except Exception:  # noqa: BLE001 — a diagnosis must not need a credential
        _who = "the configured AppStream account"
    msg = (
        f"AppStream session is not usable: {reason}\n"
        "(an unattended form login is tried first — username, NEXT, the "
        "Cloudflare wait, password, submit — so reaching this means that "
        "failed too, and the credential itself is the first thing to check)\n"
        f"Fix it HERE, on this machine — re-seed the session:\n"
        f"{APPSTREAM_RESEED_CMD}\n"
        f"(a browser opens; sign in as {_who}). Confirm with:\n"
        "    PYTHONPATH=. .venv/bin/python -m "
        "automations.shared.appstream_whoami\n"
        "The session holder then keeps it warm for scheduled runs.")
    if detail:
        msg += f"\n\nWhat it tripped over on the way down:\n{detail}"
    return RuntimeError(msg)


def _appstream_form_login_allowed(*, allow_form_login: bool,
                                  force_form_login: bool,
                                  username: Optional[str],
                                  password: Optional[str]) -> bool:
    """May THIS call drive the AppStream login form?

    Only when someone asked for it on purpose. Three ways to ask:
      • allow_form_login=True   — interactive/debug (appstream_whoami)
      • force_form_login=True   — re-seed / holder paths that skip reuse
      • explicit username+password — daily_focus --alt-appstream, whose whole
        point is signing in as a DIFFERENT account than the saved session

    A scheduled report passes none of them, and until 2026-09-02 that meant
    "reuse or die": the premise was that the 2026-08-20 release put a human
    check on the form, so an unattended fall-through was only "a slower and
    much more confusing way to fail". [[reference_appstream_turnstile]]

    THAT PREMISE WAS MEASURED WRONG (Megan, 2026-09-01). appstream_autorenew
    drives this same form as its last-resort recovery and it completes with
    nobody at the browser — verified on Lucy 1 from a COLD profile with no
    saved session, which is the 4am case exactly: username -> NEXT -> the
    Cloudflare wait -> password -> submit -> a live #searchMC. Her note there
    says it in as many words: "The premise was wrong, not the mechanism."

    So a scheduled run may try the form too. What it buys: on 2026-09-02
    recruiter_retention_daily and applicant_sync_morning both died at 04:00
    because the token had expired at 21:33 the night before and the renewal
    timer runs on ONE machine (deploy/com.alphalete.appstream-autorenew.plist
    is Megan's Mac, and it was asleep). With the form allowed, the first report
    of the batch signs itself back in, saves the session, and the ones behind
    it reuse it — instead of four reports waiting on a person at 4am.

    The fallback is unchanged: the form drive is bounded (it gives up when
    #searchMC never renders) and _appstream_reseed_error is what a failed
    attempt raises, so a genuinely dead login still pages exactly as before.

    KILL SWITCH: APPSTREAM_NO_FORM_LOGIN=1 puts a machine back to reuse-only,
    for the day the provider really does gate the form."""
    if allow_form_login or force_form_login or (username and password):
        return True
    return (os.environ.get("APPSTREAM_NO_FORM_LOGIN", "").strip().lower()
            not in ("1", "true", "yes", "on"))


@contextmanager
def appstream_direct_session(headless: bool = False,
                             verbose: bool = True,
                             profile_dir: Optional[Path] = None,
                             username: Optional[str] = None,
                             password: Optional[str] = None,
                             allow_form_login: bool = False,
                             force_form_login: bool = False,
                             load_extensions: bool = False,
                             yield_if_busy: bool = False,
                             enable_extensions: bool = False) -> Iterator[Page]:
    """Yield a Page on the AppStream recruiting console (#searchMC office
    switcher) for the rcaptain account, via patchright stealth. Unattended
    replacement for fetch_office._attach() (debug-Chrome CDP, broken on Chrome
    148).

    yield_if_busy=True: if the Chrome profile is already in use by another run,
    DON'T wait — raise AppStreamBusy immediately so a low-priority caller
    (resume_pushing) can step aside and let the other report have the session.

    enable_extensions=True: drop patchright's default "--disable-extensions" so a
    Chrome extension installed in this profile actually LOADS. Required by
    resume_pushing — ApplicantStream's resume extractor ("the robot") is an
    extension, and the default flag silently disables it. Seed the extension into
    the profile once with:  python -m automations.shared.tableau_patchright
    --appstream-extension

    Auth path (2026-08-24): reuse the saved session (APPSTREAM_STORAGE_STATE).
    That is the ONLY path an unattended run has. If the session is stale or
    missing, the run fails fast with re-seed instructions.

    That used to read differently. Between 6/30 and 8/20 AppStream's Cloudflare
    auto-passed the automation, so a stale session could self-heal by driving
    the rcaptain login form unattended, and allow_form_login defaulted True. The
    2026-08-20 release put an interactive human-check back on that form, which
    killed the self-heal — but the default stayed True, so scheduled runs kept
    falling into a path that cannot complete and reporting whatever it tripped
    over on the way (a missing credential, a Turnstile timeout) as the cause.
    The default is now False: no session, no run, one clear message.
    [[reference_appstream_turnstile]]

    allow_form_login=True re-enables the form drive for interactive/debug use
    (it will sit on the human-check in an unattended run).
    force_form_login=True skips reuse and re-logs-in unconditionally.
    Passing BOTH username and password also enables the form drive — that's
    daily_focus --alt-appstream, which signs in as a different account than the
    saved session on purpose.

    Override args (used by daily_focus --alt-appstream for ICDs visible only
    from a different AppStream account):
      - profile_dir: use a separate profile (so rcaptain's cookies aren't
                     overwritten by the alternate account's session).
      - username / password: skip creds.py lookup; pass these directly to
                             the login form (only relevant with
                             allow_form_login=True)."""
    profile = profile_dir or APPSTREAM_PROFILE_DIR
    profile.mkdir(exist_ok=True, parents=True)
    # Force-load any extension a human installed into this profile (resume_pushing
    # needs the ApplicantStream AI resume-extractor plugin). Playwright otherwise
    # launches with extensions disabled, so the installed plugin sits unused.
    ext_args = []
    if load_extensions:
        import shutil
        _ext_paths = _profile_extension_paths(profile)
        # patchright launches Chrome with flags (--use-mock-keychain etc.) that
        # invalidate the profile's own extension registrations, so Chrome STRIPS a
        # human-installed plugin on launch (6 -> 2 -> 0). Keep a copy OUTSIDE the
        # profile and load THAT: a command-line --load-extension is unpacked/dev
        # mode and isn't subject to that stripping, so it survives every launch.
        cache = Path(profile).parent / ".extractor_cache"
        if _ext_paths:                      # profile still has them → refresh cache
            shutil.rmtree(cache, ignore_errors=True)
            cache.mkdir(parents=True, exist_ok=True)
            cached = []
            for _i, _src in enumerate(_ext_paths):
                _dst = cache / f"ext{_i}"
                try:
                    shutil.copytree(_src, _dst)
                    cached.append(str(_dst))
                except Exception as _e:
                    if verbose:
                        print(f"-> cache copy failed for {_src}: {_e}", flush=True)
        else:                               # profile got wiped → reuse the cache
            cached = ([str(d) for d in sorted(cache.glob("ext*"))
                       if (d / "manifest.json").exists()]
                      if cache.is_dir() else [])
        if cached:
            _joined = ",".join(cached)
            # BOTH flags together (the documented Playwright combo) — required for
            # a --load-extension'd extension to actually stay ENABLED. We include
            # every cached extension in the allow-list, so nothing gets disabled.
            ext_args = [f"--disable-extensions-except={_joined}",
                        f"--load-extension={_joined}"]
            if verbose:
                print(f"-> loading {len(cached)} extension(s) from cache:",
                      flush=True)
                for _c in cached:
                    try:
                        _m = json.loads((Path(_c) / "manifest.json").read_text())
                        print(f"   - {_m.get('name', '?')}  (v{_m.get('version','?')})",
                              flush=True)
                    except Exception:
                        print(f"   - {_c} (no readable manifest)", flush=True)
        elif verbose:
            print("-> load_extensions=True but no extension in profile OR cache — "
                  "install the plugin first, then run once to cache it", flush=True)
    with sync_playwright() as p:
        try:
            ctx = _launch_persistent(p, profile, headless=headless,
                                     label="appstream_direct", verbose=verbose,
                                     extra_args=ext_args,
                                     busy_retries=1 if yield_if_busy else None,
                                     enable_extensions=enable_extensions)
        except Exception as e:
            if yield_if_busy and _is_profile_in_use(e):
                raise AppStreamBusy(str(e)) from e
            raise
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            # Primary (automated) path: restore the exported session. Never
            # touches the login form / Turnstile. force_form_login skips this to
            # exercise the rcaptain form login directly (test / holder re-seed).
            if not force_form_login and _reuse_appstream_storage_state(
                    ctx, page, verbose):
                # Verify the reused session actually landed on a LIVE console.
                # A stale token restores cookies + navigates fine but lands
                # logged-out with no #searchMC — and yielding that dead console
                # cascades into every owner failing (Megan 2026-07-03: 35 ICDs
                # missed exactly this way). If the switcher isn't there, DON'T
                # yield — fall through to the unattended form-login self-heal.
                if page.locator("#searchMC").count() > 0:
                    yield page
                    return
                if verbose:
                    print("-> reused AppStream session has no #searchMC (stale "
                          "token)", flush=True)

            # No live session. Drive the login form — including on a scheduled
            # run, which is the 2026-09-02 change: the form completes unattended
            # (appstream_autorenew measured it from a cold profile), so this is
            # a real self-heal and not a slower way to fail. Only a machine that
            # opted out with APPSTREAM_NO_FORM_LOGIN=1 stops here, saying the
            # one thing that fixes it (see _appstream_form_login_allowed). The
            # ownerville SSO URL hop is not an option either: it lands on the
            # ownerville report view, not the rcaptain console.
            if not _appstream_form_login_allowed(
                    allow_form_login=allow_form_login,
                    force_form_login=force_form_login,
                    username=username, password=password):
                raise _appstream_reseed_error(
                    "the saved session (.appstream_storage_state.json) has no "
                    "live token, and this run may not drive the login form")

            # The form drive itself: reached by an opt-in caller, or by a
            # scheduled run whose saved session went stale.
            try:
                user = username or creds.appstream_username()
                pwd  = password or creds.appstream_password()
            except RuntimeError as _cred_err:
                # The caller DID ask for the form, so the missing credential is
                # a real answer — but name the re-seed too, because on a report
                # machine that is nearly always the shorter road.
                raise _appstream_reseed_error(
                    "the saved session is stale and the login form can't run "
                    "either (no AppStream credentials on this machine)",
                    detail=str(_cred_err)) from _cred_err
            # An explicit username override must NEVER silently ride a session
            # some other account left in this profile: if the profile is already
            # signed in, applicantstream.com shows no login form, the form-drive
            # below is skipped, and the whole run proceeds as WHOEVER the
            # profile was — which is exactly how Lucy 2's "rcaptain" verify
            # actually ran as Carlos Hidalgo (2026-08-20). A marker file in the
            # profile records who last form-logged-in here; on mismatch (or no
            # marker) the cookies are cleared so the real form renders.
            _acct_marker = Path(profile) / ".appstream_account"
            _restored = False
            if username:
                try:
                    _last = (_acct_marker.read_text().strip()
                             if _acct_marker.exists() else "")
                except Exception:
                    _last = ""
                if _last != username:
                    try:
                        ctx.clear_cookies()
                        if verbose:
                            print(f"-> profile last logged in as "
                                  f"{_last or '<unknown>'} — cleared cookies to "
                                  f"force a real {username} login", flush=True)
                    except Exception as _e:
                        if verbose:
                            print(f"-> couldn't clear cookies ({_e}) — the "
                                  "login may reuse the wrong account", flush=True)
                else:
                    # The profile's session already belongs to this account
                    # (seeded by --appstream-seed-alt, or left by a prior
                    # login). A bare page load still shows the LOGIN form even
                    # with live cookies — only the ?rqst=<TOKEN> URL restores
                    # the console — so try the token hop BEFORE concluding a
                    # form drive (dead since the 2026-08-20 release put an
                    # interactive human-check on the form) is needed.
                    for _tok in [c["name"][len("rqst_"):]
                                 for c in ctx.cookies()
                                 if c.get("name", "").startswith("rqst_")]:
                        try:
                            page.goto(f"{APPSTREAM_BASE}?rqst={_tok}&p=701",
                                      wait_until="domcontentloaded")
                            page.wait_for_selector("#searchMC", timeout=8_000)
                            _restored = True
                            if verbose:
                                print(f"-> {username} console restored from the "
                                      "profile's own session", flush=True)
                            break
                        except Exception:
                            continue
            # DO NOT clear cookies on a forced form login. Tried on 2026-09-02
            # and MEASURED WRONG on Lucy 1: the theory was that applicantstream
            # was resuming the profile's session instead of issuing, so clearing
            # would force a real mint. It does force the form to render — and
            # the login still produces NO rqst_ cookie, because the applicantstream
            # form does not mint one. The rqst token comes from OWNERVILLE SSO
            # (_sso_to_appstream: ownerville ?p=701 → applicantstream), which is
            # why _ownerville_tokens() is described as what makes applicantstream
            # ISSUE while our own saved token only makes it RESTORE.
            #
            # So clearing deleted the only working token and minted nothing: the
            # save below found zero rqst_ cookies and skipped, and the run only
            # reached a console because the hop re-injected the OLD saved state.
            # A forced login re-authenticates the ACCOUNT; the token still has to
            # come from the ownerville hop.
            if not _restored:
                if verbose:
                    print("-> [allow_form_login] driving AppStream login form",
                          flush=True)
                page.goto("https://applicantstream.com/",
                          wait_until="domcontentloaded")
                page.wait_for_timeout(3_000)
                if (page.locator(_PASSWORD_SELECTOR).count() > 0
                        or page.locator(_APPSTREAM_USERNAME_SELECTOR).count() > 0):
                    _drive_login_form(page, verbose, username=user, password=pwd)
                    try:
                        _acct_marker.write_text(user)
                    except Exception:
                        pass
                elif verbose:
                    print("-> AppStream session reused from profile", flush=True)
                page.wait_for_timeout(3_000)
            # Persist the freshly-authenticated session so sibling reports in the
            # same batch reuse it (fast) instead of each re-driving the login +
            # Cloudflare wait. Only save a real console session (carries an rqst_
            # cookie) — never clobber the last good export with a half-login.
            # And NEVER when running as an explicit override account: saving an
            # alternate login here would hand its identity to every primary
            # report that reuses the shared state file.
            try:
                if not username:
                    _st = ctx.storage_state()
                    if sum(1 for c in _st.get("cookies", [])
                           if c.get("name", "").startswith("rqst_")):
                        APPSTREAM_STORAGE_STATE.write_text(json.dumps(_st))
                        if verbose:
                            print("-> saved fresh AppStream session for reuse",
                                  flush=True)
            except Exception:
                pass
            # The login lands on the HOME page (index.cfm), not the office
            # switcher (#searchMC) that callers like pull_as_weeks expect. If
            # we're not already on it, hop to it via the just-minted rqst (the
            # same ?rqst=<TOKEN>&p=701 nav the reuse path uses).
            try:
                if page.locator("#searchMC").count() == 0:
                    if verbose:
                        print("-> login landed off the office switcher — hopping "
                              "to #searchMC via the fresh token", flush=True)
                    if username:
                        # Override-account login: hop via the CURRENT context's
                        # just-minted rqst token. The shared storage-state file
                        # belongs to the PRIMARY account — re-injecting it here
                        # would silently flip the session back to that identity.
                        for _tok in [c["name"][len("rqst_"):]
                                     for c in ctx.cookies()
                                     if c.get("name", "").startswith("rqst_")]:
                            page.goto(f"{APPSTREAM_BASE}?rqst={_tok}&p=701",
                                      wait_until="domcontentloaded")
                            try:
                                page.wait_for_selector("#searchMC", timeout=8_000)
                                break
                            except Exception:
                                continue
                    else:
                        _reuse_appstream_storage_state(ctx, page, verbose)
            except Exception:
                pass
            # Final guard: never yield a dead console. If #searchMC still isn't
            # present after the login + token hop, the login didn't complete
            # (Cloudflare re-challenge) — fail LOUDLY so the run stops cleanly
            # and the one-time reseed fallback is used, instead of cascading a
            # #searchMC-timeout through every owner (Megan 2026-07-03).
            if page.locator("#searchMC").count() == 0:
                # Say WHERE the failed login actually landed — "didn't complete"
                # alone can't distinguish a Cloudflare challenge from a rejected
                # password from a site change (2026-08-20: three blind probes).
                _where = ""
                try:
                    _body = " ".join(page.inner_text("body").split())[:200]
                    _where = f"\nlanded on: {(page.url or '?')[:100]}\npage says: {_body!r}"
                    _shot = (Path(__file__).resolve().parents[2] / "output"
                             / "appstream-login-fail.png")
                    _shot.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(_shot))
                    _where += f"\nscreenshot: {_shot}"
                except Exception:
                    pass
                raise RuntimeError(
                    "AppStream console never rendered #searchMC after login — "
                    "the login didn't complete (Cloudflare re-challenge, "
                    "rejected password, or a site change)." + _where + "\n"
                    "Re-seed once with:\n"
                    "    PYTHONPATH=. .venv/bin/python -m "
                    "automations.shared.tableau_patchright --appstream-login")
            if verbose:
                print(f"-> AppStream console ready "
                      f"(page at {(page.url or '')[:72]})", flush=True)
            yield page
        finally:
            ctx.close()


def _capture_appstream_state(verbose: bool = True,
                             account: Optional[str] = None,
                             wait_min: float = 5.0) -> bool:
    """One-time interactive capture of the AppStream session. Opens a HEADED
    browser on the persistent .appstream_profile and signs in as whatever
    account THIS machine is configured for (see `who` below — never a literal;
    a hardcoded account name here sent two re-seeds down a retired login on
    2026-09-02). Once the office console (#searchMC) appears, the session
    (cookies incl. CFID/CFTOKEN + the rqst_<TOKEN> SSO cookies) is written to
    APPSTREAM_STORAGE_STATE for the unattended runs to reuse.

    THIS IS NO LONGER THE ONLY WAY IN. The docstring used to say "AppStream's
    own Cloudflare can't be cleared headlessly, so this interactive seed is the
    only way to (re)establish the session". It is not: the check clears itself
    given ~30s before submit, and appstream_direct_session drives the form
    unattended (measured from a cold profile on Lucy 1, 2026-09-02). This stays
    as the deliberate hands-on path — for a first install, or when a login is
    failing and you want to watch it.

    account: capture a DIFFERENT account's session into its own capture profile
    and state file (.appstream_storage_state_<account>.json), which
    --appstream-push-primary --account <name> then ships to the runner. A clean
    profile is used because the default one would silently auto-resume as
    whoever last signed in there. NOTE there are only two accounts left —
    'Lucy Reports' and 'Lucy Resume Pushing' (Megan 2026-09-02); rcaptain and
    the CarlosNLR slot are retired.

    wait_min: how long to watch for the office console before giving up
    (default 5, unchanged for every existing caller). Raise it when the person
    signing in is remote or intermittent — three seeds were lost on 2026-09-02
    to a 5-minute ceiling nobody was standing at."""
    if account:
        profile = APPSTREAM_PROFILE_DIR.parent / f".appstream_profile_cap_{account}"
        state_path = APPSTREAM_STORAGE_STATE.with_name(
            f".appstream_storage_state_{account}.json")
        who = account
    else:
        profile = APPSTREAM_PROFILE_DIR
        state_path = APPSTREAM_STORAGE_STATE
        # NAME THE ACCOUNT THIS MACHINE IS ACTUALLY CONFIGURED FOR. This said
        # "rcaptain" unconditionally, long after the migration to per-person
        # logins — so the seed prompt told the human to sign in as a RETIRED
        # account, and the success line claimed "rcaptain console reached" no
        # matter who had signed in. On 2026-09-02 that string sent a re-seed
        # down the wrong account twice and misdirected the incident diagnosis.
        # Fall back to the literal only if no credential resolves.
        try:
            who = creds.appstream_username() or "the configured account"
        except Exception:  # noqa: BLE001 — a missing credential is not fatal here
            who = "the configured account"
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
        print(f"  • sign in as {who}")
        print("  • THEN go to:  applicantstream.com/index.cfm?p=701")
        print("    (that loads the office search box — which is what gets saved)")
        print(f"  Waiting for the office console to load (up to {wait_min:g} min)…")
        print("=" * 64 + "\n", flush=True)
        seen = False
        # 5s per tick; at least one tick so wait_min=0 still probes once.
        for _ in range(max(1, int(round(wait_min * 12)))):
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
            print(f"❌ Didn't detect the office console (#searchMC) within "
                  f"{wait_min:g} min — nothing saved. Re-run and finish the "
                  f"login (--wait-min N buys more time).", flush=True)
            ctx.close()
            return False
        state = ctx.storage_state()
        state_path.write_text(json.dumps(state))
        cookies = state.get("cookies", [])
        n_rqst = sum(1 for c in cookies if c.get("name", "").startswith("rqst_"))
        print(f"✅ Saved AppStream session ({len(cookies)} cookies, {n_rqst} "
              f"rqst token(s)) → {state_path.name}", flush=True)
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
    ap.add_argument("--wait-min", type=float, default=5.0, metavar="N",
                    help="With --appstream-login: minutes to wait for the "
                         "office console before giving up (default 5). Raise "
                         "it when the person signing in is remote.")
    ap.add_argument("--appstream-check", action="store_true",
                    help="REUSE-ONLY probe: does the SAVED session still "
                         "authenticate from THIS machine? Never logs in, so a "
                         "dead session fails instead of silently re-seeding.")
    ap.add_argument("--appstream-form-login", action="store_true",
                    help="Test the UNATTENDED AppStream form login as this "
                         "machine's configured account (now that "
                         "Cloudflare auto-passes) → real console + save session.")
    ap.add_argument("--ownerville-check", action="store_true",
                    help="REUSE-ONLY probe: does the SAVED ownerville session "
                         "still mint an rqst FROM THIS MACHINE? Never touches "
                         "the login form, so a dead session fails instead of "
                         "silently re-seeding. The twin of --appstream-check.")
    ap.add_argument("--ownerville-form-login", action="store_true",
                    help="Test whether ownerville's Cloudflare auto-passes now: "
                         "drive the OV login in a THROWAWAY profile, unattended.")
    ap.add_argument("--appstream-extension", action="store_true",
                    help="One-time: open the AppStream profile HEADED with "
                         "extensions ENABLED so you can install the resume-"
                         "extractor plugin (the robot) into it. It then persists "
                         "for every scheduled resume_pushing run.")
    ap.add_argument("--appstream-push-alt", nargs="?", const="Lucy 2",
                    metavar="MACHINE", default=None,
                    help="Push THIS machine's saved AppStream session to another "
                         "machine's ALTERNATE-account profiles via the Mini "
                         "Control queue (default machine: Lucy 2). Run it right "
                         "after --appstream-login so the session is fresh. The "
                         "session JSON goes file->queue directly; the queue "
                         "blanks it once installed.")
    ap.add_argument("--appstream-seed-alt", metavar="JSON_PATH", default=None,
                    help="(runner side) Inject an exported AppStream session "
                         "into THIS machine's alternate-account browser "
                         "profiles. Normally invoked by the mini-control action "
                         "set_appstream_alt_state, not by hand.")
    ap.add_argument("--appstream-push-primary", nargs="?", const="Lucy 1",
                    metavar="MACHINE", default=None,
                    help="DISCOURAGED — hands THIS machine's saved AppStream "
                         "session to another machine. Since every Lucy signs in "
                         "as its own account that REPLACES who that machine is. "
                         "Needs --i-know-this-swaps-identity.")
    ap.add_argument("--appstream-push-fleet", action="store_true",
                    help="DISCOURAGED — pushes the saved session to the whole "
                         "fleet. Each Lucy logs itself in; use --appstream-login "
                         "on the machine that needs one. Needs "
                         "--i-know-this-swaps-identity.")
    ap.add_argument("--i-know-this-swaps-identity", action="store_true",
                    help="Required to actually perform a session push. Read the "
                         "refusal text first — this is almost never what you want.")
    ap.add_argument("--account", metavar="NAME", default=None,
                    help="With --appstream-login / --appstream-push-primary: "
                         "capture/push a NAMED account's session in its own "
                         "slot. Only two accounts exist: the reporting login "
                         "(default) and 'lucyresume'.")
    args = ap.parse_args()

    # PUSHING A SESSION IS AN IDENTITY SWAP, NOT A FAVOUR (Megan 2026-09-02:
    # "one machine CANNOT depend on another, we don't want 1 taking them all
    # down").
    #
    # These two flags are the last cross-machine dependency in the AppStream
    # path. They were built when all three boxes shared one rcaptain login, and
    # then a pushed storage_state really was just a fresher copy of the same
    # session. It is not that any more: Lucy 1 authenticates as 'Lucy Reports',
    # the resume pusher as 'Lucy Resume Pushing', and handing one machine's
    # cookies to another does not top up its session — it makes that machine
    # somebody else, silently, for every office lookup behind it. That is the
    # same class of failure as Lucy 2's "rcaptain" verify actually running as
    # Carlos Hidalgo (2026-08-20).
    #
    # They also create the outage this is meant to remove: a fleet that gets its
    # session from one donor is a fleet that dies when the donor does.
    #
    # Refused rather than deleted, because deleting them would just move the
    # question to whoever finds the old command in a runbook. The refusal names
    # the command that does work.
    if (args.appstream_push_primary is not None or args.appstream_push_fleet) \
            and not args.i_know_this_swaps_identity:
        import sys as _sys
        print("❌ Refusing to push an AppStream session to another machine.\n"
              "   Every Lucy signs in as its OWN account now, so a push does not\n"
              "   refresh the other machine's session — it REPLACES WHO THAT\n"
              "   MACHINE IS, and every office lookup behind it becomes the\n"
              "   wrong account's. It also rebuilds the single point of failure\n"
              "   we just removed: one donor down takes the fleet down.\n"
              "\n"
              "   Fix the machine that has no session, ON that machine:\n"
              "       PYTHONPATH=. .venv/bin/python -m "
              "automations.shared.tableau_patchright --appstream-login\n"
              "   or queue it without SSH:  lucy appstream_whoami --machine \"<name>\"\n"
              "   Then confirm BOTH logins there:\n"
              "       PYTHONPATH=. .venv/bin/python -m automations.shared.login_check\n"
              "\n"
              "   If you genuinely mean to overwrite another machine's identity,\n"
              "   re-run with --i-know-this-swaps-identity.")
        _sys.exit(1)
    if args.appstream_push_primary is not None or args.appstream_push_fleet:
        import sys as _sys
        _state_path = (APPSTREAM_STORAGE_STATE if not args.account else
                       APPSTREAM_STORAGE_STATE.with_name(
                           f".appstream_storage_state_{args.account}.json"))
        if args.appstream_push_fleet and args.account:
            print("❌ --appstream-push-fleet is the rcaptain routine — use "
                  "--appstream-push-primary <machine> --account <name> for "
                  "another account")
            _sys.exit(1)
        if not _state_path.exists():
            print(f"❌ no saved session ({_state_path.name} missing) — run "
                  "--appstream-login"
                  + (f" --account {args.account}" if args.account else "")
                  + " first")
            _sys.exit(1)
        _blob = _state_path.read_text()
        try:
            _n_rqst = sum(1 for c in json.loads(_blob).get("cookies", [])
                          if c.get("name", "").startswith("rqst_"))
        except Exception as _e:
            print(f"❌ saved session unreadable: {_e}")
            _sys.exit(1)
        if _n_rqst == 0:
            print("❌ saved session has no rqst_ token — re-run --appstream-login")
            _sys.exit(1)
        from automations.day_orchestrator import mini_control as _mc
        # Where each machine wants the rcaptain session. Since 2026-08-21 ALL
        # machines run rcaptain as primary (Megan: rcaptain sees everything
        # CarlosNLR did, so one account, one daily re-seed); Lucy 2 also keeps
        # its alt slot fresh so `--account alt` flags keep working unchanged.
        #
        # LUCY 3 ADDED 2026-08-24. This list used to end at Lucy 2 with a note
        # saying "extend here when Lucy 3 exists" — Lucy 3 went live 8/21 and
        # nobody came back to it, so the daily re-seed quietly covered two of
        # three machines for three days. Lucy 3 runs alphalete_org_focus, whose
        # Recruiting pull is AppStream, and on 8/24 that step failed on an
        # expired session while Lucy 1 and Lucy 2 were freshly seeded. A machine
        # missing from THIS list has no other way to get the session, and
        # nothing reports the gap — the miss only shows up as that machine's
        # AppStream reports failing the next morning.
        #
        # ADDING A MACHINE: one line here. The push is idempotent and each
        # machine installs + verifies its own copy.
        if args.appstream_push_fleet:
            # Lucy 2's ALT slot came off this list 2026-08-25. It had been
            # failing its verify every push since the 8/20 human-gate: the alt
            # profile belongs to another account, so installing rcaptain's
            # session there falls through to a login form that can no longer
            # complete unattended ("console never rendered #searchMC"). Nothing
            # depended on it — since 8/21 every machine runs rcaptain as primary
            # and NO scheduled report passes --alt-appstream or --account — so
            # the only thing the push produced was a red `failed` row every
            # morning that named no real problem, which is worse than silence:
            # it trains people to skim past a failed re-seed row.
            # The capability is NOT gone. If an ICD ever needs the alternate
            # account again, capture it and ship it on purpose with
            #   --appstream-login --account <name>
            #   --appstream-push-primary "Lucy 2" --account <name>
            # (or --appstream-push-alt "Lucy 2"), and put the line back here.
            _dests = [("Lucy 1", "set_appstream_state"),
                      ("Lucy 2", "set_appstream_state"),
                      ("Lucy 3", "set_appstream_state")]
        else:
            _dests = [(args.appstream_push_primary, "set_appstream_state")]
        for _m, _act in _dests:
            _mc.enqueue(_act, _blob, by="appstream-push", machine=_m)
            print(f"✅ queued → {_m} as {_act}")
        print("Each machine installs + verifies on its own and blanks the "
              "session from the queue when done. Check with the machine's "
              "Mini Control status.")
        _sys.exit(0)
    if args.appstream_push_alt is not None:
        import sys as _sys
        _machine = args.appstream_push_alt
        if not APPSTREAM_STORAGE_STATE.exists():
            print(f"❌ no saved session ({APPSTREAM_STORAGE_STATE.name} missing) "
                  "— run --appstream-login first")
            _sys.exit(1)
        _blob = APPSTREAM_STORAGE_STATE.read_text()
        try:
            _n_rqst = sum(1 for c in json.loads(_blob).get("cookies", [])
                          if c.get("name", "").startswith("rqst_"))
        except Exception as _e:
            print(f"❌ saved session unreadable: {_e}")
            _sys.exit(1)
        if _n_rqst == 0:
            print("❌ saved session has no rqst_ token — it wouldn't restore a "
                  "console. Re-run --appstream-login first.")
            _sys.exit(1)
        from automations.day_orchestrator import mini_control as _mc
        _mc.enqueue("set_appstream_alt_state", _blob,
                    by="appstream-push-alt", machine=_machine)
        print(f"✅ queued the saved session ({_n_rqst} rqst token) to "
              f"'{_machine}' as set_appstream_alt_state — watch it with the "
              "machine's Mini Control status. The queue blanks the session "
              "from the sheet once the row finishes.")
        _sys.exit(0)
    if args.appstream_seed_alt:
        import sys as _sys
        _src = Path(args.appstream_seed_alt)
        try:
            _state = json.loads(_src.read_text())
        except Exception as _e:
            print(f"❌ couldn't read state JSON at {_src}: {_e}")
            _sys.exit(1)
        _cookies = _state.get("cookies", [])
        _n_rqst = sum(1 for c in _cookies
                      if c.get("name", "").startswith("rqst_"))
        if not _cookies or _n_rqst == 0:
            print(f"❌ state has {len(_cookies)} cookie(s) and {_n_rqst} rqst "
                  "token(s) — refusing to seed a session that can't restore "
                  "a console")
            _sys.exit(1)
        try:
            from automations.shared import creds as _creds
            _alt_user = _creds.appstream_alt_username()
        except Exception:
            print("❌ no alternate AppStream login configured here — run the "
                  "set_appstream_alt_creds action first (the seeded session "
                  "needs a username for the identity marker)")
            _sys.exit(1)
        # Both alternate-account profiles get the session: appstream_whoami
        # --alt verifies on one, funnel_board --account alt runs on the other.
        _targets = [APPSTREAM_PROFILE_DIR.parent / ".appstream_profile_alt",
                    APPSTREAM_PROFILE_DIR.parent / ".appstream_profile_funnel_alt"]
        with sync_playwright() as _p:
            for _prof in _targets:
                _prof.mkdir(exist_ok=True, parents=True)
                _ctx = _launch_persistent(_p, _prof, headless=True,
                                          label="seed_alt", verbose=False)
                try:
                    _ctx.clear_cookies()
                    _ctx.add_cookies(_cookies)
                finally:
                    _ctx.close()
                # Stamp who this session belongs to, so the form-login identity
                # guard doesn't clear the cookies we just planted.
                (_prof / ".appstream_account").write_text(_alt_user)
                print(f"-> seeded {len(_cookies)} cookie(s) into {_prof.name} "
                      f"(marker: {_alt_user})", flush=True)
        print(f"✅ alternate session seeded for {_alt_user} on both profiles")
        _sys.exit(0)
    if args.appstream_extension:
        import sys as _sys
        print("Opening the AppStream automation profile with extensions ENABLED.\n"
              "  1. The AppStream console opens in the window that appears.\n"
              "  2. Go to Applicants -> Process Emails -> Process in Batches.\n"
              "  3. If there's no robot icon, click the DOWNLOAD PLUGIN option and\n"
              "     install the extension INTO THIS BROWSER WINDOW.\n"
              "  4. Refresh the page and confirm the robot icon now appears.\n"
              "  5. Come back to this terminal and press Enter to close.\n"
              "The extension is saved in the PERSISTENT profile, so every scheduled\n"
              "run gets it from then on.\n", flush=True)
        try:
            # Headed and a human is sitting here, so the login form is still a
            # usable fallback for THIS command — unlike a scheduled run.
            with appstream_direct_session(headless=False, verbose=True,
                                          allow_form_login=True,
                                          enable_extensions=True) as _pg:
                print(f"\n-> console at {(_pg.url or '')[:78]}", flush=True)
                input("\nPress Enter once the robot icon is showing… ")
            print("✓ closed — the extension is saved in the profile. Now verify "
                  "unattended with:\n"
                  "    python -m automations.resume_pushing.run --debug")
            _sys.exit(0)
        except Exception as _e:
            print(f"❌ {type(_e).__name__}: {str(_e)[:200]}")
            _sys.exit(1)
    if args.appstream_form_login:
        import sys as _sys
        _ok = False
        try:
            with appstream_direct_session(allow_form_login=True,
                                          force_form_login=True,
                                          headless=False, verbose=True) as _pg:
                _got = _pg.locator("#searchMC").count() > 0
                print(f"\n-> landed at {(_pg.url or '')[:78]}")
                if _got:
                    _st = _pg.context.storage_state()
                    APPSTREAM_STORAGE_STATE.write_text(json.dumps(_st))
                    _nr = sum(1 for c in _st.get("cookies", [])
                              if c.get("name", "").startswith("rqst_"))
                    # Report the account actually used, not a hardcoded name.
                    try:
                        _who = creds.appstream_username() or "configured account"
                    except Exception:  # noqa: BLE001
                        _who = "configured account"
                    print(f"✅ {_who} console reached UNATTENDED — saved session "
                          f"({len(_st.get('cookies', []))} cookies, {_nr} rqst) "
                          f"→ {APPSTREAM_STORAGE_STATE.name}")
                    _ok = _nr > 0
                else:
                    print("❌ did NOT reach the AppStream console (#searchMC) — "
                          "Cloudflare may still be challenging the form, or the "
                          "login didn't submit. Nothing saved.")
        except Exception as _e:
            print(f"❌ form login error: {type(_e).__name__}: {str(_e)[:160]}")
        _sys.exit(0 if _ok else 1)
    if args.appstream_login:
        import sys as _sys
        _sys.exit(0 if _capture_appstream_state(verbose=True,
                                                account=args.account,
                                                wait_min=args.wait_min) else 1)
    if args.ownerville_form_login:
        import sys as _sys
        # Throwaway profile so we NEVER touch the holder's / reports' shared
        # profile. NOTE: ownerville is one-session-per-account, so this login can
        # still bump a live holder session server-side — stop the holder first.
        _test_profile = PROFILE_DIR.parent / ".ov_login_test"
        _test_profile.mkdir(exist_ok=True, parents=True)
        _ok = False
        with sync_playwright() as _p:
            _ctx = _launch_persistent(_p, _test_profile, headless=False,
                                      label="ov_form_login_test", verbose=True)
            _pg = _ctx.pages[0] if _ctx.pages else _ctx.new_page()
            try:
                _pg.goto(LOGIN_URL, wait_until="domcontentloaded")
                _pg.wait_for_timeout(3_000)
                try:
                    _pg.wait_for_selector(
                        f"{_PASSWORD_SELECTOR}, {_USERNAME_SELECTOR}",
                        timeout=20_000)
                except Exception:
                    pass
                _drive_login_form(_pg, verbose=True)   # defaults to OV creds
                _ok = _ownerville_session_valid(_pg, verbose=True)
                print("\n✅ ownerville form login reached a LIVE session UNATTENDED "
                      "(rqst present) — Cloudflare auto-passes; the holder could be "
                      "retired." if _ok else
                      "\n❌ ownerville form login did NOT reach a live session — "
                      "Cloudflare still blocks the OV form; keep the holder.")
            except Exception as _e:
                print(f"\n❌ ownerville form login error: {type(_e).__name__}: "
                      f"{str(_e)[:180]}")
            finally:
                _ctx.close()
        _sys.exit(0 if _ok else 1)
    if args.ownerville_check:
        # Reuse-only ON PURPOSE (allow_form_login=False): a dead session RAISES
        # instead of quietly driving the Turnstile, so this answers the one
        # question a SHIPPED session poses — does it authenticate from THIS
        # machine, or was it bound to the browser that logged in? The twin of
        # --appstream-check, and what set_ownerville_state verifies with.
        try:
            with ownerville_session(verbose=True,
                                    allow_form_login=False) as pg:
                url = pg.url or ""
                ok = "ownerville.com" in url
            print("✅ ownerville session VALID from this machine" if ok else
                  "❌ landed on a non-ownerville page: " + url[:90])
            raise SystemExit(0 if ok else 1)
        except SystemExit:
            raise
        except Exception as e:
            print(f"❌ ownerville session REJECTED here: "
                  f"{type(e).__name__}: {str(e).splitlines()[0][:160]}")
            raise SystemExit(1)

    if args.appstream_check:
        # Reuse-only ON PURPOSE: allow_form_login=False means a dead session
        # RAISES instead of quietly re-driving the login, so this answers the
        # one question a shipped session poses -- does it authenticate from
        # THIS machine, or was it bound to the browser/IP that logged in?
        # (Eve 2026-08-24, mirroring the credico --check that set_credico_state
        # verifies with.)
        try:
            with appstream_direct_session(verbose=True,
                                          allow_form_login=False) as pg:
                url = pg.url or ""
                ok = "applicantstream.com" in url and "login" not in url.lower()
            print("✅ AppStream session VALID from this machine" if ok else
                  "❌ landed on a non-authed page: " + url[:90])
            raise SystemExit(0 if ok else 1)
        except SystemExit:
            raise
        except Exception as e:
            print(f"❌ AppStream session REJECTED here: "
                  f"{type(e).__name__}: {str(e).splitlines()[0][:160]}")
            raise SystemExit(1)

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

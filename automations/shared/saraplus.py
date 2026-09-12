"""SaraPlus mechanics, shared by every report that reads the Reporting Hub.

EVERY SARAPLUS IS THE SAME (Megan 2026-09-10) — same element ids, same grids,
same column indices, same row markers — so these live in ONE file and a site
change is one fix for every office and every report, not a hunt through
per-report copies.

NOTHING HERE KNOWS WHOSE ACCOUNT IT IS. No credentials, no profile directory,
no sheet, no channel: the caller passes a page and a login. That is not tidiness
— it is what lets `automations/icd_alerts` ship to an ICD's laptop without
carrying Alphalete's workbook id, Slack channel and iMessage groups along with
it, which importing `alphalete_sales_board.config` would do.

Lifted verbatim out of `alphalete_sales_board/sara.py` on 2026-09-10, comments
and all. Those comments are the expensive part — each one is a live-site failure
somebody already paid for (the Telerik date blob, the 404-that-looks-like-a-
changed-selector, domcontentloaded-not-networkidle). Read them before
"simplifying" anything here.

Python 3.9-safe and platform-neutral: this runs on the Lucys AND on ICD laptops,
which are not machines we set up.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

LOGIN_URL = "https://ui.saraplus.com"

HUB_PATH = "Reports/ReportingHub.aspx"

FIELD_START = "ctl00_MainContent_rdpOrderDashStartDate"
FIELD_END = "ctl00_MainContent_rdpOrderDashEndDate"
COMBO_INPUT = "#ctl00_MainContent_rcbOrderDashOptions_Input"
SUBMIT = "#MainContent_rbOrderDashSubmit"

GRID_ATT = "#ctl00_MainContent_rgOrderDashboard_ATT_ctl00"
GRID_ALL = "#ctl00_MainContent_rgOrderDashboard_ctl00"
GRID_INTERNET = "#ctl00_MainContent_rgOrderDash_ATT_Internet_ctl00"

# 0-based column indices, per grid.
COL_ROWTYPE = 1
COL_ATT = {"name": 2, "internet_sales": 9, "internet_upgrades": 10,
           "aia_sales": 11, "wireless_lines_sold": 14}
COL_ALL = {"name": 2, "dtv": 4}
COL_INTERNET = {"name": 2, "records": 3}

# The row-type marker that means "this row is one rep". The AT&T Internet grid
# uses a DIFFERENT one -- 6_Agent, not 5_Agent -- and reading it with the wrong
# marker returns an empty result rather than a wrong one.
AGENT_ROW = "5_Agent"
AGENT_ROW_INTERNET = "6_Agent"

GRID_TIMEOUT_MS = 90_000
NAV_TIMEOUT_MS = 60_000


class SaraError(RuntimeError):
    pass


class SaraPasswordWall(SaraError):
    """SaraPlus served its Change Password page. Its OWN type because the
    caller has to do something specific about it -- retry on a fresh profile --
    and `except SaraError` must not swallow that decision."""
    pass


class SaraPasswordChangeRequired(SaraError):
    """The wall survived a brand-new profile, so SaraPlus really is demanding a
    new password. Megan 2026-09-12: 'sara asks every few weeks for a new PW
    update' -- so this is a NORMAL, RECURRING event, not a breakage. Needs a
    human: only a person can choose a password."""
    pass


# SARAPLUS'S SECURITY AREA -- the browser-verification wall, NOT a password
# problem. Everything under /Security/ on the dealer session root
# (https://www.saraplus.com/e/(S(<session>))/Security/...) is SaraPlus saying
# "it appears that this is a new location or browser" and refusing to serve
# the Hub until an emailed passcode clears. The session id in that url is the
# proof: the PASSWORD WAS ACCEPTED before we ever got here.
#
# 2026-09-12, read the wrong way twice: the sales board sweep failed 3 passes
# with only "landed somewhere unexpected" (reads like a moved page), and the
# first fix called it a forced password change (reads like an expired
# password). Megan: the SaraPlus password had not changed. Both wrong for the
# same reason -- the URL was never checked against what /Security/ means.
# rc_contact_sync already hit this wall on the B2B account on 2026-09-03 and
# built the passcode flow for it; the shared login never got one, so it walks
# into the challenge and gives up. [[reference_saraplus_reporting_hub]]
SECURITY_PATH = "/security/"

# THE RESET PAGE IS A PROFILE SYMPTOM, NOT AN ACCOUNT ONE. Proved on
# 2026-09-12 by running the SAME credential three ways within one minute:
#
#   Megan's incognito Chrome        -> DealerPages/SubmitOrders.aspx   OK
#   a brand NEW empty profile here  -> DealerPages/SubmitOrders.aspx   OK
#   the sweep's .saraplus_profile   -> Security/ResetPassword.aspx     STUCK
#
# Same account, same password file, same machine, same minute. The only
# variable was the Chrome profile, and moving it aside fixed the sweep on the
# very next tick after 30 straight failures.
#
# So do NOT read this page's words as truth about the account. It says "SARA
# Plus requires a reset of your SARA Password" and that sentence is a lie about
# everything except this browser -- it cost a whole day, two password changes
# Megan did not need to make, and three wrong diagnoses in a row:
#   "SaraPlus moved a page" -> "the password expired" -> "a passcode challenge"
# Megan said twice that the password had not changed. She was right twice.
#
# THE FIRST THING TO TRY IS ALWAYS THE PROFILE.
RESET_PATH = "/security/resetpassword.aspx"
RESET_WORDS = ("requires a reset of your sara password", "change password")


def _is_password_reset(page, url: str) -> bool:
    if RESET_PATH in (url or "").lower():
        return True
    try:
        body = (page.evaluate("() => (document.body.innerText || '')") or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(w in body for w in RESET_WORDS)


def _stuck_profile_error(url: str, email: str, creds_hint: str,
                         profile_hint: str = "this report's Chrome profile") -> "SaraError":
    return SaraError(
        "SaraPlus served its Change Password page to %s (%s). READ THIS BEFORE "
        "TOUCHING THE PASSWORD: that page is almost always about THIS BROWSER "
        "PROFILE, not the account. On 2026-09-12 the identical credential went "
        "straight into DealerPages from an incognito window AND from a new "
        "empty profile, while this profile got stuck here for 30 passes. "
        "FIX, in order: (1) move %s aside -- it is only browser state and the "
        "next run recreates it; the sweep recovered on the very next tick. "
        "(2) ONLY if a brand-new empty profile ALSO lands here is the account "
        "really being asked to reset, in which case sign in at %s and set a "
        "new password (8-15 chars, 1 upper, 1 lower, 1 number, not the last 5, "
        "and no run of 3+ characters from the old one), then store it with "
        "set_credentials (%s). Nothing was read and nothing was written."
        % (email, url, profile_hint, LOGIN_URL, creds_hint))


def _int(v) -> int:
    try:
        return int(str(v).strip().replace(",", "") or 0)
    except (TypeError, ValueError):
        return 0


def strip_office(name: str) -> str:
    """'FIRST LAST (CODE)- COMPANY' -> 'FIRST LAST'. The 'All' grid decorates
    every name with the office code; the AT&T grid does not."""
    import re
    return re.sub(r"\s*\([^)]+\).*$", "", str(name or "")).strip().upper()


# --- browser ----------------------------------------------------------------
def _login(page, email: str, password: str, *, login_url: str = LOGIN_URL,
           creds_hint: str = "the saved SaraPlus login", log=print) -> str:
    """Sign in and return the DealerPages base url. Raises if we land back on
    the login page -- a silent bounce there is how a whole day of sweeps can
    read as 'no sales' instead of 'not logged in'."""
    page.goto(login_url, wait_until="networkidle")
    page.click('a:has-text("LOGIN")')
    page.fill("#ctl00_MainContent_txtUserName", email)
    page.wait_for_selector("#ctl00_MainContent_txtPassword", state="visible")
    # Typed character by character on purpose: the site is old ASP.NET and its
    # field handlers drop a value that arrives in one paste-like event.
    page.click("#ctl00_MainContent_txtPassword")
    field = page.locator("#ctl00_MainContent_txtPassword")
    # press_sequentially is the current name; older builds only have type().
    # The runner's patchright is not necessarily the laptop's, and a login is
    # the worst place to find that out.
    if hasattr(field, "press_sequentially"):
        field.press_sequentially(password, delay=50)
    else:
        field.type(password, delay=50)
    with page.expect_navigation():
        page.click("#MainContent_btnLogin")
    url = page.url
    if "login" in url.lower():
        raise SaraError(
            "SaraPlus login failed -- still on the login page after submit. "
            "Check the credentials in %s (a password change is the usual "
            "cause); nothing was written." % creds_hint)
    # THE CHANGE PASSWORD PAGE, raised as its OWN type so the caller can run
    # the one test that tells a stuck profile from a real demand: try again on
    # a brand-new profile. See login_healing().
    if _is_password_reset(page, url):
        raise SaraPasswordWall(
            _stuck_profile_error(url, email, creds_hint).args[0])
    # TWO LANDING PAGES: a remembered browser lands on DealerPages/, some
    # logins land straight on Reports/ReportingHub.aspx. Splitting on
    # 'DealerPages/' alone called that second one "somewhere unexpected" and
    # threw away a login that had in fact just succeeded.
    if "DealerPages/" not in url and "Reports/" in url:
        return url.split("Reports/")[0]
    if SECURITY_PATH in url.lower():
        raise SaraPasswordWall(
            _stuck_profile_error(url, email, creds_hint).args[0])
    if "DealerPages/" not in url:
        raise SaraError("logged in but landed somewhere unexpected: %s" % url)
    # The DEALER ROOT -- everything up to and including the session segment,
    # e.g. https://www.saraplus.com/e/(S(<session>))/ -- and deliberately NOT
    # .../DealerPages/. The Reporting Hub is a SIBLING of DealerPages, not a
    # child of it: the live Analytics menu is
    #     onclick="window.location.href='../Reports/ReportingHub.aspx'"
    # and that '..' is the whole story. Building base as ".../DealerPages/"
    # and appending "Reports/ReportingHub.aspx" gives
    # .../DealerPages/Reports/ReportingHub.aspx, which SaraPlus serves as
    # 404.aspx -- and a 404 then presents as a selector timeout on the Service
    # dropdown, which reads like a changed control rather than a wrong url
    # (2026-08-26; read off the nav by `run --probe`).
    return url.split("DealerPages/")[0]


def _set_telerik_date(page, field_id: str, day: dt.date) -> None:
    """Set one RadDatePicker's FOUR agreeing pieces. See the module docstring."""
    page.evaluate(
        """([id, iso, mdy, cal]) => {
             const raw = document.getElementById(id);
             if (raw) raw.value = iso;
             const disp = document.getElementById(id + '_dateInput');
             if (disp) disp.value = mdy;
             const cs = document.getElementById(id + '_dateInput_ClientState');
             if (cs) {
               let st = {};
               try { st = JSON.parse(cs.value || '{}'); } catch (e) { st = {}; }
               st.validationText = iso + '-00-00-00';
               st.valueAsString  = iso + '-00-00-00';
               st.lastSetTextBoxValue = mdy;
               cs.value = JSON.stringify(st);
             }
             const ad = document.getElementById(id + '_calendar_AD');
             if (ad) ad.value = cal;
           }""",
        [field_id, day.isoformat(),
         "%d/%d/%d" % (day.month, day.day, day.year),
         "[[1980,1,1],[2099,12,30],[%d,%d,%d]]" % (day.year, day.month, day.day)],
    )


def page_state(page) -> str:
    """A one-line description of where we actually are. Every "selector not
    found" failure is really "not on the page you think you are", and the URL
    plus which landmarks exist is what tells the two apart."""
    marks = {
        "service combo": COMBO_INPUT,
        "start date": "#" + FIELD_START,
        "submit": SUBMIT,
        "att grid": GRID_ATT,
        "login form": "#ctl00_MainContent_txtUserName",
    }
    found = []
    for name, sel in marks.items():
        try:
            if page.locator(sel).count():
                found.append(name)
        except Exception:  # noqa: BLE001
            pass
    try:
        title = page.title()
    except Exception:  # noqa: BLE001
        title = "?"
    return "url=%s | title=%r | found: %s" % (
        page.url, title, ", ".join(found) or "NONE of the expected landmarks")


def _assert_on_hub(page, base_url: str) -> None:
    """Fail with the URL, not 30s later with a missing selector.

    SaraPlus answers a bad dealer path with 404.aspx, a real page -- so the
    navigation "succeeds" and the first thing that notices is whichever control
    we reach for next. Saying so here turns a puzzling selector timeout into
    the sentence "we asked for the wrong url"."""
    try:
        title = page.title()
    except Exception:  # noqa: BLE001
        title = ""
    if "404" in title or "404.aspx" in page.url:
        raise SaraError(
            "%s is a 404 for this dealer (landed on %s). The Reporting Hub sits "
            "beside DealerPages/, not inside it -- check what the Analytics menu "
            "points at with `run --probe`."
            % (base_url + HUB_PATH, page.url))


def _select_service(page, label: str) -> None:
    """Pick a value in the Telerik RadComboBox by its visible text."""
    try:
        page.wait_for_selector(COMBO_INPUT, timeout=20_000)
    except Exception as e:  # noqa: BLE001
        raise SaraError(
            "the Service dropdown (%s) never appeared, so the page we are on is "
            "not the Order Dashboard. %s -- run `--probe` to dump the page's "
            "real controls. (%s)" % (COMBO_INPUT, page_state(page),
                                     type(e).__name__))
    page.click(COMBO_INPUT)
    page.wait_for_timeout(800)
    picked = page.evaluate(
        """(want) => {
             const items = document.querySelectorAll('.rcbList li, [class*="rcbItem"]');
             for (const el of items) {
               if ((el.textContent || '').trim() === want) { el.click(); return true; }
             }
             return false;
           }""", label)
    if not picked:
        raise SaraError("no %r option in the Service dropdown" % label)
    page.wait_for_timeout(500)


def _run_report(page, base_url: str, day: dt.date, service: str, grid: str,
                attempts: int = 3, log=print) -> List[List[str]]:
    """One report pass, RETRIED -- SaraPlus is intermittently slow.

    Measured on the first night live: three sweeps died on
    `wait_for_selector: Timeout 90000ms` and `click: Timeout 30000ms`. The grid
    simply had not rendered; nothing was wrong with the login or the session.

    A failed sweep posts NOTHING, so a sale then waits ~7 minutes for the next
    tick. Retrying the pass re-navigates to a fresh hub page and asks again --
    what a person would do -- and turns most of those into a sweep that lands on
    time. Only a pass that fails every attempt fails the sweep, which is worth
    failing on: that means SaraPlus is down, not slow.
    """
    for attempt in range(1, attempts + 1):
        try:
            return _run_report_once(page, base_url, day, service, grid)
        except Exception as e:  # noqa: BLE001 — retry ANY per-pass failure
            if attempt == attempts:
                raise SaraError("the %r report failed %d times; last error %s: %s"
                                % (service, attempts, type(e).__name__, str(e)[:200]))
            log("  %r pass attempt %d/%d failed (%s) — retrying"
                % (service, attempt, attempts, type(e).__name__))
            try:
                page.wait_for_timeout(3000)
            except Exception:  # noqa: BLE001
                pass


def _run_report_once(page, base_url: str, day: dt.date, service: str,
                     grid: str) -> List[List[str]]:
    """Set the day + service, submit, and return the grid's rows as cell text."""
    # NOT networkidle. The ReportingHub is a Telerik page that keeps talking --
    # timers, keep-alives, partial postbacks -- so "no network for 500ms" may
    # never arrive and the navigation times out at 30s having actually loaded
    # the page fine (2026-08-26, the failure right after the url was fixed).
    # domcontentloaded plus an explicit wait for the control we need is both
    # faster and a truer test: it waits for the THING, not for silence.
    page.goto(base_url + HUB_PATH, wait_until="domcontentloaded",
              timeout=NAV_TIMEOUT_MS)
    page.wait_for_timeout(2000)
    _assert_on_hub(page, base_url)
    _set_telerik_date(page, FIELD_START, day)
    _set_telerik_date(page, FIELD_END, day)
    _select_service(page, service)
    page.click(SUBMIT)
    page.wait_for_selector(grid, timeout=GRID_TIMEOUT_MS)
    page.wait_for_timeout(2000)
    return page.evaluate(
        """(sel) => {
             const g = document.querySelector(sel);
             if (!g) return [];
             return Array.from(g.querySelectorAll('tbody tr')).map(
               tr => Array.from(tr.querySelectorAll('td')).map(
                 td => (td.innerText || '').trim()));
           }""", grid)


# --- parsing (pure, unit-tested offline) ------------------------------------
def agent_rows(rows: List[List[str]], marker: str) -> List[List[str]]:
    """The rep rows -- the ones whose row-type column holds `marker`. Group and
    territory rows share the grid and would double-count every sale."""
    out = []
    for r in rows:
        if len(r) > COL_ROWTYPE and r[COL_ROWTYPE].strip() == marker:
            out.append(r)
    return out


def parse_att(rows: List[List[str]]) -> List[Dict]:
    out = []
    for r in agent_rows(rows, AGENT_ROW):
        if len(r) <= max(COL_ATT.values()):
            continue
        out.append({
            "name": r[COL_ATT["name"]].strip(),
            "internet_sales": _int(r[COL_ATT["internet_sales"]]),
            "internet_upgrades": _int(r[COL_ATT["internet_upgrades"]]),
            "aia_sales": _int(r[COL_ATT["aia_sales"]]),
            "wireless_lines_sold": _int(r[COL_ATT["wireless_lines_sold"]]),
            "dtv_streaming": 0,
        })
    return out


def parse_dtv(rows: List[List[str]]) -> Dict[str, int]:
    """{UPPERCASE NAME: dtv}. Keyed uppercase because this grid's names carry
    the office code and the AT&T grid's do not."""
    out = {}
    for r in agent_rows(rows, AGENT_ROW):
        if len(r) <= max(COL_ALL.values()):
            continue
        key = strip_office(r[COL_ALL["name"]])
        if key:
            out[key] = out.get(key, 0) + _int(r[COL_ALL["dtv"]])
    return out


def parse_records(rows: List[List[str]]) -> Dict[str, int]:
    """{UPPERCASE NAME: credit checks}."""
    out = {}
    for r in agent_rows(rows, AGENT_ROW_INTERNET):
        if len(r) <= max(COL_INTERNET.values()):
            continue
        key = strip_office(r[COL_INTERNET["name"]])
        if key:
            out[key] = out.get(key, 0) + _int(r[COL_INTERNET["records"]])
    return out


def merge_dtv(agents: List[Dict], dtv: Dict[str, int]) -> List[Dict]:
    for a in agents:
        a["dtv_streaming"] = dtv.get(strip_office(a["name"]), 0)
    return agents



# --- browser ----------------------------------------------------------------
def rotate_profile(profile_dir, log=print):
    """Move a stuck Chrome profile aside and return where it went.

    ONE SLOT, not a growing pile: each of these is ~480MB (measured on Lucy 1,
    2026-09-12), so a new rotation replaces the previous keepsake rather than
    stacking beside it. One is enough -- it exists so somebody can look at what
    went stale, and nobody needs six.
    """
    import shutil
    from pathlib import Path
    src = Path(profile_dir)
    if not src.exists():
        return None
    kept = src.with_name(src.name + ".stuck")
    if kept.exists():
        shutil.rmtree(str(kept), ignore_errors=True)
    src.rename(kept)
    log("  moved the stuck profile aside -> %s" % kept.name)
    return str(kept)


def login_healing(playwright, profile_dir, email: str, password: str, *,
                  headless: bool = True,
                  creds_hint: str = "the saved SaraPlus login", log=print):
    """Open a context and log in, HEALING a stuck profile by itself.

    Returns (ctx, page, base_url). The caller owns ctx and must close it.

    THE ONE TEST THAT TELLS THE TWO APART. SaraPlus's Change Password page is
    usually a stuck profile and occasionally a real demand -- Megan 2026-09-12:
    "sara asks every few weeks for a new PW update" -- and from inside a single
    login they look identical. What separates them is cheap: throw the profile
    away and try once more on an empty one.

      wall -> fresh profile works  = the profile was stuck. Healed, nobody woken.
      wall -> fresh profile walls   = SaraPlus really is asking. Needs a human,
                                      because only a person can choose a password.

    Not doing this test cost a day on 2026-09-12: the page's own words were
    read as truth about the account, and the password was changed twice for a
    problem a 90-second retry would have disproved.
    """
    def _open_and_login():
        ctx = open_context(playwright, profile_dir, headless=headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return ctx, page, _login(page, email, password,
                                     creds_hint=creds_hint, log=log)
        except Exception:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
            raise

    try:
        return _open_and_login()
    except SaraPasswordWall as first:
        log("SaraPlus served its Change Password page -- testing whether it is "
            "this profile or the account")
        rotate_profile(profile_dir, log=log)
        try:
            ctx, page, base = _open_and_login()
        except SaraPasswordWall:
            raise SaraPasswordChangeRequired(
                "SaraPlus is genuinely asking %s for a new password. A "
                "BRAND-NEW empty Chrome profile landed on the same Change "
                "Password page, which is the one thing that rules out a stuck "
                "profile -- so this is the real every-few-weeks reset, not a "
                "browser problem. A human has to choose the password: sign in "
                "at %s, set a new one (8-15 chars, 1 upper, 1 lower, 1 number, "
                "not any of the last 5, and no run of 3+ characters from the "
                "old one), then store it with set_credentials (%s). Nothing "
                "was read and nothing was written." % (email, LOGIN_URL,
                                                       creds_hint)) from first
        log("  the profile was the problem, not the password -- healed, "
            "carrying on")
        return ctx, page, base


def open_context(playwright, profile_dir, *, headless: bool = True):
    """A persistent Chrome context on `profile_dir`.

    PERSISTENT ON PURPOSE. SaraPlus challenges a browser it does not recognise
    with an emailed passcode; the profile is what makes that a once-per-machine
    event instead of a once-per-run one. Callers own the directory, and they
    keep it somewhere a code update will not delete.
    """
    from pathlib import Path
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        str(profile_dir), headless=headless, args=["--disable-sync"])


# Public aliases. The originals are underscore-prefixed because they began life
# as one module's privates; they are this module's API now, and the underscore
# names stay so existing importers keep working.
login = _login
set_telerik_date = _set_telerik_date
assert_on_hub = _assert_on_hub
select_service = _select_service
run_report = _run_report
run_report_once = _run_report_once

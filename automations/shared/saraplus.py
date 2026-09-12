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


def _security_wall_error(url: str, email: str, creds_hint: str) -> "SaraError":
    return SaraError(
        "SaraPlus is CHALLENGING THIS BROWSER for %s and this login was given "
        "no way to read the code. The password was accepted -- that url "
        "carries a real session id -- and SaraPlus then sent us to its "
        "Security area instead of the Hub: %s. NOT an expired password: do "
        "not go changing the one in %s. Pass read_code= to login() (the "
        "Alphalete reports hand it rc_contact_sync.verify_code.wait_for_code), "
        "or sign in once by hand in this Chrome profile so SaraPlus remembers "
        "the browser. Nothing was read and nothing was written."
        % (email, url, creds_hint))


# --- the passcode wall -------------------------------------------------------
# Every line below was paid for on the B2B account on 2026-09-03 and is lifted
# from rc_contact_sync/sara.py, comments and all. It is HERE because the wall
# is the site's, not one report's: the sales board hit the identical challenge
# on 2026-09-12 and had nothing to answer it with.
#
# rc_contact_sync still runs its own copy on purpose -- it is live at 4am and
# collapsing a working login into a fresh refactor on the same day as an
# outage is how one broken report becomes two. Collapse them once this one has
# run clean for a week. [[reference_saraplus_reporting_hub]]
VERIFY_SETTLE_MS = 2500
VERIFY_TIMEOUT_S = 180
VERIFY_POLL_S = 10


def code_page_text(page, limit: int = 400) -> str:
    """What the challenge page actually SAYS, trimmed. Every 'no code box'
    report is really 'not the page you think', and its own words settle it."""
    try:
        txt = page.evaluate("() => (document.body.innerText || '').trim()") or ""
    except Exception:  # noqa: BLE001
        return "(unreadable)"
    return " ".join(txt.split())[:limit]


def _on_passcode_page(page) -> bool:
    """Still sitting in SaraPlus's Security area. The URL is the honest
    signal that the challenge has not been cleared -- the Hub we land on
    afterwards carries enough of the same vocabulary to read as 'still being
    asked' on a login that had in fact just succeeded."""
    try:
        url = (page.url or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return "passcode" in url or "verifycode" in url or SECURITY_PATH in url


def _needs_code(page) -> bool:
    """Is this login being asked to prove the browser? Judged on the PAGE, not
    on finding a text box -- the first screen is a destination picker that has
    no code box on it at all, and the box only appears on the next one."""
    try:
        url = (page.url or "").lower()
        body = (page.evaluate("() => (document.body.innerText || '')") or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if "passcode" in url or "verifycode" in url or SECURITY_PATH in url:
        return True
    return any(n in body for n in
               ("confirmation code", "verification code", "security code",
                "new location or browser", "enter the code"))


def _code_field(page):
    """The input to TYPE the code into, or None if this page has no such box.

    TEXT-LIKE INPUTS ONLY. It used to accept any non-password input whose id
    matched /code/, and on the picker screen that is `btnGetCodeEmail` -- the
    Get Code BUTTON. The code was then 'typed' into a submit button, which
    does exactly nothing, and the run failed one page later claiming the code
    had expired (2026-09-03)."""
    return page.evaluate(
        """() => {
             const typable = e => ['text', 'tel', 'number', 'search', ''].includes(e.type);
             const els = [...document.querySelectorAll('input')].filter(typable);
             for (const e of els) {
               if (e.readOnly || e.disabled) continue;
               const hay = [e.id, e.name, e.placeholder,
                            e.getAttribute('aria-label') || ''].join(' ').toLowerCase();
               if (/code|otp|verif|token|pin/.test(hay)) return e.id || e.name || '';
             }
             const body = (document.body.innerText || '').toLowerCase();
             if (!/verification|security code|confirmation code|one-time|enter the code/.test(body))
               return null;
             const visible = els.filter(e => !e.readOnly && !e.disabled &&
                                             e.offsetParent !== null);
             return visible.length === 1 ? (visible[0].id || visible[0].name || '') : null;
           }""")


def _choose_email_destination(page, log=print) -> bool:
    """Tick the EMAIL radio, then pick the address. Both, in that order.

    THE RADIO IS NOT AN <input type=radio>. It is a Telerik RadButton toggle
    -- a <span id=...rbEmailRadio> whose real state lives in a hidden
    ClientState blob ('"checked":false', '"autoPostBack":true'). Nothing in a
    normal control dump sees it, which is why three attempts in a row reported
    "no email destination" while looking straight at one.

    Get Code with the radio unticked sends NOTHING and says nothing -- it
    reads as a broken mail filter.

    It has to be email: the other destination is a mobile number an unattended
    run cannot read, and which would text a person at 4am."""
    radio = page.evaluate(
        """() => {
             const els = [...document.querySelectorAll('span,div,label')];
             const e = els.find(x => /emailradio/i.test(x.id || ''))
                    || els.find(x => /rbToggle|RadButton/.test(x.className || '') &&
                                     /^email:?$/i.test((x.innerText || '').trim()));
             if (!e) return '';
             e.click();
             return e.id || 'email-toggle';
           }""")
    if radio:
        log("  ticked the Email radio (%s)" % radio)
        # autoPostBack:true -- the page reloads itself before Get Code means
        # anything, and every element found before this is now stale.
        try:
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1500)

    combo = page.evaluate(
        """() => {
             const els = [...document.querySelectorAll('input')].filter(e => e.type !== 'hidden');
             const e = els.find(x => /email/i.test(x.id || '') || /email/i.test(x.name || ''))
                    || els.find(x => /@/.test(x.value || ''));
             return e ? {id: e.id, value: e.value || ''} : null;
           }""")
    if not combo:
        return bool(radio)
    # LOGGED ON PURPOSE. Which mailbox SaraPlus will send to is the one thing
    # about this wall we cannot know from here, and an unattended run that
    # picks an address nobody reads waits 3 minutes and blames the mail filter.
    log("  email destination on file: %s" % (combo["value"] or "(blank)"))
    try:
        page.click("#%s" % combo["id"])
        page.wait_for_timeout(900)
    except Exception:  # noqa: BLE001
        pass
    picked = page.evaluate(
        """() => {
             const items = document.querySelectorAll('.rcbList li, [class*="rcbItem"]');
             for (const el of items) {
               const t = (el.textContent || '').trim();
               if (/@/.test(t)) { el.click(); return t; }
             }
             return '';
           }""")
    if picked:
        log("  address chosen from the list: %s" % picked)
        page.wait_for_timeout(900)
        return True
    if "@" in (combo["value"] or ""):
        log("  no dropdown list appeared -- using the address already in the box")
        return True
    return bool(radio)


def _request_code(page, log=print) -> bool:
    """Choose EMAIL, then press Get Code.

    The screen is a destination picker -- 'It appears that this is a new
    location or browser for you to login from' -- offering a mobile number and
    an email combo. Pressing Get Code without choosing sends nothing at all,
    silently: that is what the first two attempts did, and it read as a broken
    mail filter rather than an unpicked control."""
    if not _choose_email_destination(page, log=log):
        raise SaraError(
            "SaraPlus wants a confirmation code for this browser but no EMAIL "
            "destination could be found on the picker -- and the only other "
            "option is the mobile number, which an unattended run cannot read "
            "and which would text a person at 4am. Nothing was requested. "
            "Page says: %s" % code_page_text(page))
    clicked = page.evaluate(
        """() => {
             const els = [...document.querySelectorAll(
               'input[type=submit],input[type=button],button,a')];
             // The EMAIL button by id first (MainContent_btnGetCodeEmail on
             // the live page): the screen carries one Get Code per
             // destination, and matching on the visible text alone could
             // press the phone's.
             const want = /get code|send.*code|email.*code|request.*code|resend|send me/i;
             const b = els.find(e => /getcodeemail/i.test(e.id || e.name || ''))
                    || els.find(e => {
                         const t = (e.value || e.innerText || '').trim();
                         return t && t.length < 40 && want.test(t);
                       });
             if (!b) return '';
             b.click();
             return ((b.value || b.innerText || '').trim() + ' [' + (b.id || '?') + ']');
           }""")
    if clicked:
        log("  asked SaraPlus to send the code (%r)" % clicked)
        page.wait_for_timeout(2500)
        return True
    log("  no 'Get Code' button found -- assuming the code was already sent")
    return False


def _submit_code(page, field: str, code: str) -> None:
    """Type the code and press whatever continues. Typed character by
    character like the password: this is the same old ASP.NET form, and it
    drops a value that arrives in one paste-like event."""
    sel = ("#%s" % field) if field else "input[type=text]:visible"
    box = page.locator(sel).first
    box.click()
    if hasattr(box, "press_sequentially"):
        box.press_sequentially(code, delay=50)
    else:
        box.type(code, delay=50)
    try:
        with page.expect_navigation(timeout=NAV_TIMEOUT_MS):
            page.keyboard.press("Enter")
    except Exception:  # noqa: BLE001
        page.wait_for_timeout(2000)


def _verify_browser(page, read_code, attempts: int = 3, log=print) -> None:
    """Clear SaraPlus's "new location or browser" challenge, RETRYING.

    A single pass is not enough, and the reason is worth writing down.
    SaraPlus issued TWO codes one second apart on the first Lucy 2 run
    (13:34:02 and 13:34:03) -- the Email radio's autopostback and the Get Code
    press each reaching the server -- and the page then belonged to one
    request while the newest code answered the other. The run entered a
    perfectly valid code and was told to verify again.

    Racing that perfectly is not worth attempting: notice we are still on the
    passcode page and go round again with a FRESH code. Each attempt
    re-requests and re-finds the box -- the picker and the code box are two
    different pages, so a field id from a previous attempt is stale.

    `read_code(since)` returns the 6 digits; this module deliberately does not
    know which mailbox that is [[module docstring]]."""
    import datetime as _dt
    last_state = ""
    for attempt in range(1, attempts + 1):
        # Stamped BEFORE the request and deliberately a little early: this
        # clock and Gmail's are not identical, and a code discarded for being
        # a second too old looks exactly like a code that never arrived.
        since = _dt.datetime.now().astimezone() - _dt.timedelta(seconds=30)
        if not _request_code(page, log=log):
            log("  nothing to press for a code on attempt %d" % attempt)
        try:
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        except Exception:  # noqa: BLE001
            pass
        # Settle: if SaraPlus sends two, both should be in the inbox before we
        # read it, so a newest-wins reader picks the real newest.
        page.wait_for_timeout(VERIFY_SETTLE_MS)

        field_id = _code_field(page)
        if field_id is None:
            raise SaraError(
                "SaraPlus asked to verify this browser and a code was "
                "requested, but no box to type it into appeared. Page says: "
                "%s | %s" % (code_page_text(page), page_state(page)))
        _submit_code(page, field_id, read_code(since))
        if not _on_passcode_page(page):
            log("  browser verified (attempt %d)" % attempt)
            return
        last_state = page_state(page)
        log("  still on the passcode page after attempt %d -- asking for a "
            "fresh code" % attempt)
    raise SaraError(
        "SaraPlus would not accept a verification code after %d attempts. "
        "Each one was newer than its own request, so this is not a stale-code "
        "problem -- the challenge itself is not clearing. %s"
        % (attempts, last_state))


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
           creds_hint: str = "the saved SaraPlus login",
           read_code=None, log=print) -> str:
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
    # THE BROWSER-VERIFICATION WALL, before any "where are we" judgement: a
    # challenged login is not lost, it is unanswered. Without read_code there
    # is nothing to answer it with, and _security_wall_error says so.
    if _needs_code(page):
        if read_code is None:
            raise _security_wall_error(url, email, creds_hint)
        log("SaraPlus is asking to verify this browser -- clearing it")
        _verify_browser(page, read_code, log=log)
        url = page.url
    # TWO LANDING PAGES: a remembered browser lands on DealerPages/, while a
    # login that has just cleared the challenge lands straight on
    # Reports/ReportingHub.aspx. Splitting on 'DealerPages/' alone called that
    # second one "somewhere unexpected" and threw away a login that had just
    # succeeded (rc_contact_sync, 2026-09-03).
    if "DealerPages/" not in url and "Reports/" in url:
        return url.split("Reports/")[0]
    if SECURITY_PATH in url.lower():
        raise _security_wall_error(url, email, creds_hint)
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

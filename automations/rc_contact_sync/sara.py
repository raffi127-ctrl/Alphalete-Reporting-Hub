"""Read yesterday's B2B orders off SaraPlus Detail Reports.

SOURCE, spelled out:
  ui.saraplus.com (CARLOS's login) -> Analytics -> Reports/ReportingHub.aspx
  -> tab 'Detail Reports' -> sub-tab 'Sales Order History'
  -> Date Range start = end = the ONE day, Customer Type = 'Both', Submit
  -> the grid whose header row carries 'Order ID' + 'Business Name'
  -> columns 'User Name' (the rep) and 'Business Name'
  -> that row's 'View Customer' link -> 'Primary Phone' + the customer's name.

NOTHING IS ADDRESSED BY INDEX. Telerik renders these tabs as anonymous divs
and this grid's column order is not the Order Dashboard's, so tabs are clicked
by visible text and every column is looked up in the header row that same run.
A header we don't recognise raises -- it never falls through to whatever
column happens to sit where 'Business Name' used to be.
[[feedback_no_hardcoded_columns]]

THE DATE PICKERS ARE TELERIK RadDatePicker and fill() does not work on them;
see alphalete_sales_board.sara._set_telerik_date, which is reused here. Their
element ids on THIS tab are discovered at run time rather than hardcoded,
because the two tabs use different control names.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

from automations.alphalete_sales_board.sara import SaraError, _set_telerik_date
from automations.rc_contact_sync import config as C
from automations.rc_contact_sync import verify_code as VC


# --- small helpers ------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def page_state(page) -> str:
    """One line saying where we ACTUALLY are. Every 'selector not found' is
    really 'not on the page you think', and this is what tells them apart."""
    try:
        title = page.title()
    except Exception:                                      # noqa: BLE001
        title = "?"
    marks = []
    for name, needle in (("detail reports tab", C.TAB_DETAIL_REPORTS),
                         ("sales order history tab", C.TAB_SALES_ORDER_HISTORY),
                         ("login form", None)):
        try:
            if needle is None:
                if page.locator("#ctl00_MainContent_txtUserName").count():
                    marks.append(name)
            elif page.locator("text=%s" % needle).count():
                marks.append(name)
        except Exception:                                  # noqa: BLE001
            pass
    return "url=%s | title=%r | found: %s" % (
        page.url, title, ", ".join(marks) or "NONE of the expected landmarks")


# --- the code screen ----------------------------------------------------------
# The page steps live in shared.sara_passcode since 2026-10-29, so the office
# Macs can run the same ones without this module's inbox reader. Same names
# here, so everything below (and every test that patches them) is unchanged.
from automations.shared import sara_passcode as _SP  # noqa: E402
from automations.shared.sara_passcode import (  # noqa: E402,F401
    _on_passcode_page, _settle, _needs_code, _code_field, code_page_text,
    code_page_controls, _choose_email_destination, _submit_code,
)


def _request_code(page, log=print) -> bool:
    """shared.sara_passcode._request_code, raising this module's SaraError."""
    return _SP._request_code(page, log=log, error=SaraError)


def _inbox_name(code_inbox) -> str:
    """The address a code is read from: the caller's inbox= or the
    reporting account verify_code reads by default."""
    return code_inbox[0] if code_inbox else VC._ing.ACCOUNT


def _verify_browser(page, attempts: int = 3, log=print, code_inbox=None) -> None:
    """Clear SaraPlus's "new location or browser" challenge, RETRYING.

    A single pass is not enough, and the reason is worth writing down.
    SaraPlus issued TWO codes one second apart on the first Lucy 2 run
    (13:34:02 and 13:34:03) -- the Email radio's autopostback and the Get
    Code press each reaching the server -- and the page then belonged to one
    request while the newest code answered the other. The run entered a
    perfectly valid code and was told to verify again.

    Racing that perfectly is not worth attempting: the fix is to notice we
    are still on the passcode page and go round again with a FRESH code.
    Each attempt re-requests, waits only for mail newer than that request,
    and re-finds the box -- the picker and the code box are two different
    pages, so a field id from a previous attempt is stale.

    A short settle after Get Code lets a double-issued PAIR both land before
    the inbox is read, so the newest of the two is the one we type."""
    last_state = ""
    for attempt in range(1, attempts + 1):
        # Stamped BEFORE the request and deliberately a little early: this
        # clock and Gmail's are not identical, and a code discarded for being
        # a second too old looks exactly like a code that never arrived.
        since = dt.datetime.now().astimezone() - dt.timedelta(seconds=30)
        _settle(page)
        if not _on_passcode_page(page) and attempt > 1:
            log("  browser verified (attempt %d, page caught up)" % (attempt - 1))
            return
        if not _request_code(page, log=log):
            log("  nothing to press for a code on attempt %d" % attempt)
        try:
            page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
        except Exception:                                  # noqa: BLE001
            pass
        # Settle: if SaraPlus sends two, both should be in the inbox before
        # we read it, so wait_for_code's newest-wins pick is the real newest.
        page.wait_for_timeout(C.VERIFY_SETTLE_MS)

        field_id = _code_field(page)
        if field_id is None:
            raise SaraError(
                "SaraPlus asked to verify this browser and a code was "
                "requested, but no box to type it into appeared. Page says: "
                "%s | %s" % (code_page_text(page), page_state(page)))
        code = VC.wait_for_code(since, timeout_s=C.VERIFY_TIMEOUT_S,
                                poll_s=C.VERIFY_POLL_S, query=C.VERIFY_QUERY,
                                inbox=code_inbox, log=log)
        _submit_code(page, field_id, code)
        # Judged on the URL, not on the page's words: the Reporting Hub we
        # land on afterwards carries enough of the same vocabulary to read as
        # "still being asked" on a login that had in fact just succeeded.
        if not _on_passcode_page(page):
            log("  browser verified (attempt %d)" % attempt)
            return
        last_state = page_state(page)
        log("  still on the passcode page after attempt %d — asking for a "
            "fresh code" % attempt)
    raise SaraError(
        "SaraPlus would not accept a verification code after %d attempts. "
        "Each one was read from %s and was newer than its own request, so "
        "this is not a stale-code problem -- the challenge itself is not "
        "clearing. %s" % (attempts, _inbox_name(code_inbox), last_state))


def login(page, email: str, password: str, log=print, *, code_inbox=None) -> str:
    """Sign in -- password, then the emailed verification code if asked --
    and return the DealerPages base url.

    `code_inbox` is verify_code's inbox= -- (address, app-password file) --
    for a login whose passcode SaraPlus mails somewhere other than the
    reporting inbox. None keeps the default.

    A silent bounce back to the login page is how a whole day of runs reads
    as 'no orders' instead of 'not logged in', so landing anywhere other than
    DealerPages raises."""
    page.goto(C.LOGIN_URL, wait_until="networkidle", timeout=C.NAV_TIMEOUT_MS)
    page.click('a:has-text("LOGIN")')
    page.fill(C.FIELD_USERNAME, email)
    page.wait_for_selector(C.FIELD_PASSWORD, state="visible")
    # Character by character on purpose: this is old ASP.NET and its field
    # handlers drop a value that arrives in one paste-like event.
    page.click(C.FIELD_PASSWORD)
    field = page.locator(C.FIELD_PASSWORD)
    if hasattr(field, "press_sequentially"):
        field.press_sequentially(password, delay=50)
    else:
        field.type(password, delay=50)

    # Stamped BEFORE the click, and deliberately a little early: this clock
    # and Gmail's are not identical, and a code thrown away for being one
    # second too old looks exactly like a code that never arrived.
    since = dt.datetime.now().astimezone() - dt.timedelta(seconds=30)
    try:
        with page.expect_navigation(timeout=C.NAV_TIMEOUT_MS):
            page.click(C.BUTTON_LOGIN)
    except Exception:                                      # noqa: BLE001
        # Some skins do the code step without a full navigation.
        page.wait_for_timeout(2000)

    if _needs_code(page):
        log("  SaraPlus asked to verify this browser — reading %s"
            % _inbox_name(code_inbox))
        log("  code page says: %s" % (code_page_text(page) or "(no text)"))
        _verify_browser(page, log=log, code_inbox=code_inbox)

    url = page.url
    if "login" in url.lower():
        raise SaraError(
            "SaraPlus login failed -- still on the login page after submit. "
            "Check the credentials in %s (a password change is the usual "
            "cause); nothing was written. %s" % (C.CREDS_PATH, page_state(page)))
    # THE DEALER ROOT -- everything up to and including the session segment,
    # e.g. https://www.saraplus.com/e/(S(<session>))/ .
    #
    # TWO LANDING PAGES, because the verification flow does not come back the
    # way an ordinary login does: a remembered browser lands on DealerPages/,
    # while a login that has just cleared the code challenge lands straight on
    # Reports/ReportingHub.aspx. Splitting on 'DealerPages/' alone called that
    # second one "somewhere unexpected" and threw away a login that had just
    # succeeded (2026-09-03).
    for marker in ("DealerPages/", "Reports/"):
        if marker in url:
            return url.split(marker)[0]
    raise SaraError("logged in but landed somewhere unexpected: %s" % url)


def panel_loaded(page) -> bool:
    """Is the Sales Order History panel actually on screen?

    THE HONEST CHECK. The tab's own rtsSelected class said 'Sales Order
    History' the entire time the Sales Dashboard was displayed, because that
    child tab is selected within its level from the start. The multipage
    renders exactly ONE view at a time and swaps it on the server, so the
    panel's presence is the only thing that means what it says."""
    try:
        return bool(page.evaluate(
            "(id) => { const e = document.getElementById(id);"
            "          return !!e && e.offsetParent !== null; }",
            C.PANEL_ORDER_HISTORY))
    except Exception:                                      # noqa: BLE001
        return False


def open_order_history_panel(page, log=print) -> None:
    """Bring up Detail Reports -> Sales Order History.

    BY POSTBACK, NOT BY CLICKING. Every clicking route is closed here:
      * the child tab is not in the DOM until its parent is expanded, and the
        parent's own expansion is client-side only;
      * Telerik's $find and the page's __doPostBack live in the page's world,
        which patchright's evaluate cannot reach;
      * a real mouse click on the parent sets Telerik's 'rtsClicked' class and
        nothing else, so it reads as working while changing nothing.

    So this does what the browser does underneath: sets __EVENTTARGET and
    __EVENTARGUMENT and submits the form. Both values were captured off the
    wire from a human's click (see config). Setting a field is plain DOM work
    and needs none of the page's own scripts.

    Verified by the PANEL, never by the tab's selected class -- that class
    reported 'Sales Order History' the whole time the Sales Dashboard was up."""
    if panel_loaded(page):
        return
    posted = page.evaluate(
        """(cfg) => {
             const t = document.getElementsByName('__EVENTTARGET')[0];
             const a = document.getElementsByName('__EVENTARGUMENT')[0];
             if (!t || !a) return 'no __EVENTTARGET/__EVENTARGUMENT';
             t.value = cfg.target;
             a.value = cfg.arg;
             const f = document.getElementById(cfg.form) || document.forms[0];
             if (!f) return 'no form';
             f.submit();
             return 'posted';
           }""",
        {"target": C.TAB_POSTBACK_TARGET, "arg": C.TAB_POSTBACK_ARG,
         "form": C.FORM_ID})
    if posted != "posted":
        raise SaraError("could not raise the tab postback: %s. %s"
                        % (posted, page_state(page)))
    try:
        page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
    except Exception:                                      # noqa: BLE001
        pass
    page.wait_for_timeout(1500)
    if not panel_loaded(page):
        raise SaraError(
            "the %s panel never appeared after the tab postback (%s arg=%s), "
            "so anything read after this would be a different report. If "
            "SaraPlus has reordered its tabs, that hierarchical index is what "
            "needs re-reading. %s"
            % (C.PANEL_ORDER_HISTORY, C.TAB_POSTBACK_TARGET,
               C.TAB_POSTBACK_ARG, page_state(page)))
    log("  Sales Order History panel loaded")


def _set_customer_type(page, label: str, log=print) -> None:
    """Pick the Customer Type. NOT optional.

    It defaults to 'Residential', so a run that leaves it alone comes back
    with residential orders and no B2B customers at all -- a clean, empty,
    entirely wrong result. Carlos: "for the customer type, we would click on
    both".

    A RadComboBox: click the input, then the item in the list it opens.
    Selecting AUTOPOSTS BACK, so the page is reloading afterwards and every
    element found before it is stale."""
    combo = "#%s_Input" % C.COMBO_CUSTOMER_TYPE
    before = page.evaluate("(s) => { const e = document.querySelector(s);"
                           "         return e ? e.value : null; }", combo)
    if (before or "").strip().lower() == label.lower():
        log("  customer type already %r" % label)
        return
    page.click(combo, timeout=20_000)
    page.wait_for_timeout(800)
    picked = page.evaluate(
        """(want) => {
             const items = document.querySelectorAll('.rcbList li, [class*="rcbItem"]');
             for (const el of items) {
               if ((el.textContent || '').trim().toLowerCase() === want.toLowerCase()) {
                 el.click();
                 return true;
               }
             }
             return false;
           }""", label)
    if not picked:
        raise SaraError(
            "no %r option in the Customer Type list -- leaving it would read "
            "%r orders instead. %s" % (label, before, page_state(page)))
    try:
        page.wait_for_load_state("networkidle", timeout=C.NAV_TIMEOUT_MS)
    except Exception:                                      # noqa: BLE001
        pass
    page.wait_for_timeout(1200)
    after = page.evaluate("(s) => { const e = document.querySelector(s);"
                          "         return e ? e.value : null; }", combo)
    if (after or "").strip().lower() != label.lower():
        raise SaraError(
            "Customer Type still reads %r after picking %r; the report would "
            "cover the wrong customers. %s" % (after, label, page_state(page)))
    log("  customer type: %s" % after)


def _submit(page, log=print) -> None:
    """Run the report and WAIT FOR THE GRID, not for a fixed pause.

    Submit fires an ASYNC postback, so networkidle can come back before the
    146-column grid has rendered -- a fixed wait then reads a page that has
    no grid on it yet and reports the report as empty."""
    page.click(C.SUBMIT, timeout=30_000)
    try:
        page.wait_for_load_state("networkidle", timeout=C.GRID_TIMEOUT_MS)
    except Exception:                                      # noqa: BLE001
        pass
    try:
        page.wait_for_selector("#%s" % C.GRID_DATA, timeout=C.GRID_TIMEOUT_MS)
    except Exception:                                      # noqa: BLE001
        # Not fatal here: read_grid says what is actually on the page, which
        # is a better error than a selector timeout.
        log("  (the grid did not appear within %ds)" % (C.GRID_TIMEOUT_MS / 1000))
    page.wait_for_timeout(800)


def read_grid(page) -> List[Dict[str, str]]:
    """Every data row of the Sales Order History grid, keyed BY HEADER LABEL.

    RadGrid renders the header and the rows as TWO tables -- reading 'the
    table whose first row holds the headers' finds the header table, which
    has no data in it. Header comes from _Header, rows from the grid proper.

    All 146 columns are in the DOM whatever the Report View is set to, so the
    phone is read straight off the row: no 'View Customer' page load per
    customer, which is what the Loom had to do by hand."""
    raw = page.evaluate(
        """(ids) => {
             const hdr = document.getElementById(ids.header);
             const data = document.getElementById(ids.data);
             if (!hdr || !data) return {headers: [], rows: [],
                                        missing: (!hdr ? 'header ' : '') + (!data ? 'data' : '')};
             const headRow = hdr.querySelector('tr');
             const headers = headRow
               ? [...headRow.querySelectorAll('th,td')]
                   .map(c => (c.innerText || '').replace(/[ \\t\\n\\r]+/g, ' ').trim())
               : [];
             const rows = [...data.querySelectorAll('tbody > tr')]
               .map(r => [...r.querySelectorAll('td')]
                 .map(c => (c.innerText || '').replace(/[ \\t\\n\\r]+/g, ' ').trim()));
             return {headers: headers, rows: rows, missing: ''};
           }""", {"header": C.GRID_HEADER, "data": C.GRID_DATA})
    if raw.get("missing"):
        present = page.evaluate(
            """() => [...document.querySelectorAll('table[id], div[id]')]
                 .map(e => e.id)
                 .filter(id => /rg|grid|OrderHistory/i.test(id))
                 .slice(0, 12)""")
        raise SaraError(
            "the Sales Order History grid is not on the page (%s table "
            "missing). Grid-ish ids that ARE present: %s. %s"
            % (raw["missing"].strip(), present or "none", page_state(page)))
    try:
        return parse_grid(raw["headers"], raw["rows"])
    except SaraError as e:
        raise SaraError("%s %s" % (e, page_state(page)))


def parse_grid(headers: List[str], rows: List[List[str]]) -> List[Dict[str, str]]:
    """The pure half of read_grid: map columns by LABEL.

    Split out from the browser so the part that decides which text is a rep
    and which is a business can be tested without a login, and so a SaraPlus
    column move is caught by a name lookup rather than shifting every value
    one to the left. [[feedback_no_hardcoded_columns]]"""
    heads = [_norm(h) for h in headers]
    idx = {}
    for want in C.REQUIRED_COLUMNS:
        if want not in heads:
            raise SaraError(
                "the grid has no %r column. Columns seen: %s."
                % (want, ", ".join(h for h in heads if h)[:400]))
        idx[want] = heads.index(want)
    out: List[Dict[str, str]] = []
    for cells in rows:
        if not cells:
            continue                       # spacer / pager row
        row = {c: (cells[i] if i < len(cells) else "") for c, i in idx.items()}
        if not row.get(C.COL_ORDER_ID):
            continue                       # grouping or footer row
        out.append(row)
    return out


def open_report(page, base_url: str, day: dt.date, log=print) -> None:
    """Open Sales Order History for ONE day, Customer Type Both, and submit."""
    page.goto(base_url + C.HUB_PATH, wait_until="networkidle",
              timeout=C.NAV_TIMEOUT_MS)
    if "404" in (page.title() or "") or "404.aspx" in page.url:
        raise SaraError(
            "%s is a 404 for this dealer (landed on %s). The Reporting Hub "
            "sits BESIDE DealerPages/, not inside it."
            % (base_url + C.HUB_PATH, page.url))
    open_order_history_panel(page, log=log)

    # Carlos's Loom: the range is the ONE day, start AND end. The pickers are
    # RadDatePickers and fill() does not work on them -- _set_telerik_date
    # writes the four pieces the control actually reads.
    _set_telerik_date(page, C.FIELD_START, day)
    _set_telerik_date(page, C.FIELD_END, day)
    log("  date range %s -> %s" % (day, day))

    _set_customer_type(page, C.CUSTOMER_TYPE_BOTH, log=log)
    # Customer Type autoposts back, which re-renders the panel and can reset
    # the dates -- so they are written again, after it, not before.
    _set_telerik_date(page, C.FIELD_START, day)
    _set_telerik_date(page, C.FIELD_END, day)
    _submit(page, log=log)


def scrape(day: Optional[dt.date] = None, *, headless: bool = True,
           limit: Optional[int] = None, log=print) -> List[Dict[str, str]]:
    """One day's orders with the rep, the business, the customer and the phone.

    [{'order_id', 'day', 'order_date', 'rep', 'business', 'customer_name',
      'phone'}]

    ONE page load for the whole day. The Loom opened each row's 'View
    Customer' card to read the phone; every column is in the grid's DOM
    regardless of the Report View, so the phone comes off the row itself."""
    from patchright.sync_api import sync_playwright

    day = day or C.yesterday()
    cr = C.creds()
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    out: List[Dict[str, str]] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                base = login(page, cr["email"], cr["password"], log=log)
            except SaraError as e:
                raise SaraError(
                    "%s (credentials read from %s -- this report uses CARLOS's "
                    "SaraPlus login, not the sales board's)"
                    % (e, C.CREDS_PATH))
            log("logged in as %s: %s" % (cr["email"], base))

            open_report(page, base, day, log=log)
            rows = read_grid(page)
            log("Sales Order History %s: %d order(s)" % (day, len(rows)))
            if limit:
                rows = rows[:limit]
                log("  --limit %d: only the first %d" % (limit, len(rows)))

            for r in rows:
                out.append({
                    "order_id": r[C.COL_ORDER_ID],
                    "day": day.isoformat(),
                    "order_date": r.get(C.COL_ORDER_DATE, ""),
                    "rep": _norm(r[C.COL_REP]),
                    "business": _norm(r[C.COL_BUSINESS]),
                    "customer_name": _norm(r[C.COL_CUSTOMER]),
                    "phone": _norm(r[C.COL_PHONE]),
                })
                log("  %-14s %-26s %-24s %s"
                    % (r[C.COL_ORDER_ID], (r[C.COL_BUSINESS] or "(no business)")[:26],
                       r[C.COL_CUSTOMER][:24], r[C.COL_PHONE] or "NO PHONE"))
        finally:
            ctx.close()
    return out


def probe(day: Optional[dt.date] = None, *, headless: bool = True,
          log=print) -> Dict:
    """READ-ONLY: log in, open the report, and say what is ACTUALLY there.
    Run this first on a new machine, before trusting a single contact."""
    from patchright.sync_api import sync_playwright

    day = day or C.yesterday()
    cr = C.creds()
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    info: Dict = {"day": day.isoformat(), "login": cr["email"]}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            info["base"] = login(page, cr["email"], cr["password"], log=log)
            try:
                open_report(page, info["base"], day, log=log)
                info["panel"] = panel_loaded(page)
                rows = read_grid(page)
                info["rows"] = len(rows)
                info["sample"] = [
                    {k: r.get(k, "") for k in
                     (C.COL_ORDER_ID, C.COL_REP, C.COL_BUSINESS,
                      C.COL_CUSTOMER, C.COL_PHONE)}
                    for r in rows[:3]]
            except SaraError as e:
                info["error"] = str(e)
        finally:
            ctx.close()
    for k, v in info.items():
        log("%s: %s" % (k, v))
    return info

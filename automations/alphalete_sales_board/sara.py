"""Log into SaraPlus and read the day's ReportingHub grids.

THREE PASSES, because no single service filter carries all four measures:

  1. 'AT&T'          -> Internet Sales / Internet Upgrades / AIA / Wireless Lines
  2. 'All'           -> DTV Streaming   (the AT&T-filtered grid always says 0)
  3. 'AT&T Internet' -> Records, i.e. credit checks -- one step BEFORE a
                        confirmed sale. Never written to the board; it only
                        feeds the Slack heads-up.

SOURCE, spelled out: ui.saraplus.com -> DealerPages/Reports/ReportingHub.aspx
-> Order Dashboard, date range set to the ONE day, Service = the filter above,
-> the RadGrid named in GRID_* below -> the columns in COL_*.

THE DATE PICKERS ARE TELERIK RadDatePicker AND fill() DOES NOT WORK on them.
A RadDatePicker is four DOM elements that have to agree -- the raw input, the
display input, a ClientState JSON blob and the calendar's own JSON range -- and
the control reads the blob, not the box. Typing into the visible field leaves
the blob saying yesterday, so the grid comes back for the wrong day with no
error anywhere. _set_telerik_date writes all four. This is not a workaround to
be tidied up later; it is how the control works.

COLUMN INDICES were confirmed against the live grids on 2026-07-09 and are
0-based. They are the one thing here that a SaraPlus redesign would silently
rot -- _row_values() therefore refuses a grid whose row-type column does not
hold the expected marker, rather than reading sales out of whatever column
happens to sit at index 9.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.alphalete_sales_board import config as C

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


class SaraError(RuntimeError):
    pass


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
def _login(page, email: str, password: str) -> str:
    """Sign in and return the DealerPages base url. Raises if we land back on
    the login page -- a silent bounce there is how a whole day of sweeps can
    read as 'no sales' instead of 'not logged in'."""
    page.goto(C.LOGIN_URL, wait_until="networkidle")
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
            "cause); nothing was written." % C.CREDS_PATH)
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


def _run_report(page, base_url: str, day: dt.date, service: str,
                grid: str) -> List[List[str]]:
    """Set the day + service, submit, and return the grid's rows as cell text."""
    page.goto(base_url + HUB_PATH, wait_until="networkidle")
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


# --- the one public entry point ---------------------------------------------
def scrape(day: Optional[dt.date] = None, *, headless: bool = True,
           log=print) -> Dict:
    """{'agents': [...], 'records': {...}} for ONE day."""
    from patchright.sync_api import sync_playwright

    day = day or dt.date.today()
    cr = C.creds()
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = _login(page, cr["email"], cr["password"])
            log("logged in: %s" % base)

            att = parse_att(_run_report(page, base, day, "AT&T", GRID_ATT))
            log("AT&T pass: %d reps" % len(att))

            dtv = parse_dtv(_run_report(page, base, day, "All", GRID_ALL))
            log("All pass: DTV for %d reps" % len(dtv))

            records = parse_records(
                _run_report(page, base, day, "AT&T Internet", GRID_INTERNET))
            log("AT&T Internet pass: records for %d reps" % len(records))
        finally:
            ctx.close()

    return {"agents": merge_dtv(att, dtv), "records": records, "day": day}


def probe(*, headless: bool = True, log=print) -> Dict:
    """READ-ONLY: log in, open the ReportingHub, and report what is ACTUALLY
    there -- the landing url, the page title, which expected landmarks exist,
    and every id/name that looks like a Telerik combo or grid.

    Exists because a bare 'waiting for locator(...)' says only that something
    is missing, never what is present instead, and the answer is usually that
    login landed somewhere else entirely (a dealer picker, a T&C page, a
    session bounce). Clicks nothing, submits nothing, writes nothing.
    """
    from patchright.sync_api import sync_playwright

    cr = C.creds()
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(C.PROFILE_DIR), headless=headless, args=["--disable-sync"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            base = _login(page, cr["email"], cr["password"])
            out["base_url"] = base
            log("LOGIN OK -> %s" % base)
            log("after login: %s" % page_state(page))

            # What can this login actually REACH? Dumped from the landing page,
            # because "the hub 404s" and "this account has no reporting module"
            # look identical from the hub's side and need opposite fixes.
            # EVERY link, unfiltered. The first version of this kept only
            # hrefs containing ".aspx" and then grepped them for "report" --
            # and reported "NONE", which I read as "this login has no
            # reporting". It has: the menu is called ANALYTICS (Megan's
            # screenshot, 2026-08-26). A keyword search only ever finds the
            # word you guessed. Dump the nav and read it.
            links = page.evaluate(
                r"""() => Array.from(document.querySelectorAll('a'))
                       .map(a => ({
                              text: (a.textContent || '').trim().replace(/\s+/g, ' '),
                              href: a.getAttribute('href') || '',
                              onclick: (a.getAttribute('onclick') || '').slice(0, 120)}))
                       .filter(o => o.text || o.href)""")
            out["links"] = links
            log("--- %d links on the landing page (ALL of them) ---" % len(links))
            for o in links[:60]:
                log("   %-28s -> %s%s" % (o["text"][:28], o["href"][:90],
                                          ("  onclick=" + o["onclick"]) if o["onclick"] else ""))

            page.goto(base + HUB_PATH, wait_until="networkidle")
            page.wait_for_timeout(3000)
            out["hub_state"] = page_state(page)
            log("ReportingHub: %s" % out["hub_state"])

            controls = page.evaluate(
                """() => {
                     const out = {combos: [], grids: [], dates: [], buttons: []};
                     for (const el of document.querySelectorAll('[id]')) {
                       const id = el.id;
                       if (/rcb.*Input$/i.test(id)) out.combos.push(id);
                       else if (/^ctl00.*rg[A-Za-z_]*_ctl00$/.test(id)) out.grids.push(id);
                       else if (/rdp.*Date$/i.test(id)) out.dates.push(id);
                       else if (/btn|Submit/i.test(id) && el.tagName !== 'DIV') out.buttons.push(id);
                     }
                     out.title = document.title;
                     out.frames = document.querySelectorAll('iframe').length;
                     return out;
                   }""")
            out["controls"] = controls
            for key in ("combos", "dates", "grids", "buttons"):
                vals = controls.get(key) or []
                log("%-8s %d: %s" % (key, len(vals), ", ".join(vals[:8]) or "(none)"))
            log("iframes on page: %s" % controls.get("frames"))
            if controls.get("frames"):
                log("NOTE: the dashboard may live inside an IFRAME -- our "
                    "selectors run against the top document only.")
        finally:
            ctx.close()
    return out

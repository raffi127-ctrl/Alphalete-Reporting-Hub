"""Playwright driver for ApplicantStream.

WHY PLAYWRIGHT: ApplicantStream is a private site behind Cloudflare with no
public API, so Python has to drive a real browser.

STRUCTURE CONFIRMED FROM THE LIVE SITE (2026-07-21):
  * ColdFusion app. Every page is a URL:
        https://applicantstream.com/index.cfm?rqst=<TOKEN>&p=<PAGE>
    <TOKEN> is a per-session id in every link; we capture it once after login.
  * Page numbers:  Calendar 102 | Call List 501 | Retention Details 701
  * Office picker = jQuery UI autocomplete input #searchMC. Typing an office id
    shows a .ui-autocomplete dropdown whose item reads:
        "<officeId>\n<Owner Name>\n<Company>"   e.g. "11280 / Rafael Hidalgo /
    ALPHALETE MARKETING, INC." -- so we also read the OWNER NAME from it.
  * On the Retention Details report (p=701, weekly grid), each numeric cell is a
    link to a detail page:
        index.cfm?p=715&rqst=<TOKEN>&count=<n>&dt=<serial>&accId=<officeInternalId>
                 &id=<Row_Id>&...
    Row ids seen: "Sent_to_Call_List", "Total_Second_Interviews".
    So we don't fight a modal -- we grab the cell's <a href> and navigate to it.
  * The detail page (p=715) is a plain table:
        col 0 = row number, then the data columns, then a trailing action col.
        "Sent to Call List"        data cols: First Name, Last Name, Email,
                                   Phone, Job Board, Date and Time, Ad  (7)
        "Total Second Interviews"  data cols: First Name, Last Name, Email,
                                   Phone, Done By 1st, Done By 2nd, Job Board,
                                   Date and Time, Ad  (9)
    Detail header text: "For Date: <Weekday>, <Mon d, yyyy> | Total Apps: <n>".
    "Export to CSV" button = #btnCSV_popup (client-side download).

STILL VERIFY (Calendar workflows only): the calendar day-view (p=102) is an
interactive grid with per-applicant dropdowns (Offer Position / Done By /
Follow Up) and an Action column showing e.g. "Brought on Board (Jul 27)".
Reading those statuses is marked `# >>> VERIFY` in confirm_first_day.py /
update_second_round.py.

CLOUDFLARE / SESSION: persistent context in USER_DATA_DIR. First run headed
(HEADLESS=0) you clear Cloudflare + log in once; the session is reused after.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt
import re
from contextlib import contextmanager
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from . import config
from . import sheets

BASE = "https://applicantstream.com/index.cfm"
PAGES = {"calendar": 102, "call_list": 501, "retention_details": 701}


class ApplicantStream:
    def __init__(self, headless: bool | None = None):
        self.headless = config.HEADLESS if headless is None else headless
        self._pw = None
        self.ctx = None
        self.page = None
        self.token = None            # per-session 'rqst' id
        self.current_owner = None    # owner name of the last-selected office

    # ---- lifecycle -------------------------------------------------------
    def start(self):
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=config.USER_DATA_DIR,
            headless=self.headless,
            viewport={"width": 1600, "height": 950},
            accept_downloads=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def close(self):
        if self.ctx:
            self.ctx.close()
        if self._pw:
            self._pw.stop()

    # ---- auth ------------------------------------------------------------
    # Two-step ownerville login form (ApplicantStream shares the ownerville
    # login). Selectors mirror the proven, in-production
    # automations.shared.tableau_patchright._drive_login_form — the original
    # get_by_label("Username")/single-page "Log in" guesses were wrong for this
    # username→NEXT→password→submit flow, which is why the first headless login
    # failed with "Could not find session token".
    _USER_SEL = ('input[type="email"], input[name="username"], '
                 'input[name="email"], input[type="text"]')
    _PASS_SEL = 'input[type="password"]'
    _NEXT_NAME = re.compile(r"^\s*next\s*$", re.I)
    _SUBMIT_NAME = re.compile(r"sign\s*in|log\s*in|submit|continue|enter", re.I)

    def login(self):
        # Go to the app (index.cfm). Authenticated → it serves the app with rqst
        # links; unauthenticated → it serves the ownerville login form.
        self.page.goto(BASE, wait_until="domcontentloaded")
        self._wait_for_cloudflare()

        already = ("rqst=" in (self.page.url or "")
                   or self.page.get_by_role(
                       "link", name=re.compile("log ?out", re.I)).count() > 0)
        if not already:
            username, password = sheets.read_as_credentials()  # README B1/B2
            try:
                self.page.wait_for_selector(self._USER_SEL, timeout=15000)
                self.page.fill(self._USER_SEL, username)
                self.page.get_by_role("button", name=self._NEXT_NAME).first.click()
                self.page.wait_for_selector(self._PASS_SEL, timeout=60000)
                self._wait_for_cloudflare()
                self.page.wait_for_timeout(1500)
                self.page.fill(self._PASS_SEL, password)
                self.page.wait_for_timeout(1500)
                # Submit fires a Cloudflare→SSO redirect chain that can outlast
                # Playwright's post-click nav auto-wait; no_wait_after skips it,
                # the explicit waits below settle it.
                try:
                    self.page.get_by_role(
                        "button", name=self._SUBMIT_NAME).first.click(
                            no_wait_after=True)
                except PWTimeout:
                    pass
                self.page.wait_for_load_state("domcontentloaded")
                self.page.wait_for_timeout(5000)
                self._wait_for_cloudflare()
            except PWTimeout:
                pass
        self._capture_token()

    def _capture_token(self):
        href = self.page.evaluate(
            "() => (document.querySelector('a[href*=\"rqst=\"]')||{}).href || location.href"
        )
        m = re.search(r"rqst=([A-F0-9-]+)", href, re.I)
        if not m:
            raise RuntimeError("Could not find session token (rqst=...). Are we logged in?")
        self.token = m.group(1)

    def _wait_for_cloudflare(self, timeout_ms: int = 45000):
        try:
            self.page.wait_for_function(
                "!document.title.toLowerCase().includes('just a moment')", timeout=timeout_ms
            )
        except PWTimeout:
            pass

    # ---- navigation ------------------------------------------------------
    def goto_page(self, page_num: int):
        self.page.goto(f"{BASE}?rqst={self.token}&p={page_num}", wait_until="networkidle")

    def select_office(self, office_id: str, attempts: int = 3) -> str:
        """Select an office in #searchMC, retrying transient timeouts. Under
        browser-resource contention (several headless reports at once) the
        picker's click actionability check can hit the 30s timeout — a full
        17-office run saw many of these mid-day. Retry from a clean report page
        so one slow click doesn't drop the whole office. Returns the owner name."""
        last = None
        for i in range(max(1, attempts)):
            try:
                return self._select_office_once(office_id)
            except PWTimeout as e:
                last = e
                print(f"  ~ [{office_id}] select timeout, retry {i + 1}/{attempts}",
                      flush=True)
                try:
                    self.open_retention_details()  # reset to a page with #searchMC
                except Exception:  # noqa: BLE001
                    pass
                self.page.wait_for_timeout(1500)
        raise last  # exhausted retries — the caller's per-office guard logs + skips

    def _select_office_once(self, office_id: str) -> str:
        box = self.page.locator("#searchMC")
        box.click()
        box.fill("")
        box.type(str(office_id), delay=60)  # real keystrokes drive jQuery UI
        item = self.page.locator("ul.ui-autocomplete li", has_text=str(office_id)).first
        item.wait_for(timeout=10000)
        # item text is "<id>\n<owner>\n<company>" -- second line is the owner
        parts = [p.strip() for p in item.inner_text().split("\n") if p.strip()]
        self.current_owner = parts[1] if len(parts) >= 2 else str(office_id)
        item.click()
        self.page.wait_for_load_state("networkidle")
        return self.current_owner

    def open_retention_details(self):
        self.goto_page(PAGES["retention_details"])

    def open_calendar(self):
        self.goto_page(PAGES["calendar"])

    # ---- retention report -> detail page --------------------------------
    def open_detail_page(self, row_label: str, date_header: str):
        """On the retention report (p=701), find the cell where `row_label` meets
        the column whose header contains `date_header` (e.g. 'Jul 21, 2026'),
        read its link, and navigate to that detail page (p=715).

        Returns True if opened, False if the number was 0 / no link (nothing to do)."""
        href = self.page.evaluate(
            """([label, dateStr]) => {
                const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
                const trs = [...document.querySelectorAll('tr')];
                // locate the date column index from the header row
                const headerCells = [...document.querySelectorAll('tr')]
                    .map(tr => [...tr.children])
                    .find(cells => cells.some(c => norm(c.innerText).includes(norm(dateStr))));
                if (!headerCells) return null;
                let col = headerCells.findIndex(c => norm(c.innerText).includes(norm(dateStr)));
                // find the data row by its first-cell label
                const row = trs.find(tr => {
                    const f = tr.querySelector('td,th');
                    return f && norm(f.innerText).startsWith(norm(label));
                });
                if (!row) return null;
                const a = row.children[col] && row.children[col].querySelector('a');
                return a ? a.getAttribute('href') : null;
            }""",
            [row_label, date_header],
        )
        if not href:
            return False
        if not href.startswith("http"):
            href = "https://applicantstream.com/" + href.lstrip("/")
        self.page.goto(href, wait_until="networkidle")
        return True

    def scrape_detail_table(self, n_data_cols: int) -> list[list[str]]:
        """Scrape the p=715 detail table: skip col 0 (row number) and the trailing
        action col, returning the `n_data_cols` data columns for every row."""
        return self.page.evaluate(
            """(nCols) => {
                const tables = [...document.querySelectorAll('table')];
                let best=null, n=0;
                tables.forEach(t => { const r=t.querySelectorAll('tr').length; if(r>n){n=r;best=t;} });
                if (!best) return [];
                const rows = [...best.querySelectorAll('tr')];
                const out = [];
                for (let i=1; i<rows.length; i++) {           // skip header row
                    const tds = [...rows[i].querySelectorAll('td')];
                    if (!tds.length) continue;
                    const data = tds.slice(1, 1+nCols).map(td => td.innerText.trim());
                    if (data.some(x => x)) out.push(data);
                }
                return out;
            }""",
            n_data_cols,
        )

    def export_detail_csv(self, download_dir: str = "downloads") -> str:
        """Click #btnCSV_popup on the detail page and save the download."""
        import os
        os.makedirs(download_dir, exist_ok=True)
        with self.page.expect_download() as dl:
            self.page.locator("#btnCSV_popup").click()
        download = dl.value
        path = os.path.join(download_dir, download.suggested_filename)
        download.save_as(path)
        return path

    # ---- detail-list helpers (for status cross-referencing) --------------
    def detail_href(self, row_label: str, date_header: str) -> str | None:
        """On the retention report, return the detail-page href for the cell where
        `row_label` meets the `date_header` column (or None if the number is 0)."""
        return self.page.evaluate(
            """([label, dateStr]) => {
                const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
                const trs = [...document.querySelectorAll('tr')];
                const headerCells = trs.map(tr => [...tr.children])
                    .find(cells => cells.some(c => norm(c.innerText).includes(norm(dateStr))));
                if (!headerCells) return null;
                const col = headerCells.findIndex(c => norm(c.innerText).includes(norm(dateStr)));
                const row = trs.find(tr => {
                    const f = tr.querySelector('td,th');
                    return f && norm(f.innerText).startsWith(norm(label));
                });
                if (!row) return null;
                const a = row.children[col] && row.children[col].querySelector('a');
                return a ? a.getAttribute('href') : null;
            }""",
            [row_label, date_header],
        )

    def detail_names_for(self, row_label: str, date_header: str) -> set[str]:
        """Load the detail page for (row_label, date) and return a set of the
        applicants' full names ("First Last"). Empty set if there's no link.
        NOTE: navigates away from the report -- reload it before the next call,
        or gather all hrefs first with detail_href()."""
        href = self.detail_href(row_label, date_header)
        if not href:
            return set()
        if not href.startswith("http"):
            href = "https://applicantstream.com/" + href.lstrip("/")
        self.page.goto(href, wait_until="networkidle")
        rows = self.scrape_detail_table(2)  # first two data cols = First, Last
        return {f"{r[0]} {r[1]}".strip() for r in rows if len(r) >= 2}

    def scrape_at(self, href: str, n_data_cols: int) -> list[list[str]]:
        """Navigate to an already-collected detail href and scrape its table.
        Lets a caller gather ALL of an office's detail hrefs from ONE loaded
        retention report (detail_href doesn't navigate), then visit each — far
        fewer page loads than reloading the report before every metric."""
        if not href:
            return []
        if not href.startswith("http"):
            href = "https://applicantstream.com/" + href.lstrip("/")
        self.page.goto(href, wait_until="networkidle")
        return self.scrape_detail_table(n_data_cols)

    def names_at(self, href: str) -> set[str]:
        """Full names ('First Last') from an already-collected detail href."""
        rows = self.scrape_at(href, 2)  # first two data cols = First, Last
        return {f"{r[0]} {r[1]}".strip() for r in rows if len(r) >= 2}

    # ---- calendar helpers ------------------------------------------------
    def open_calendar_for(self, date: dt.date):
        """Open the calendar day view for a specific date (uses the page's own
        cal.navigate() since the date is not a plain URL param)."""
        self.open_calendar()
        self.page.evaluate(
            """(mmddyyyy) => {
                const $ = window.jQuery;
                if ($) $("#topLevelDatePicker").val(mmddyyyy);
                if (window.cal) { cal.currentDate = mmddyyyy; cal.currentDateLocale = mmddyyyy; cal.navigate(); }
            }""",
            date.strftime("%m/%d/%Y"),
        )
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1200)  # cal.navigate re-renders async

    def scrape_calendar_bob_dates(self) -> dict[str, str]:
        """From the currently-shown calendar day, return {full_name: bob_date_str}
        for every applicant whose row shows 'Brought on Board (<date>)'."""
        pairs = self.page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('tr').forEach(tr => {
                    const m = (tr.innerText||'').match(/Brought on Board\\s*\\(([^)]+)\\)/i);
                    if (!m) return;
                    let name = '';
                    for (const td of tr.children) {
                        const t = td.innerText || '';
                        if (/Phone:/i.test(t)) { name = t.split('\\n').map(s=>s.trim()).filter(Boolean)[0]; break; }
                    }
                    if (name) out.push([name, m[1].trim()]);
                });
                return out;
            }"""
        )
        return {name.strip().lower(): date for name, date in pairs}


@contextmanager
def session(headless: bool | None = None):
    app = ApplicantStream(headless=headless)
    try:
        app.start()
        app.login()
        yield app
    finally:
        app.close()


if __name__ == "__main__":
    # One-time HEADED login. Open the site and let a human clear Cloudflare +
    # sign in, THEN capture the token. We pause BEFORE capturing so a fresh
    # profile (no saved session yet) doesn't crash on the missing token — the
    # old code called login() -> _capture_token() up front, which raised and
    # exited before the human ever saw the page. The session is saved to the
    # persistent profile either way once you've logged in.
    app = ApplicantStream(headless=False).start()
    app.page.goto(config.AS_URL, wait_until="domcontentloaded")
    app._wait_for_cloudflare()
    print("Log in if prompted (creds are in the tracker sheet's README tab, "
          "B1/B2). When you're logged in, close the Playwright Inspector to save "
          "the session.")
    app.page.pause()
    try:
        app._capture_token()
        print(f"Logged in. Session token = {app.token}")
    except Exception as e:  # noqa: BLE001
        print(f"(couldn't read a session token: {e}. If you logged in, the "
              "session is still saved to the profile and reports will reuse it.)")
    app.close()

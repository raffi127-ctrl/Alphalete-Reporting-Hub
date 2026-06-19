"""Sara Plus (saraplus.com) Sales Dashboard pull for the B2B WE sales board.

Logs in with the trusted persistent profile (carhi1816 — Carlos Hidalgo's B2B
team), opens Analytics → Sales Dashboard, sets the Date Range to a single day,
submits, and scrapes the 'Agent' group of the result grid.

The result grid is a Telerik RadGrid grouped Company → Location → Reports To →
Campaign → Agent → History. Every data row's FIRST cell is a group key like
'5_Agent' / '6_History' / '1_Company'. We keep only rows whose key ends in
'_Agent' — that is exactly the per-agent breakdown ('Total - Agent') and it
excludes the rollup rows (incl. 'Carlos Hidalgo' as the Reports-To owner) and
the History date rows. Columns are read by HEADER LABEL, never by position
([[feedback_no_hardcoded_columns]]).

DEVICE TRUST: a fresh browser profile triggers Sara Plus's "new location" OTP
(email/SMS). The persistent profile is trusted once by a human (see
_bootstrap_otp.py); after that, login skips the code. If the OTP page appears,
we RAISE loudly rather than hang — a human must re-bootstrap the profile.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, Optional

from automations.shared.tableau_patchright import _launch_persistent
from automations.shared import creds

HERE = Path(__file__).resolve().parent
PROFILE = HERE / ".saraplus_profile"
LOGIN_URL = "https://www.saraplus.com/e/servicepages/login.aspx"
GRID = "#ctl00_MainContent_rgOrderDashboard"

# Sara Plus measure-column labels we care about (others ignored).
COL_NL = "Wireless New Lines"
COL_INT = "AT&T Internet"
COL_VOICE = "Total Voice"
COL_TOTAL = "Total Sales"


class OTPRequired(RuntimeError):
    """Sara Plus is asking for a device-verification code — the profile is no
    longer trusted. A human must re-run _bootstrap_otp.py on this machine."""


def _fmt(d: dt.date) -> str:
    # Sara's dateInput wants M/D/YYYY (no zero-pad); cross-platform safe.
    return f"{d.month}/{d.day}/{d.year}"


def _login(page, allow_human_otp: bool = False, otp_wait_min: float = 8.0,
           logfn=print) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    if page.query_selector("#ctl00_MainContent_txtUserName"):
        page.fill("#ctl00_MainContent_txtUserName", creds.saraplus_username())
        page.fill("#ctl00_MainContent_txtPassword", creds.saraplus_password())
        page.click("#MainContent_btnLogin")
        page.wait_for_load_state("networkidle", timeout=45000)
    if "verifypasscode" not in page.url.lower():
        return
    # Device-verification (OTP) page. Sara's trust is fingerprint + short-lived
    # cookie, so this recurs; headless never passes it.
    if not allow_human_otp:
        raise OTPRequired(
            "Sara Plus requested a device-verification code (new location/browser). "
            "Run headed with human OTP allowed, or bootstrap the profile: "
            "`python -m automations.b2b_sales_board._bootstrap_otp`.")
    logfn("  *** Sara Plus needs a verification code. In the browser window: pick "
          "Email/Mobile, Get Code, type it, submit. Waiting up to "
          f"{otp_wait_min:g} min… ***")
    import time
    for i in range(int(otp_wait_min * 20)):  # poll every 3s
        if "verifypasscode" not in page.url.lower():
            logfn("  OTP cleared — continuing.")
            return
        if i % 5 == 0:  # nudge the window to the foreground periodically
            try:
                page.bring_to_front()
            except Exception:
                pass
        time.sleep(3)
    raise OTPRequired("Timed out waiting for the human to clear the Sara Plus OTP.")


def _open_dashboard(page) -> None:
    m = re.match(r"(https://www\.saraplus\.com/e/\(S\([^)]+\)\)/)", page.url)
    if not m:
        raise RuntimeError(f"Could not derive Sara Plus session base from {page.url!r}")
    page.goto(m.group(1) + "Reports/ReportingHub.aspx",
              wait_until="networkidle", timeout=45000)
    # Make sure the Sales Dashboard form actually rendered before we drive it.
    page.wait_for_selector("#ctl00_MainContent_rdpOrderDashStartDate_dateInput",
                           state="visible", timeout=30000)
    page.wait_for_timeout(800)


def _agent_signature(page):
    """(agent row count, first agent name) — used to detect when an AJAX submit
    has actually replaced the grid (vs. showing stale data under the overlay)."""
    rows = [c for c in _grid_rows(page) if _is_agent_row(c)]
    return (len(rows), rows[0][2] if rows else "")


def _set_range_and_submit(page, start: dt.date, end: dt.date) -> None:
    before = _agent_signature(page)
    for did, d in (("ctl00_MainContent_rdpOrderDashStartDate_dateInput", start),
                   ("ctl00_MainContent_rdpOrderDashEndDate_dateInput", end)):
        page.fill(f"#{did}", _fmt(d))
        page.eval_on_selector(
            f"#{did}", "e => { e.dispatchEvent(new Event('change',{bubbles:true})); e.blur&&e.blur(); }")
    page.click("#MainContent_rbOrderDashSubmit")
    page.wait_for_load_state("networkidle", timeout=60000)
    # The AJAX postback shows a LOADING overlay over the STALE previous grid, so
    # we wait for the agent signature to (a) differ from before the submit and
    # (b) hold steady across two polls — i.e. the new data has rendered.
    last = None
    for _ in range(90):
        try:
            sig = _agent_signature(page)
            if sig[0] > 0 and sig != before and sig == last:
                break
            last = sig
        except Exception:
            last = None
        page.wait_for_timeout(1000)
    page.wait_for_timeout(400)
    if _count_agent_rows(page) == 0:
        try:
            from pathlib import Path as _P
            page.screenshot(path=str(_P(__file__).resolve().parents[2] / "output" /
                                      "saraplus_empty_grid.png"), full_page=True)
        except Exception:
            pass


# Each data row is [indent(''), 'N_Agent' group-key, agent name, Total Sales, …].
# The group key sits at cell index 1; the name at index 2; metric columns line up
# 1:1 with the header row (both carry the same 3 leading columns — no offset).
def _grid_rows(page):
    return page.eval_on_selector_all(
        f"{GRID}_ctl00 > tbody > tr",
        """els => els.map(tr =>
            Array.from(tr.querySelectorAll('th,td')).map(c => (c.innerText||'').trim()))""")


def _is_agent_row(cells) -> bool:
    return len(cells) > 2 and (cells[1] or "").endswith("_Agent")


def _count_agent_rows(page) -> int:
    return sum(1 for cells in _grid_rows(page) if _is_agent_row(cells))


def _scrape_agents(page) -> Dict[str, Dict[str, int]]:
    headers = page.eval_on_selector_all(
        f"{GRID} .rgHeader", "els => els.map(e => (e.innerText||'').trim())")
    if not headers:
        raise RuntimeError("Sara dashboard: no grid headers found after submit.")
    col = {lbl: i for i, lbl in enumerate(headers) if lbl}  # header idx == data idx
    for need in (COL_NL, COL_INT, COL_VOICE, COL_TOTAL):
        if need not in col:
            raise RuntimeError(f"Sara dashboard missing column {need!r}. Headers: {headers}")

    def num(cell: str) -> int:
        cell = (cell or "").replace(",", "").strip()
        try:
            return int(float(cell)) if cell else 0
        except ValueError:
            return 0

    out: Dict[str, Dict[str, int]] = {}
    for cells in _grid_rows(page):
        if not _is_agent_row(cells):
            continue
        name = (cells[2] or "").strip()
        if not name:
            continue
        out[name] = {
            "nl": num(cells[col[COL_NL]]) if col[COL_NL] < len(cells) else 0,
            "int": num(cells[col[COL_INT]]) if col[COL_INT] < len(cells) else 0,
            "voice": num(cells[col[COL_VOICE]]) if col[COL_VOICE] < len(cells) else 0,
            "total": num(cells[col[COL_TOTAL]]) if col[COL_TOTAL] < len(cells) else 0,
        }
    return out


def pull_many(ranges, headless: bool = False, allow_human_otp: bool = True,
              otp_wait_min: float = 20.0, logfn=print):
    """Pull several date ranges in ONE browser session (one login / one OTP).

    `ranges` = list of (label, start_date, end_date). Returns
    {label: {sara_agent: {'nl','int','voice','total'}}}. Use this to grab the
    wide roster + the target day together so the human only clears the OTP once.
    """
    from patchright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    out = {}
    with sync_playwright() as p:
        ctx = _launch_persistent(p, PROFILE, headless=headless, label="saraplus")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            try:
                page.bring_to_front()
            except Exception:
                pass
            _login(page, allow_human_otp=allow_human_otp,
                   otp_wait_min=otp_wait_min, logfn=logfn)
            _open_dashboard(page)
            for label, start, end in ranges:
                rng = _fmt(start) if end == start else f"{_fmt(start)}..{_fmt(end)}"
                logfn(f"  Sara Plus: {label} — date {rng}…")
                _set_range_and_submit(page, start, end)
                out[label] = _scrape_agents(page)
                logfn(f"    {len(out[label])} agent row(s).")
            return out
        finally:
            ctx.close()


def pull_agents(day: dt.date, end: Optional[dt.date] = None,
                headless: bool = True, allow_human_otp: bool = False,
                logfn=print) -> Dict[str, Dict[str, int]]:
    """Pull the 'Total - Agent' breakdown for a day (or a [day..end] range, used
    for the roster pre-check).

    Returns {sara_agent_name: {'nl','int','voice','total': int}}. Raises
    OTPRequired if the profile lost device trust (unless allow_human_otp and a
    human clears it in the headed window)."""
    from patchright.sync_api import sync_playwright
    end = end or day
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch_persistent(p, PROFILE, headless=headless, label="saraplus")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _login(page, allow_human_otp=allow_human_otp, logfn=logfn)
            _open_dashboard(page)
            rng = _fmt(day) if end == day else f"{_fmt(day)}..{_fmt(end)}"
            logfn(f"  Sara Plus: Sales Dashboard, date {rng}…")
            _set_range_and_submit(page, day, end)
            agents = _scrape_agents(page)
            logfn(f"  Sara Plus: {len(agents)} agent row(s) with sales.")
            return agents
        finally:
            ctx.close()

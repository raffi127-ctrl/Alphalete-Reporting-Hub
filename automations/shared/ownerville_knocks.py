"""Read one office's OwnerVille disposition grid. No creds module, no Tableau.

BUILT TO RUN ON A LAPTOP WE DO NOT OWN. `total_knocks.pull` does this already
and does it well, but it reaches `shared.tableau_patchright` for the session and
carries the Total-Knocks Sheet's whole column vocabulary — neither of which
belongs on an ICD's machine. So the page-driving half lives here: pass a page
and a login, get rows back.

IT RETURNS RAW ROWS, keyed by the grid's OWN header text. Mapping those onto
canonical names is OUR side's job, where the vocabulary already lives and can
change without reaching 52 laptops. A laptop that shipped opinions about column
names would need a release every time a disposition was renamed.

NO IMPERSONATION, and that is the whole reason an owner reads their own office:
`_pin_campaign` / `assert_impersonating` and the entire bug class around them —
the pull that returned Calvin's seven reps under Kash's heading, the read-only
probe that stranded a session and fed Raf an impersonated board twice in one
afternoon — simply do not apply when the login IS the office.

Python 3.9-safe and platform-neutral.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

LOGIN_URL = "https://ownerville.com"
V2_URL = "https://v2.ownerville.com/index.cfm"
DISPOSITIONS_TABLE = "#table-dispositions"

# Lifted from shared/tableau_patchright so the two cannot drift on a form
# change; kept here because importing that module pulls in Tableau.
_USERNAME_SELECTOR = (
    'input[type="email"], input[name="username"], input[name="email"], '
    'input[type="text"]'
)
_PASSWORD_SELECTOR = 'input[type="password"]'
_LOGIN_BUTTON_NAME = re.compile(r"log\s*in|sign\s*in", re.IGNORECASE)
_NEXT_BUTTON_NAME = re.compile(r"^\s*next\s*$", re.IGNORECASE)
_FINAL_SUBMIT_NAME = re.compile(
    r"sign\s*in|log\s*in|submit|continue|enter", re.IGNORECASE)

# THE 'VERIFY YOU ARE HUMAN' BOX CLEARS ITSELF, but only if you leave it alone
# long enough. Megan 2026-09-01: "you just wait 30 sec before hitting submit on
# the PW". Shorter waits land the submit while the box is still thinking and
# the login fails in a way that looks like a wrong password. NO HUMAN IS
# NEEDED; the wait is the whole trick.
CLOUDFLARE_WAIT_MS = 30_000
PRE_SUBMIT_PAUSE_MS = 30_000


class OwnervilleError(RuntimeError):
    """Phrased for whoever is reading it on an owner's laptop."""


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


# --- signing in -------------------------------------------------------------
def login(page, username: str, password: str, *, log=print) -> None:
    """Drive the two-step username -> NEXT -> password form with THEIR login."""
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3_000)

    for role in ("link", "button"):
        try:
            cand = page.get_by_role(role, name=_LOGIN_BUTTON_NAME).first
            if cand.is_visible(timeout=2_000):
                cand.click()
                break
        except Exception:  # noqa: BLE001
            continue

    page.wait_for_selector(_USERNAME_SELECTOR, timeout=15_000)
    page.fill(_USERNAME_SELECTOR, username)
    page.get_by_role("button", name=_NEXT_BUTTON_NAME).first.click()
    page.wait_for_selector(_PASSWORD_SELECTOR, timeout=60_000)

    log("waiting %ds for the security check to clear itself"
        % (CLOUDFLARE_WAIT_MS // 1000))
    page.wait_for_timeout(CLOUDFLARE_WAIT_MS)
    page.fill(_PASSWORD_SELECTOR, password)
    page.wait_for_timeout(PRE_SUBMIT_PAUSE_MS)

    # The submit fires a Cloudflare->SSO redirect chain that can outlast
    # patchright's 30s post-click navigation auto-wait, so .click() raises even
    # though the form already submitted. no_wait_after skips that auto-wait.
    try:
        page.get_by_role("button", name=_FINAL_SUBMIT_NAME).first.click(
            no_wait_after=True)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(5_000)


def capture_rqst(page) -> Optional[str]:
    """The SSO token every p=89 url needs. Its absence means NOT SIGNED IN --
    a page that rendered is not a session."""
    for url in (V2_URL, LOGIN_URL):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
        except Exception:  # noqa: BLE001
            continue
        m = re.search(r"rqst=([A-Za-z0-9_\-]+)", page.url)
        if m:
            return m.group(1)
        try:
            href = page.evaluate(
                "() => { const a = document.querySelector('a[href*=\"rqst=\"]');"
                " return a ? a.getAttribute('href') : ''; }")
        except Exception:  # noqa: BLE001
            href = ""
        m = re.search(r"rqst=([A-Za-z0-9_\-]+)", href or "")
        if m:
            return m.group(1)
    return None


# --- the grid ---------------------------------------------------------------
def navigate(page, rqst: str, mdy: str, *, attempts: int = 3, log=print) -> None:
    """Disposition by Rep for ONE day. The date filters server-side via the
    URL; the on-page picker only sets local JS vars.

    Waits for the HEADER row, not the body. DataTables builds the grid from an
    AJAX call that fires after networkidle, so a header read can land on an
    empty <thead> -- reproduced 1-in-2 on the same office and date. A day with
    NO knocks still renders headers, so this cannot confuse an empty day with a
    stalled one, which is the distinction that matters when an office
    legitimately logged nothing.
    """
    url = ("%s?p=89&rqst=%s&startDate=%s&endDate=%s" % (V2_URL, rqst, mdy, mdy))
    for attempt in range(1, attempts + 1):
        page.goto(url, wait_until="networkidle", timeout=25_000)
        try:
            page.wait_for_selector(DISPOSITIONS_TABLE + " thead th", timeout=15_000)
            break
        except Exception:  # noqa: BLE001 — a stalled grid, not a fatal state
            if attempt == attempts:
                log("grid never built after %d navigations" % attempts)
                break
            log("grid not built yet (try %d/%d) — re-navigating"
                % (attempt, attempts))
    try:                       # show all rows on one page where possible
        page.locator("select[name='table-dispositions_length']").select_option("100")
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:  # noqa: BLE001
        pass


def header_index(page) -> Dict[str, int]:
    """{normalized header text: column index}, read LIVE off the grid.

    Waits for the header row first. Reading the instant navigation returns
    yields {} on a grid still building -- and an empty index makes every
    column missing, an intermittent failure that looks exactly like a
    permanent one.
    """
    try:
        page.wait_for_function(
            "() => document.querySelectorAll("
            "  '#table-dispositions thead th, #table-dispositions thead td'"
            ").length > 0", timeout=15_000)
    except Exception:  # noqa: BLE001
        pass
    headers = page.evaluate(
        """() => {
            const t = document.querySelector('#table-dispositions');
            if (!t) return [];
            return Array.from(t.querySelectorAll('thead th, thead td'))
                .map(th => (th.innerText || '').trim());
        }""")
    return {_norm(h): i for i, h in enumerate(headers)}


def wait_rows_settled(page, *, quiet_ms: int = 400, timeout_ms: int = 12_000) -> int:
    """Wait until the grid STOPS growing, and return the row count.

    DataTables fills the table from an AJAX call, and asking for 100 rows per
    page fires a SECOND one. Between those the tbody legitimately holds a
    partial set -- and reading at that moment is how a board publishes 2 reps
    of 22 with nothing raising. Best-effort by design: a wait that RAISED would
    turn a slow grid into a missing board.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    last, stable_since = -1, time.monotonic()
    while time.monotonic() < deadline:
        try:
            n = page.evaluate(
                "() => {"
                " const p = document.querySelector('#table-dispositions_processing');"
                " const busy = p && p.offsetParent !== null;"
                " const rows = document.querySelectorAll("
                "   '#table-dispositions tbody tr').length;"
                " return busy ? -1 : rows;"
                "}")
        except Exception:  # noqa: BLE001 — a wait must never be the failure
            return max(last, 0)
        if n != last:
            last, stable_since = n, time.monotonic()
        elif n >= 0 and (time.monotonic() - stable_since) * 1000 >= quiet_ms:
            return n
        try:
            page.wait_for_timeout(150)
        except Exception:  # noqa: BLE001
            break
    return max(last, 0)


def fetch_time_tracker(page, rqst: str, mdy: str, *, log=print) -> List[Dict]:
    """Raw Time Tracker rows for one day, straight from its JSON endpoint.

    THIS IS WHERE GAPS COME FROM. The disposition grid has no idea how long a
    rep stood still; the board's Gaps and Total Gaps columns are this fetch, and
    without it they render empty -- which on a board whose whole point is rep
    gaps reads as "nobody was idle" rather than "we did not look".

    A same-origin fetch from the page, so the session cookies ride along.
    Driving the jQuery datepicker instead is not an option here: jQuery is not
    on `window` in the world patchright evaluates in.

    A 200 with no rows is a VERIFIED quiet day, never a failure. A bad status
    leaves gaps blank rather than losing the board -- the disposition half is
    still worth posting.
    """
    result = page.evaluate(
        """async ({rqst, mdy}) => {
            const url = `https://v2.ownerville.com/components/telemapper/`
                + `report_timeTracker.cfc?method=getTimeTrackingData&rqst=${rqst}`
                + `&dateToSearch=${encodeURIComponent(mdy)}&returnFormat=json`;
            try {
                const r = await fetch(url, {credentials: 'include'});
                const text = await r.text();
                try { return {status: r.status, data: (JSON.parse(text).data) || []}; }
                catch (e) { return {status: r.status, data: [], raw: text.slice(0, 160)}; }
            } catch (e) { return {status: 0, data: [], raw: String(e).slice(0, 160)}; }
        }""",
        {"rqst": rqst, "mdy": mdy})
    rows = result.get("data") or []
    status = result.get("status")
    if status != 200:
        log("time tracker unavailable (status %s) — gaps will be blank" % status)
        return []
    log("time tracker: %d rep(s) clocked in" % len(rows))
    return rows


def read_rows(page, *, log=print) -> List[Dict[str, str]]:
    """Every rep row, as {header text: cell text}.

    RAW, and keyed by the grid's own headers. This module deliberately holds no
    opinion about which columns matter or what they are called: the office that
    sells fiber, the one on wireless and the one on Energy Wells all render
    different dispositions, and teaching a laptop that vocabulary means a
    release every time one is renamed.
    """
    idx = header_index(page)
    if not idx:
        raise OwnervilleError(
            "The knocks table never appeared. This usually means the "
            "OwnerVille sign-in did not go through.")
    wait_rows_settled(page)
    names = [h for h, _ in sorted(idx.items(), key=lambda kv: kv[1])]
    cells = page.evaluate(
        """() => Array.from(
             document.querySelectorAll('#table-dispositions tbody tr')
           ).map(tr => Array.from(tr.querySelectorAll('td'))
                            .map(td => (td.innerText || '').trim()))""")
    rows = []
    for row in cells:
        if not any((c or "").strip() for c in row):
            continue
        rows.append({names[i]: row[i] for i in range(min(len(names), len(row)))})
    log("read %d rep row(s), %d column(s)" % (len(rows), len(names)))
    return rows

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

# DataTables' own empty-state text, in the variants it ships with.
EMPTY_GRID_RE = re.compile(
    r"no (?:data|matching|records)|nothing found|empty", re.IGNORECASE)

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


class AccountLocked(OwnervilleError):
    """The login page itself says the account is locked. Only OwnerVille
    support can undo it, and every further attempt is one more strike."""


# THE LOCK SHOWS ON THE PASSWORD STEP, before anything is submitted. Jenny
# (Figspire) 2026-10-12: "Account Permanently Locked -- Your account has been
# locked due to excessive failed login attempts. Admin unlock required." and
# the submit button reads "LOCKED - CONTACT SUPPORT". Her laptop kept opening
# that window every sweep, because nothing here read the page.
LOCKED_RE = re.compile(
    r"account (?:permanently )?locked|locked due to excessive"
    r"|admin unlock required|locked\s*[-–—]\s*contact support",
    re.IGNORECASE)


def page_says_locked(page) -> bool:
    try:
        text = page.inner_text("body", timeout=5_000)
    except Exception:  # noqa: BLE001
        return False
    return bool(LOCKED_RE.search(text or ""))


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


# --- signing in -------------------------------------------------------------
def login(page, username: str, password: str, *, log=print,
          url: str = LOGIN_URL) -> None:
    """Drive the two-step username -> NEXT -> password form with THEIR login.

    `url` lets AppStream reuse it: applicantstream.com serves the SAME form,
    security box and all (resources/lucy-login-standard.md, rule 1)."""
    page.goto(url, wait_until="domcontentloaded")
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
    if page_says_locked(page):
        raise AccountLocked("the sign-in page says this account is locked")

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
    if page_says_locked(page):
        raise AccountLocked("the sign-in page says this account is locked")


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
def pin_campaign(page, rqst: str, campaign_id: str, *, log=print) -> bool:
    """Put this OwnerVille session on one campaign before reading anything.

    THE CAMPAIGN IS A STICKY SESSION-GLOBAL. An unpinned read returns whatever
    campaign that login was last on -- which for an owner running one campaign
    is always the right answer, and for an owner running two is whatever they
    themselves last clicked. Not a default: a coin flip (Megan 2026-09-15,
    enrolling two multi-campaign offices).

    PINNING IS NOT PROOF. A pin can fail to take and still serve a grid:
    Calvin was pinned to Energy Wells on 2026-09-02 and his board came back
    Box-shaped, published as "TOTAL KNOCKS - ENERGYWELL - CALVIN", and nobody
    reading it could have told. So this only ASKS; whether the grid that
    arrives really is that campaign's is checked where the board is drawn, on
    our side, against the rows themselves.
    """
    if not campaign_id:
        return False
    try:
        page.goto("%s?p=88&rqst=%s&invD2DClientId=%s" % (V2_URL, rqst,
                                                         campaign_id),
                  wait_until="networkidle", timeout=25_000)
        page.wait_for_timeout(1000)
        log("  pinned campaign %s" % campaign_id)
        return True
    except Exception as e:  # noqa: BLE001 — an unpinned read is still a read
        log("  could not pin campaign %s: %s" % (campaign_id, type(e).__name__))
        return False


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
        # A slow page load is the same stall as a slow grid and gets the same
        # retries. Roshan 2026-09-18: one goto timeout outside this loop ended
        # the whole knocks read on the first try.
        try:
            page.goto(url, wait_until="networkidle", timeout=25_000)
        except Exception:  # noqa: BLE001 — retried below; the last one raises
            if attempt == attempts:
                raise
            log("page load timed out (try %d/%d) — re-navigating"
                % (attempt, attempts))
            continue
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


# --- consumer tallies (B2B) ---------------------------------------------------
# OwnerVille → TeleMapper Leads → Reports → CRU/IRU Engagement → Consumer
# Tally. A B2B rep also logs CONSUMER doors, and the disposition grid only
# counts business ones (Jamis 2026-11-14). The tab is filled by ONE JSON call
# (consumer_tally_probe, 2026-11-15): reps[{name, loc{c1..c6}, fly{c1..c6},
# appts}], c1..c6 in the tab's column order; loc = at a business, fly = on the
# fly, and the board shows their sum. Megan 2026-11-15: every B2B board, at the
# far right, in its own shade.
CONSUMER_COLUMNS = ["Consumer Talk To", "Consumer Qualifying Questions",
                    "Consumer Presentation", "Consumer Close",
                    "Consumer Sara Plus (Credit Check)", "Consumer Client Acq.",
                    "Consumer Appointments Set"]
# Raw-row keys are the board names lower-cased, like every other grid column.
CONSUMER_KEYS = [c.lower() for c in CONSUMER_COLUMNS]


def fetch_consumer_tally(page, rqst: str, day_iso: str, *,
                         log=print) -> "List[Dict] | None":
    """{rep name: {consumer column: n}} for one day, or None when the call
    failed. An empty dict is a VERIFIED day with no consumer tallies."""
    result = page.evaluate(
        """async ({rqst, day}) => {
            const url = `https://v2.ownerville.com/components/telemapper/`
                + `report_consumer.cfc?method=getConsumerTally&rqst=${rqst}`
                + `&startDate=${day}&endDate=${day}`;
            try {
                const r = await fetch(url, {credentials: 'include'});
                const text = await r.text();
                try { return {status: r.status, data: JSON.parse(text).data}; }
                catch (e) { return {status: r.status, raw: text.slice(0, 160)}; }
            } catch (e) { return {status: 0, raw: String(e).slice(0, 160)}; }
        }""",
        {"rqst": rqst, "day": day_iso})
    data = (result or {}).get("data")
    if (result or {}).get("status") != 200 or not isinstance(data, dict) \
            or "reps" not in data:
        log("consumer tally unavailable (status %s) — board posts without it"
            % (result or {}).get("status"))
        return None
    out: Dict = {}
    for r in data.get("reps") or []:
        name = " ".join(str(r.get("name") or "").split())
        if not name:
            continue
        loc, fly = r.get("loc") or {}, r.get("fly") or {}

        def _n(v):
            try:
                return int(float(v or 0))
            except (TypeError, ValueError):
                return 0
        vals = {CONSUMER_COLUMNS[i]: _n(loc.get("c%d" % (i + 1)))
                + _n(fly.get("c%d" % (i + 1))) for i in range(6)}
        vals[CONSUMER_COLUMNS[6]] = _n(r.get("appts"))
        out[name] = vals
    log("consumer tally: %d rep(s)" % len(out))
    return out


def attach_consumer(rows: List[Dict], tally: Dict, *, log=print) -> List[Dict]:
    """Put each rep's consumer numbers onto THEIR grid row (raw keys), so they
    travel with the knocks everywhere the knocks already go. Every grid row
    gets all seven (0 when the rep logged none: the tally only lists reps who
    did). A tally rep with no grid row is logged, not invented."""
    def _k(s):
        return " ".join(str(s or "").split()).lower()
    by = {_k(n): v for n, v in (tally or {}).items()}
    seen = set()
    for row in rows or []:
        rep = row.get("rep") or row.get("Rep") or ""
        vals = by.get(_k(rep))
        if vals is not None:
            seen.add(_k(rep))
        for col, key in zip(CONSUMER_COLUMNS, CONSUMER_KEYS):
            row[key] = str((vals or {}).get(col, 0))
    missing = [n for n in (tally or {}) if _k(n) not in seen]
    if missing:
        log("consumer tally: no grid row for %s — left off the board"
            % ", ".join(missing))
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
        # DataTables renders its empty state as ONE cell spanning the table --
        # "No data available in table". It is not blank, so an all-cells-empty
        # test misses it, and it arrives looking exactly like a rep whose name
        # is that sentence. Read off the live grid on 2026-09-11: a legitimately
        # quiet morning came back as "1 rep row".
        if len(row) < max(2, len(names) // 2):
            text = " ".join(c for c in row if c).strip().lower()
            if not text or EMPTY_GRID_RE.search(text):
                continue
        rows.append({names[i]: row[i] for i in range(min(len(names), len(row)))})
    log("read %d rep row(s), %d column(s)" % (len(rows), len(names)))
    return rows

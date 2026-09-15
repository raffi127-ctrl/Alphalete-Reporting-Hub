"""Read THIS machine's My Service Cloud account and count today's Box work.

THE SHAPE ON THE WIRE IS THE SHAPE OF THE BOARD. read_day() returns exactly
what sara_read.read_day() returns -- {'records': {...}, 'sales': {...}} -- so
the relay, the live sales board and the Slack alerts all consume it with no
new pipeline. See icd_sales_board/relay_read.py, which says the same thing
from the other end.

  records -> contracts AWAITING SIGNATURE, per rep.
             Box's nearest thing to a SaraPlus credit check, and the fast
             alert: it lands minutes after the work rather than at the close.
  sales   -> {rep: {"Sales": n, "Volume": v}}, per rep.
             The six substatuses the office calls sold, plus the annual volume
             those contracts carry.

TWO HALVES, DELIBERATELY SPLIT. tally() is arithmetic over rows and is tested.
read_day() drives a browser and is not -- there is no Box account here to sign
into, and the office's own credentials are theirs. So everything that can be
wrong about the COUNTING is covered, and what remains unproven is the
navigation, which the first real run will show.

THE SESSION IS THE FRAGILE PART. SaraPlus signs in fresh every sweep; this
cannot, because of the authenticator. A sweep that finds a login form has lost
the session, and that is a person's problem to fix -- never an office with no
sales. See servicecloud.session_lost().
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

from automations.icd_alerts import config as C
from automations.shared import servicecloud as SC


class AccountProblem(RuntimeError):
    """Something the office can fix, phrased for the office."""


# "09/15/2026 06:13 PM" -- the Initiated Date cell, which IS the sale date.
# Start Date is the service start (APR 2027) and must never be read for this.
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def initiated_on(value: str) -> Optional[dt.date]:
    """The day a contract was initiated, or None if the cell cannot be read.

    None, not today. A cell we cannot parse is unknown, and counting it as
    today would put somebody else's week into this morning's number.
    """
    m = _DATE_RE.search(str(value or ""))
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _volume(value) -> int:
    """'51,000' -> 51000. Anything unreadable is zero, never a guess."""
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else 0


def tally(rows: List[Dict], day: dt.date) -> Dict:
    """{'records': {...}, 'sales': {...}, 'unknown': [...]} for ONE day.

    ROWS FOR OTHER DAYS ARE IGNORED, not assumed absent: the grid is sorted
    newest first and a day's contracts sit among yesterday's, so a reader that
    takes what it is given would fold the whole week into today.

    A rep with no name is skipped rather than bucketed under "". An unnamed
    row is a grid problem; inventing a rep out of it would put sales on a
    board under a blank heading.
    """
    records: Dict[str, int] = {}
    sales: Dict[str, Dict[str, int]] = {}
    seen_status: List[str] = []

    for row in rows or []:
        if initiated_on(row.get(SC.COL_INITIATED)) != day:
            continue
        rep = str(row.get(SC.COL_AGENT) or "").strip()
        if not rep:
            continue
        status = str(row.get(SC.COL_SUBSTATUS) or "").strip()
        seen_status.append(status)

        if SC.is_presale(status):
            records[rep] = records.get(rep, 0) + 1
            continue
        if SC.is_completed(status):
            got = sales.setdefault(rep, {"Sales": 0, "Volume": 0})
            got["Sales"] += 1
            got["Volume"] += _volume(row.get("Adjusted Annual Volume"))

    return {"records": records, "sales": sales,
            # A substatus nobody has ruled on. Reported so Box adding one
            # cannot quietly drop those contracts out of every Box number.
            "unknown": SC.unknown_statuses(seen_status)}


def _context(p, headless: bool):
    """The Service Cloud profile. NEVER rotated.

    sara_read throws a wedged profile away and signs in again, because a
    SaraPlus login is an email and a password. This profile IS the two-factor
    session: discarding it costs the owner standing at their Mac with an
    authenticator, not a retry.
    """
    C.SC_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(C.SC_PROFILE_DIR), headless=headless, args=["--disable-sync"])


def _grid_rows(page) -> List[Dict]:
    """The contracts grid as {column name: cell}, matched BY NAME.

    By name because the grid has a column chooser: Agent and Initiated Date
    were both hidden when it was first looked at, and an index would silently
    read a neighbour the first time somebody toggles one.
    """
    return page.evaluate("""() => {
        const t = document.querySelector('table');
        if (!t) return [];
        const head = [...t.querySelectorAll('thead th')]
            .map(th => (th.innerText || '').trim());
        return [...t.querySelectorAll('tbody tr')].map(tr => {
            const cells = [...tr.querySelectorAll('td')]
                .map(td => (td.innerText || '').trim());
            const row = {};
            head.forEach((h, i) => { if (h) row[h] = cells[i] || ''; });
            return row;
        });
    }""")


def read_day(day: Optional[dt.date] = None, *, headless: bool = True,
             log=print) -> Dict:
    """Today's Box work, in the shape every other surface already reads."""
    from patchright.sync_api import sync_playwright

    day = day or C.today()
    cr = C.sc_creds()
    if not cr.get("email"):
        raise AccountProblem(
            "No My Service Cloud login is saved on this computer, so this "
            "office's sales cannot be read. Run the installer again and it "
            "will ask for it.")

    with sync_playwright() as p:
        ctx = _context(p, headless)
        try:
            page = ctx.new_page()
            page.goto(SC.LOGIN_URL.rsplit("/", 1)[0] + SC.CONTRACTS_PATH,
                      timeout=SC.LOGIN_TIMEOUT_MS)
            if SC.session_lost(page):
                # NOT AN EMPTY DAY. The session has gone and a person has to
                # sign in with their authenticator -- reporting zero here is
                # the failure this whole module is written around.
                raise AccountProblem(
                    "My Service Cloud has signed this computer out, so no "
                    "sales can be read until somebody signs in again with "
                    "the authenticator code. Nothing is lost -- the contracts "
                    "are still there, we just cannot see them.")
            rows = _grid_rows(page)
            log("contracts grid: %d row(s) on screen" % len(rows))
        finally:
            ctx.close()

    out = tally(rows, day)
    log("awaiting signature: %d rep(s), sold: %d rep(s)"
        % (len(out["records"]), len(out["sales"])))
    if out["unknown"]:
        log("substatuses nobody has ruled on: %s" % ", ".join(out["unknown"]))
    return out

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


class SignInNeeded(AccountProblem):
    """The session is gone and only a person with the authenticator can fix it.

    ITS OWN CLASS BECAUSE IT NEEDS ITS OWN ALERT. Ryan McSpadden, asked how
    often the authenticator is needed: "It saves typically, but it feels
    random when it logs me out" (2026-09-15). So this is not a rare edge --
    it will happen, unpredictably, and the office will not know it has
    happened. Every other fault here is ours to chase; this one is the only
    thing the OWNER can act on, and until they do their sales read as zero.
    """


# TWO FORMATS, BECAUSE THE SCREEN AND THE WIRE DISAGREE. The grid shows
# "09/15/2026 06:13 PM"; the API returns "2026-09-15 18:13:46" for the same
# contract. Reading Ryan's live data with only the screen's format matched
# nothing at all and the day came back EMPTY -- no error, no rows, just an
# office that looked like it had sold nothing (2026-09-15).
_DATE_US = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")     # 09/15/2026
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")    # 2026-09-15


def initiated_on(value: str) -> Optional[dt.date]:
    """The day a contract was initiated, or None if the cell cannot be read.

    None, not today. A cell we cannot parse is unknown, and counting it as
    today would put somebody else's week into this morning's number.
    """
    text = str(value or "")
    m = _DATE_ISO.search(text)
    if m:
        year, month, day = (int(g) for g in m.groups())
    else:
        m = _DATE_US.search(text)
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


def tally_window(rows: List[Dict], days: List[dt.date]) -> Dict:
    """{day: {'records':..., 'sales':...}} for SEVERAL days at once.

    A CONTRACT BECOMES A SALE LATER THAN IT IS SOLD. Megan 2026-09-15: "you
    need to track past days in case status changes here and we need to count
    something as a sale". A rep sells on Monday, the contract sits at
    "Awaiting Signature", and on Wednesday it passes TPV -- and it was always
    Monday's sale. Reading only today would have counted it on Wednesday under
    whoever happened to be having a good day, or not at all.

    So a sale belongs to its INITIATED date and its status is whatever the
    status is NOW. Re-reading a window rewrites the days in it, which is what
    makes a board that fills itself correct rather than merely current.
    """
    out = {d: {"records": {}, "sales": {}} for d in days}
    seen_status: List[str] = []
    wanted = set(days)

    for row in rows or []:
        when = initiated_on(row.get(SC.COL_INITIATED))
        if when not in wanted:
            continue
        rep = str(row.get(SC.COL_AGENT) or "").strip()
        if not rep:
            continue
        status = str(row.get(SC.COL_SUBSTATUS) or "").strip()
        seen_status.append(status)
        bucket = out[when]

        # WORKING AND SOLD ARE NOT EXCLUSIVE. A sale was logged first, so it
        # belongs in both -- "working" is every real contract, "sales" is the
        # ones that closed. Counting them as either/or would make a rep's
        # working number FALL as their sales rose.
        if SC.is_logged(status):
            bucket["records"][rep] = bucket["records"].get(rep, 0) + 1
        if SC.is_completed(status):
            got = bucket["sales"].setdefault(
                rep, {"Sales": 0, "Volume": 0, "Big": 0, "Huge": 0})
            got["Sales"] += 1
            got["Volume"] += _volume(row.get("Adjusted Annual Volume"))
            # HOW LOUD, decided per CONTRACT and carried as counts. The bar is
            # one contract's term and volume, not the rep's day, so it cannot
            # be worked out from the totals afterwards.
            #
            # A HUGE CONTRACT IS ALSO A BIG ONE -- it meets the term rule and
            # then some. Making them exclusive would drop a rep's Big count as
            # their contracts got larger, the same trap as working-vs-sold.
            loud = SC.contract_tier(row.get(SC.COL_TERM),
                                    row.get("Adjusted Annual Volume"))
            if loud:
                got["Big"] += 1
            if loud == "huge":
                got["Huge"] += 1

    for d in out:
        out[d]["unknown"] = []
    if days:
        out[days[0]]["unknown"] = SC.unknown_statuses(seen_status)
    return out


def tally(rows: List[Dict], day: dt.date) -> Dict:
    """{'records': {...}, 'sales': {...}, 'unknown': [...]} for ONE day.

    ROWS FOR OTHER DAYS ARE IGNORED, not assumed absent: the grid is sorted
    newest first and a day's contracts sit among yesterday's, so a reader that
    takes what it is given would fold the whole week into today.

    A rep with no name is skipped rather than bucketed under "". An unnamed
    row is a grid problem; inventing a rep out of it would put sales on a
    board under a blank heading.

    ONE DAY IS A WINDOW OF ONE. This used to be its own copy of the loop
    below, and the two drifted the moment a rule changed: "Big" was added to
    the window's sale and not to this one, so a single-day read would have
    reported every sale as ordinary (2026-09-15). There is now one rule and
    one place to change it.
    """
    return tally_window(rows, [day])[day]


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


def row_from_edge(edge: Dict) -> Dict:
    """One contractsList edge -> the row shape tally() reads.

    THE API'S NAMES ARE NOT THE SCREEN'S. "Initiated Date" on the grid is
    created_date on the wire, and the agent is a nested object rather than a
    string. A reader written off the column headings would never have found
    either -- which is why the query was captured from the page rather than
    guessed.
    """
    agent = edge.get(SC.FIELD_AGENT) or {}
    name = (agent or {}).get("name") or {}
    rep = " ".join(x for x in (name.get("first_name"), name.get("last_name"))
                   if x).strip()
    sub = edge.get(SC.FIELD_SUBSTATUS) or {}
    return {
        SC.COL_AGENT: rep,
        SC.COL_INITIATED: edge.get(SC.FIELD_INITIATED) or "",
        SC.COL_SUBSTATUS: (sub or {}).get("substatus") or "",
        "Adjusted Annual Volume": edge.get(SC.FIELD_VOLUME) or 0,
        # MONTHS. Half of what makes a sale worth shouting about, and absent
        # from this reader until 2026-09-15 -- see SC.is_big. Missing is kept
        # as "" rather than 0 so is_big can tell "no term on the wire" apart
        # from "a term of zero".
        SC.COL_TERM: edge.get(SC.FIELD_TERM, ""),
        SC.COL_BUSINESS: edge.get(SC.FIELD_BUSINESS) or "",
    }


def rows_from_response(payload: Dict) -> List[Dict]:
    """Every edge in a contractsList response, as rows. Never raises.

    An envelope that carries errors returns NOTHING rather than a short list:
    a partial page read as a whole one is how an office's number comes out low
    with nothing to say why.
    """
    data = ((payload or {}).get("data") or {}).get("contractsList") or {}
    if (payload or {}).get("errors") or (data.get("errors") or []):
        return []
    return [row_from_edge(e) for e in (data.get("edges") or [])]


# HOW THE ROWS ARE FETCHED, and why it is done from inside the page.
#
# The grid is a DevExtreme DataGrid split across four tables, with no <thead>
# and only ~18 of a 50-row page rendered at a time. Scraping it would read LOW
# and look fine. The data comes from a GraphQL endpoint instead
# (SC.GRAPHQL_URL), which answers paging, virtualisation and "one day among
# many" at once.
#
# BUT THE AUTH IS THE APP'S. The request carries `authorization` and `api-key`
# headers the SPA holds. Reproducing them would mean storing somebody's token
# in this repo, and tokens expire. So this asks the PAGE to make the call: the
# app's own fetch, with the app's own headers, from a session the office
# signed into. Nothing here ever sees a token and it keeps working when Box
# rotates one.
GRAPHQL_URL = SC.GRAPHQL_URL

# Page one is what the grid asks for. Bigger pages mean fewer round trips for
# a week's window, and the server decides whether to honour it.
PER_PAGE = 100
MAX_PAGES = 40          # 4000 contracts. A stop, not an expectation.


_FETCH_JS = """
async (args) => {
  const [url, page, perPage] = args;
  const query = `query ($input: ContractsListQueryInput) {
    contractsList(input: $input) {
      edges {
        contract_id
        business_name
        adjusted_annual_volume
        created_date
        agent { name { first_name last_name } email }
        contract_substatus { substatus }
      }
      errors { error_message }
    }
  }`;
  const res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: window.__lucyHeaders || {'content-type': 'application/json'},
    body: JSON.stringify({query, variables: {input: {
      page: page, per_page: perPage, search: '',
      sorting: [{name: 'id', direction: 'DESCENDING'}]}}}),
  });
  return await res.json();
}
"""

# The app's own request goes past first, so its headers -- including the ones
# we must never store -- are borrowed for the calls above and then dropped
# with the browser context.
_SNIFF_JS = """
() => {
  if (window.__lucySniffing) return true;
  window.__lucySniffing = true;
  const orig = window.fetch;
  window.fetch = function (input, init) {
    try {
      const u = typeof input === 'string' ? input : (input && input.url) || '';
      if (/gql/i.test(u) && init && init.headers) {
        const h = {};
        const src = init.headers;
        if (typeof src.forEach === 'function') src.forEach((v, k) => h[k] = v);
        else Object.keys(src).forEach(k => h[k] = src[k]);
        window.__lucyHeaders = h;
      }
    } catch (e) {}
    return orig.apply(this, arguments);
  };
  return true;
}
"""


def _fetch_page(page, n: int) -> List[Dict]:
    """One page of contracts, through the app's own fetch."""
    payload = page.evaluate(_FETCH_JS, [GRAPHQL_URL, n, PER_PAGE])
    return rows_from_response(payload)


def fetch_rows(page, days: List[dt.date], log=print) -> List[Dict]:
    """Every contract initiated on any of `days`, newest first.

    STOPS WHEN IT HAS PASSED THE WINDOW, not when it finds nothing. The grid
    is sorted newest-first, so once a whole page is older than the oldest day
    we want, everything after it is older too. Reading to the end would be
    fifty-three pages to find one morning.

    A page that comes back EMPTY stops it as well -- that is the end of the
    list, and continuing would spin to MAX_PAGES for no reason.
    """
    oldest = min(days)
    out: List[Dict] = []
    for n in range(1, MAX_PAGES + 1):
        rows = _fetch_page(page, n)
        if not rows:
            break
        out.extend(rows)
        dates = [initiated_on(r.get(SC.COL_INITIATED)) for r in rows]
        real = [d for d in dates if d]
        if real and max(real) < oldest:
            # This whole page predates the window; so does everything after.
            break
        log("  page %d: %d row(s)" % (n, len(rows)))
    return out


def read_day(day: Optional[dt.date] = None, *, headless: bool = True,
             log=print, back_days: int = 6) -> Dict:
    """Today's Box work, in the shape every other surface already reads.

    READS A WINDOW AND RETURNS TODAY. A contract sold on Monday can pass TPV
    on Wednesday, and it was always Monday's sale -- so the window is
    re-read every sweep and `days` carries the whole of it for a caller that
    wants to rewrite past days on the board. See tally_window().
    """
    from patchright.sync_api import sync_playwright

    day = day or C.today()
    days = [day - dt.timedelta(days=n) for n in range(back_days, -1, -1)]
    cr = C.sc_creds()
    if not cr.get("email"):
        raise SignInNeeded(
            "No My Service Cloud login is saved on this computer, so this "
            "office's sales cannot be read. Run the installer again and it "
            "will ask for it.")

    with sync_playwright() as p:
        ctx = _context(p, headless)
        try:
            page = ctx.new_page()
            base = SC.LOGIN_URL.rsplit("/", 1)[0]
            page.goto(base + SC.CONTRACTS_PATH,
                      timeout=SC.LOGIN_TIMEOUT_MS)
            if SC.session_lost(page):
                # NOT AN EMPTY DAY. The session has gone and a person has to
                # sign in with their authenticator -- reporting zero here is
                # the failure this whole module is written around.
                raise SignInNeeded(
                    "My Service Cloud has signed this computer out, so no "
                    "sales can be read until somebody signs in again with "
                    "the authenticator code. Nothing is lost -- the contracts "
                    "are still there, we just cannot see them.")
            # Let the app make one call of its own, so its headers can be
            # borrowed for ours. Re-entering the route is enough.
            page.evaluate(_SNIFF_JS)
            page.goto(base + SC.CUSTOMERS_PATH, timeout=SC.LOGIN_TIMEOUT_MS)
            page.goto(base + SC.CONTRACTS_PATH, timeout=SC.LOGIN_TIMEOUT_MS)
            page.wait_for_timeout(4000)
            rows = fetch_rows(page, days, log=log)
            log("contracts fetched: %d row(s) across the window" % len(rows))
        finally:
            ctx.close()

    window = tally_window(rows, days)
    out = dict(window[day])
    # THE WHOLE WINDOW RIDES ALONG. A caller filling a board rewrites the past
    # days from this; a caller sending alerts uses only today. Neither has to
    # read twice.
    out["window"] = window
    log("awaiting signature: %d rep(s), sold: %d rep(s)"
        % (len(out["records"]), len(out["sales"])))
    if out.get("unknown"):
        log("substatuses nobody has ruled on: %s" % ", ".join(out["unknown"]))
    return out

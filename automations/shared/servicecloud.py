"""My Service Cloud — what Box offices use for sales, as AT&T uses SaraPlus.

ONE FILE FOR THE SITE, the same rule saraplus.py follows: every selector, URL
and grid marker lives here and nothing re-derives them. Every Box office signs
into the same system, so a change to the site is a change in one place for all
of them.

WHY IT EXISTS AT ALL. Box, Energy Wells and NDS have no SaraPlus account, so
until now the knocks board was their ENTIRE product -- no credit checks, no
sales, nothing on the days their reps were selling rather than knocking. This
is the other half for the Box offices (Megan 2026-09-15: "this is what Box
uses for sales like at&t uses Sara+").

THE PASSWORD NEVER LEAVES THE OFFICE'S MACHINE. Same contract as SaraPlus and
OwnerVille: the installer asks for it on their own Mac, it is written to their
own config directory, and what reaches us is counts. Nothing in this repo ever
holds one.
"""
from __future__ import annotations

from typing import Optional

# The office signs in here. Asked for and confirmed rather than guessed
# (Megan 2026-09-15, from Ryan McSpadden's own screenshot).
LOGIN_URL = "https://myservicecloud.net/sign-in"

# Read off the live sign-in page, not invented. The form is a plain HTML one:
# an email input, a password input and a submit button, with no framework
# wrapper to fight -- unlike SaraPlus, whose Telerik ids are what most of
# saraplus.py exists to handle.
SEL_EMAIL = "input[type='email']"
SEL_PASSWORD = "input[type='password']"
SEL_SUBMIT = "button[type='submit']"

# Where a wrong or expired password lands. Treated the same way SaraPlus's
# ResetPassword.aspx is: a page we must recognise, because the alternative is
# a scrape that "succeeds" against a login form and reports zero of everything.
PASSWORD_RESET_PATH = "/user/index/request-password-reset"

LOGIN_TIMEOUT_MS = 60_000

# WHERE THE SALES ARE, in Ryan McSpadden's words (2026-09-15): "To see sales
# you go to contracts and anything that says 'TPV Passed, Ready for booking,
# In Progress, Missing Documents or Submitted to supplier' are the sales that
# are completed. Anything else is still in process."
# A SINGLE-PAGE APP. Routes are client-side under /spa/ -- confirmed from
# Ryan's own screen, not guessed: myservicecloud.net/spa/customers. So a read
# navigates and waits for the grid to render; there is no server-rendered page
# to fetch, and no ".aspx" to post to the way SaraPlus has.
SPA_ROOT = "/spa"
CONTRACTS_PATH = "/spa/contracts"
CUSTOMERS_PATH = "/spa/customers"

# THE GRIDS PAGINATE. Customers showed "Showing 1 - 50 of 4261" across 86
# pages. Whatever a read does, it must not assume page one is the day: a
# reader that takes the first fifty rows and stops would report a number that
# is right on a quiet morning and quietly wrong every afternoon.
#
# There is a per-column filter and a Filters button on the grid, and a
# Reports section in the nav. Either may give a day's rows directly, which is
# worth far more than paging 86 times -- to be established from the Contracts
# screen before any of this is written.
# THE COLUMNS A READ NEEDS, all confirmed on the live grid 2026-09-15. Two of
# them were not on screen at first and I recorded them as missing -- they were
# behind the column chooser, not absent. Worth the correction: "this office
# can only have a total, not a per-rep board" was wrong, and would have been a
# worse thing to build on than a blank.
COL_CONTRACT_ID = "Contract ID"
COL_BUSINESS = "Business Name"
COL_AGENT = "Agent"               # the REP. per-rep boards are possible.
COL_INITIATED = "Initiated Date"  # when it was SOLD -- "09/15/2026 06:13 PM"
COL_COMMODITY = "Commodity"       # Electricity, so far
COL_SUBSTATUS = "Contract Substatus"

# NOT the sale date: "Start Date" is when the SERVICE starts (APR 2027, JUN
# 2028). Reading a day's sales off it would return almost nothing today and a
# pile of contracts on some future morning.
COL_NOT_THE_SALE_DATE = "Start Date"

# 2622 contracts over 53 pages at 50 a page, so a read filters or sorts by
# Initiated Date rather than paging the grid looking for today. The header
# carries a sort and a per-column filter; which of those a headless read can
# drive is still to be established.
ROWS_PER_PAGE_MAX_SEEN = 50

# A SALE IS A STATUS, NOT A COUNTER. "It's not as easy as Sara plus to just
# see a number live" -- SaraPlus hands over a total; this hands over a list of
# contracts and the count is ours to make. So the definition of "sold" lives
# here, written down, rather than in whoever's head is reading the screen.
#
# Kept as a set of exact strings because a near-miss is the dangerous failure:
# a status we do not recognise is silently NOT counted, and an office's sales
# number comes out low with nothing to say why. See unknown_statuses().
# THE COLUMN IS "Contract Substatus", confirmed on screen 2026-09-15.
SEL_SUBSTATUS_COLUMN = "Contract Substatus"

# SUBSTATUSES SEEN ON THE LIVE GRID that Ryan's list did not mention. Recorded
# rather than decided: "Accepted by Supplier" reads as MORE complete than
# "Submitted to supplier", and if it is a sale and we do not count it then
# every Box office's number comes out low with nothing to say why.
#
# NOT added to COMPLETED_STATUSES until somebody who sells these says so.
# Guessing in the generous direction inflates a number people are paid on;
# guessing in the strict direction hides sales. Neither is ours to pick.
SEEN_BUT_UNDECIDED = (
    "Accepted by Supplier",
    "PDF Generated",
    "TPV Sent",
)

COMPLETED_STATUSES = frozenset({
    "tpv passed",
    "ready for booking",
    "in progress",
    "missing documents",
    "submitted to supplier",
})


def is_completed(status: str) -> bool:
    """Does this contract count as a sale?"""
    return (status or "").strip().lower() in COMPLETED_STATUSES


def unknown_statuses(statuses) -> list:
    """Statuses on the page that this file has never heard of.

    THE POINT IS TO NOTICE A NEW ONE. Box adding a status we do not know
    would quietly drop those contracts out of every Box office's sales count,
    and a number that is low for a reason nobody can see is the failure this
    whole system keeps producing. Reported, not guessed at.
    """
    seen, out = set(), []
    for s in statuses or []:
        low = (s or "").strip().lower()
        if not low or low in COMPLETED_STATUSES or low in seen:
            continue
        seen.add(low)
        out.append(s.strip())
    return sorted(out)


# TWO-FACTOR. Ryan, 2026-09-15: "It's still set on an Authenticator I can only
# have on a device." So there is no unattended first sign-in: a human has to
# be there with the code once.
#
# THE PLAN IS A PERSISTENT SESSION, not a stored secret. The office signs in
# during the install, with their authenticator in hand, into a browser profile
# that stays on their machine -- the same shape OwnerVille and AppStream
# already use here. The agent then reuses it, and only needs a person again if
# the session is dropped.
#
# Ryan has asked Box whether codes can be emailed instead. If they can, that
# is a second route and not a replacement: an emailed code still has to be
# read from somewhere, and a session that simply persists needs nothing.
NEEDS_HUMAN_FIRST_LOGIN = True


class AccountProblem(RuntimeError):
    """Something the office can fix, phrased for the office."""


def _is_password_reset(url: str) -> bool:
    """Did we land on the reset page instead of the app?

    A LOGIN THAT LANDS HERE IS NOT A LOGIN. SaraPlus taught this the
    expensive way: a session that lands on ResetPassword.aspx still renders a
    page, still parses, and reports every rep at zero -- which reads as a
    quiet day rather than a broken account.
    """
    return PASSWORD_RESET_PATH in (url or "").lower()


def signed_in(page) -> bool:
    """Are we past the login form?

    Asked of the page rather than assumed from a click: the sign-in button
    submitting is not the same as the credentials being accepted.
    """
    try:
        if _is_password_reset(page.url):
            return False
        return page.query_selector(SEL_PASSWORD) is None
    except Exception:  # noqa: BLE001
        return False


def sign_in(page, email: str, password: str, *,
            login_url: str = LOGIN_URL, log=print) -> str:
    """Sign in and return the URL we ended up on. Raises AccountProblem.

    The error text is written for the OFFICE OWNER, not for us: they are the
    only person who can fix a wrong password, and "authentication failed" in
    a log on their own Mac helps nobody.
    """
    page.goto(login_url, timeout=LOGIN_TIMEOUT_MS)
    page.fill(SEL_EMAIL, email)
    page.fill(SEL_PASSWORD, password)
    page.click(SEL_SUBMIT)
    try:
        page.wait_for_load_state("networkidle", timeout=LOGIN_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — a slow page is not a failed login
        pass

    if _is_password_reset(page.url):
        raise AccountProblem(
            "My Service Cloud is asking %s to reset its password, so nothing "
            "can be read until that is done. Sign in at %s in a normal "
            "browser, set the new password, then run the installer again to "
            "save it." % (email, login_url))
    if not signed_in(page):
        raise AccountProblem(
            "My Service Cloud did not accept the login for %s. If the "
            "password has changed, run the installer again and it will ask "
            "for the new one." % email)
    log("signed in to My Service Cloud as %s" % email)
    return page.url


# --- HOW BOX SALES BECOME SLACK ALERTS --------------------------------------
#
# Megan 2026-09-15: "we also want alerts for this like the sara slack alerts".
#
# THEY RIDE THE PATH THAT ALREADY EXISTS. The relay carries sales as
# {REP: {metric: count}} and icd_alerts.post.decide_sales() turns a change in
# that into one line per rep. Everything hard in there is metric-agnostic and
# was paid for the hard way:
#
#   * BASELINE -- the first sight of a day announces nothing, or an office
#     enrolling at 3pm declares every sale since lunchtime as if it just
#     landed.
#   * ONLY UP -- a short or half-rendered grid reads LOW, and believing it
#     would let the next good pass re-announce a sale already on the board.
#   * THE BACKLOG BURST -- several reps moving in one tick is a day being
#     handed over, not live activity (Cyrus, five sales announced at 14:18,
#     the oldest three hours stale).
#
# So a Box read that relays {REP: {...}} gets all of that free. Building a
# second alert path would mean rediscovering each of those rules with a real
# office's board as the test.
#
# THE ONE SEAM THAT IS AT&T-SHAPED: relay.SALE_METRICS and
# shared.sale_hype.METRICS are both hardcoded ("Int", "Int Up", "DTV", "NL"),
# and the hype wording and tiers are written around them. Box needs its own
# metric names, and those two need to become campaign-aware rather than
# constant. That is a small change and NOT one to make blind -- it decides
# what every AT&T office's sale line says.
#
# WHAT A BOX METRIC IS, still open. A contract is one sale; the grid also
# carries Commodity (Electricity so far) and Adjusted Annual Volume. Whether
# a Box office wants one number, a split by commodity, or volume alongside
# the count is a question for an office that sells them, not a guess from
# here.

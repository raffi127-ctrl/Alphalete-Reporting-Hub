"""Tick the "Blue Ink" checkbox for anyone whose packet is SIGNED.

Two different marks live in that one column, and they mean different things:

  light green background  we sent it            (mark.highlight, at send time)
  checkbox ticked         they have SIGNED it   (here)

Sending is a moment; signing happens whenever the person gets round to it. So
this is a separate pass that re-reads Blue Ink's own list and ticks whoever has
finished since last time. Safe to run as often as you like.

Only ever ticks ON. It never un-ticks: somebody may have checked a box by hand
for a packet sent before this report existed, and clearing that would be
deleting a colleague's work to satisfy our own view of the world.

TWO ROUTES to the same answer (2026-09-08). The API goes first, because no
session can expire out from under it; the browser is the fallback, and was the
only route before. The block above `_signed_on` explains why the API read is
safe on this plan and why the browser had to stay.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List

import gspread

from automations.blueink_docs import blueink
from automations.blueink_docs import config
from automations.blueink_docs import recent_ui
from automations.blueink_docs import session as S
from automations.blueink_docs.roster import NewStart

# Row prefixes on the dashboard list that mean "signed and finished".
DONE = {"completed", "complete", "signed"}

# How far back a completion counts (Megan 2026-08-24). The Completed column
# sorts newest first and runs to thousands of rows, so only the last week is
# this cohort; anything older belongs to an earlier one -- or to a rehire whose
# previous packet must not tick this week's box.
#
# Shorter than the duplicate check's 14 days on purpose: the two answer
# different questions. "Don't send them a second packet" wants to be generous
# about what counts as recent; "they have signed THIS week's packet" wants to
# be strict.
LOOKBACK_DAYS = 7

TRUTHY = {"true", "yes", "y", "1", "x", "✓"}


def _within(datestr: str, today: dt.date, days: int = LOOKBACK_DAYS) -> bool:
    """Is this row's date inside the window? An unreadable date does NOT count
    -- the opposite of the duplicate check, and deliberately. There, an
    unparseable date blocks a send (cautious). Here it would tick a box saying
    somebody signed, which is a claim we shouldn't make on a date we couldn't
    read."""
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            when = dt.datetime.strptime(datestr, fmt).date()
        except ValueError:
            continue
        return 0 <= (today - when).days <= days
    return False


def _is_done(text: str, today=None) -> bool:
    """Does this search result show a FINISHED packet, in the last week?

    The dashboard is three columns -- Draft / Sent / Completed -- and a search
    returns the person's rows from all of them. So "Complete" appearing is not
    enough on its own: a rehire could have signed something months ago while
    this week's packet sits unsigned.
    """
    today = today or dt.date.today()
    for status, datestr in recent_ui._ROW_RE.findall(text or ""):
        if status.lower() in DONE and _within(datestr, today):
            return True
    return False


_COMPLETE_RE = re.compile(
    r"Complete(\d{1,2}/\d{1,2}/\d{2,4})\s+(.+?)"
    r"(?=Complete\d|Sent\d|Draft\d|Started\d|Declined\d|Expired\d|$)")

# How many times to scroll the Completed pane. Each pass loads ~40 more rows;
# the default view holds 40 and reaches back ~4 days, 8 passes reached 3 weeks.
_SCROLL_PASSES = 8

_SCROLL_JS = """() => {
    const els = [...document.querySelectorAll('div')]
      .filter(e => e.scrollHeight > e.clientHeight + 50 && e.clientHeight > 200);
    const last = els[els.length - 1];      // Draft | Sent | Completed
    if (last) last.scrollTop = last.scrollHeight;
}"""


def scan_completed(page, today: dt.date = None) -> Dict[str, str]:
    """{normalised name: date} for every packet signed inside the window.

    ONE page read for the whole roster, rather than a search each. A search is
    ~10 seconds, so per-person cost 50+ people nearly ten minutes -- fine once
    on a Monday, hopeless for a sweep meant to run through the day. The
    Completed column already lists exactly what we need; it just has to be
    scrolled, since it loads 40 rows at a time.
    """
    today = today or dt.date.today()
    for _ in range(_SCROLL_PASSES):
        page.evaluate(_SCROLL_JS)
        page.wait_for_timeout(2200)
    text = " ".join((page.inner_text("body") or "").split())

    out: Dict[str, str] = {}
    for datestr, name in _COMPLETE_RE.findall(text):
        if not _within(datestr, today):
            continue
        name = name.strip()
        # Rows carry the signer's INITIALS after the name ("Cale Mckenna CM");
        # and an envelope nobody renamed reads "Raf Documents", which is a
        # label, not a person -- it can't match a roster name, so it falls out.
        name = re.sub(r"\s+[A-Z]{1,3}$", "", name).strip()
        if name:
            out.setdefault(_norm_name(name), datestr)
    return out


def _norm_name(s: str) -> str:
    from automations.blueink_docs.roster import _norm
    parts = [p for p in re.split(r"\s+", (s or "").strip()) if p]
    if len(parts) < 2:
        return ""
    return _norm(parts[-1]) + "|" + _norm(" ".join(parts[:-1]))


# --- Route 1: the API ------------------------------------------------------
# Added 2026-09-08, after the web session on Lucy 2 expired and the every-2h
# sweep sat dead all day while the sheet went stale.
#
# That expiry is NOT a bug to fix in code. Blue Ink is Google SSO, this repo is
# public, and the web session can SEND documents that cannot be recalled -- so
# `session.py --login` deliberately waits for a human, and it should keep doing
# that. But THIS pass only READS, and a read has its own route that no session
# can expire out from under.
#
# Why the read is safe on this plan: what 403s, and what bills against the
# 50/year Bulk Envelope allowance, is CREATING a bundle. `GET /bundles/` costs
# nothing and is already in production on two other paths -- recent.py's
# duplicate screen and apex_new_starts' onboarding pull. The SEND is untouched
# and still goes through the web app.
#
# This does not replace the browser. recent_ui.py's header records why the UI
# route exists at all: on 2026-08-24 no machine in the fleet had
# blueink-creds.json. So the API goes first, and anything that stops it -- no
# key, 401, 403, network -- falls through to exactly the code that ran before.

_API_PAGE_SIZE = 50
_API_PAGES = 6        # 300 bundles, newest first: weeks of cover for a sweep

# Bundle/packet fields that mean "this is when it was FINISHED", best first.
# The API spec is not explicit about which of these this account returns, and
# it could not be called from the machine this was written on, so each name is
# asked for in turn rather than betting on one.
_DONE_FIELDS = ("completed_at", "completed", "finished_at",
                "updated_at", "updated")


def _iso_date(val):
    """The date out of an API timestamp ('2026-09-08T14:03:11Z'), or None."""
    try:
        return dt.datetime.strptime(str(val or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _signed_on(bundle: dict, packet: dict):
    """(date, exact) -- when this packet was signed, and how sure we are.

    `exact` is False when all that could be found is the bundle's CREATION
    date. That still bounds the answer safely: a packet cannot be signed before
    it exists, so "created inside the window" proves "signed inside the
    window". But it is an EARLIER date than the truth, so the window it gets
    measured against is widened rather than narrowed -- erring the other way
    would leave a box unticked for somebody who really did sign.
    """
    for src in (packet, bundle):
        for f in _DONE_FIELDS:
            d = _iso_date((src or {}).get(f))
            if d:
                return d, True
    return _iso_date((bundle or {}).get("created")), False


def _stamp(d: dt.date) -> str:
    """m/d/yy -- the same shape the dashboard rows carry.

    Hand-built rather than strftime: '%-m' is Mac-only and every report here
    has to run on Windows too (the cross-platform rule in CLAUDE.md).
    """
    return "{}/{}/{:02d}".format(d.month, d.day, d.year % 100)


def _scan_completed_api(today: dt.date):
    """({email: date}, {name key: date}) for packets signed inside the window.

    ONE sweep of the bundle list for the whole roster, newest first -- the same
    shape apex_new_starts uses, and for the same reason: a per-person search
    would be ~50 calls for a 13-person week and rate-limit the account.

    `setdefault` is what makes newest win: a rehire can have two signed
    packets, and the one they signed most recently is the one that describes
    them now.
    """
    by_email = {}
    by_name = {}
    for page in range(1, _API_PAGES + 1):
        rows = blueink._results(blueink._request(
            "GET", "/bundles/",
            params={"page": page, "per_page": _API_PAGE_SIZE}))
        if not rows:
            break
        for b in rows:
            for pk in b.get("packets") or []:
                if str(pk.get("status")) != "co":
                    continue           # still out for signature
                when, exact = _signed_on(b, pk)
                if not when:
                    continue           # a date we can't read never ticks a box
                span = LOOKBACK_DAYS if exact else LOOKBACK_DAYS * 2
                if not 0 <= (today - when).days <= span:
                    continue
                stamp = _stamp(when)
                em = (pk.get("email") or "").strip().lower()
                if em:
                    by_email.setdefault(em, stamp)
                k = _norm_name(pk.get("name") or "")
                if k:
                    by_name.setdefault(k, stamp)
    return by_email, by_name


def find_completed_api(people: List[NewStart], today: dt.date = None):
    """{person key: date signed} read through the API -- or None if unusable.

    None and {} mean different things, and the caller depends on it. {} is "the
    API answered, nobody new has signed"; None is "this route isn't available
    here, use the browser". Returning {} on a failure would read as "nobody
    signed" and quietly stop ticking boxes -- the exact silence this change
    exists to end.

    Matched on EMAIL first and only then on name: the address is the one the
    packet was actually delivered to, so a match on it is proof, where a name
    match is a judgement about spelling.
    """
    today = today or dt.date.today()
    try:
        config.api_key()
    except Exception as exc:  # noqa: BLE001 -- no key here is a normal state
        print("Blue Ink API key not available on this machine ({}) -- "
              "using the browser session instead."
              .format(exc.__class__.__name__))
        return None
    try:
        by_email, by_name = _scan_completed_api(today)
    except Exception as exc:  # noqa: BLE001 -- 401/403/network all land here
        print("Couldn't read Blue Ink's list through the API ({}) -- "
              "using the browser session instead.".format(exc))
        return None
    out = {}
    for p in people:
        em = (p.email or "").strip().lower()
        stamp = (by_email.get(em) if em else None) or by_name.get(p.key)
        if stamp:
            out[p.key] = stamp
    return out



def _todo(people: List[NewStart]) -> List[NewStart]:
    """Everyone still worth looking up -- no point re-reading a ticked box."""
    return [p for p in people
            if p.blueink_col and (p.blueink_val or "").strip().lower() not in TRUTHY]


def find_completed(people: List[NewStart], headless: bool = True,
                   use_api: bool = True) -> Dict[str, str]:
    """{person key: date signed} for everyone whose packet is now signed.

    The API first; the browser when that route isn't available here. Both
    answer the same question -- only the browser one can be logged out.

    Skips anyone already ticked -- no point looking up what the sheet says.
    """
    todo = _todo(people)
    if not todo:
        return {}
    if use_api:
        done = find_completed_api(todo)
        if done is not None:
            return done
    return find_completed_ui(todo, headless=headless)


# --- Route 2: the web app (the only route before 2026-09-08) ---------------

def find_completed_ui(people: List[NewStart],
                      headless: bool = True) -> Dict[str, str]:
    """{person key: date signed}, read off the dashboard a person would use."""
    todo = _todo(people)
    if not todo:
        return {}
    with S._sync_api()() as pw:
        browser, ctx = S.open_context(pw, headless=headless)
        page = ctx.new_page()
        try:
            # Waits for the list to APPEAR rather than guessing a duration.
            # Three copies of this used a fixed sleep -- 6s in the probe, 12
            # here -- and on 2026-09-09 they disagreed about the very same
            # session on Lucy 2. See recent_ui.open_dashboard.
            recent_ui.open_dashboard(page)
            signed = scan_completed(page)
        finally:
            browser.close()
    return {p.key: signed[p.key] for p in todo if p.key in signed}


def tick(worksheet, people: List[NewStart], done_keys: Dict[str, str]) -> int:
    """Write TRUE into the Blue Ink cell for everyone in `done_keys`.

    One batched write -- a per-cell loop burns the Sheets quota and 429s the
    next report as well as this one.
    """
    targets = [p for p in people
               if p.key in done_keys and p.blueink_col and p.row]
    if not targets:
        return 0
    worksheet.batch_update(
        [{"range": gspread.utils.rowcol_to_a1(p.row, p.blueink_col),
          "values": [["TRUE"]]} for p in targets],
        value_input_option="USER_ENTERED")   # so the checkbox actually ticks
    return len(targets)

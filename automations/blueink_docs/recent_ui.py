"""Who already has a packet -- read off the WEB APP's own list.

Why not the API (recent.py): that path needs a private API key, and on
2026-08-24 no machine in the fleet had one -- Lucy 1, Lucy 2 and Lucy 3 all
answered "No such file: blueink-creds.json". API Access is an Enterprise-only
feature on this plan and both API send paths already 403, so leaning the
pre-send duplicate check on a credential nobody has is what turned the report
red on the day it shipped.

The web app is the route that demonstrably works: it is where the team's own
50-90 sends a week go, where this report's four 2026-08-24 packets went, and
Lucy 2 already holds a signed-in session for it. So this asks the same question
against the same screen a person would use.

THE SCREEN (mapped against the live app 2026-08-24)

  /dashboard/ is the list. /dashboard/bundles, /sent and /documents are all
  nub-notFound, and the sidebar is a router with no <a href> to follow.

  The search box is the one with placeholder "Search...". NOT
  `[data-tid=nub-listSearch] input` -- that wrapper holds the Date Range field
  too, and a selector ending in ` input` types into whichever comes first.

  Searched by email first, then -- only when the email came back clear -- by
  NAME, because the address on the sheet is not always the address the packet
  actually went to. Searching a signer's email narrows the list. Rows carry their own status as a
  prefix, e.g. "Sent8/24/26 Raf Documents AP". An address with nothing reads
  "No Envelopes" in every section and has no "Showing" anywhere:

    has a packet   Showing 2 of 2 Sent8/24/26 Raf Documents AP Sent8/24/26 Ange
    has none       No Envelopes Sent Sort:Sent No Envelopes Completed Sort:Sent

WHICH WAY TO BE WRONG. Over-blocking costs one person a same-day auto-send and
prints why; under-blocking mails somebody a second packet that cannot be
recalled. So anything this can't classify blocks.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List

from automations.blueink_docs import session as S
from automations.blueink_docs.roster import NewStart

APP_ROOT = "https://secure.blueink.com"
DASHBOARD = APP_ROOT + "/dashboard/"
SEARCH_SEL = "input[placeholder='Search...']"

NAV_TIMEOUT = 90_000
SEARCH_TIMEOUT = 45_000

# Same window the API check used: a packet from a previous WEEK shouldn't block
# this week's send, but "sent 3 days ago" always should. New starts run
# Monday-to-Monday, so a fortnight catches this cohort and still lets a rehire
# months later get docs.
LOOKBACK_DAYS = 14

# Row prefixes that mean "they have a live or finished packet". A draft was
# never delivered and a cancelled/declined/expired one genuinely needs
# replacing, so neither blocks.
BLOCKING = {"sent", "completed", "complete", "pending", "started", "new",
            "ready", "signed"}

_ROW_RE = re.compile(
    r"(Draft|Sent|Completed|Complete|Pending|Started|New|Ready|Signed|"
    r"Cancelled|Canceled|Declined|Expired|Failed|Voided)"
    r"(\d{1,2}/\d{1,2}/\d{2,4})")


def _search(page, term: str) -> str:
    """Type `term` into the list search and return the resulting body text.

    Clearing is page.fill(sel, "") -- pressing Meta+A/Control+A then Backspace
    did NOT clear the box, and the second search of the 2026-08-24 probe ran
    with 'zzz-nobody-has-this@example.invalidAngiep8k@gmail.com' in it. It
    happened to match nothing, so it happened to look right.

    The term is then TYPED, not filled: page.fill() sets the value without the
    keystrokes the app listens for, and the list never narrows.

    The selector is re-resolved on every call -- a search re-renders the list,
    so a handle held across searches is stale and throws.
    """
    # WAIT for the box, don't snap-check it. The list is rendered by the app
    # after load, so a query_selector the instant the page settles can miss it
    # -- which is exactly how the first live run reported "the app's layout
    # changed" against a layout that hadn't changed at all.
    try:
        page.wait_for_selector(SEARCH_SEL, timeout=SEARCH_TIMEOUT)
    except Exception:
        raise RuntimeError(
            "No search box on the Blue Ink dashboard after "
            + str(SEARCH_TIMEOUT // 1000) + "s -- the app's layout may have "
            "changed. Rerun `--probe-sent` and remap.")
    page.click(SEARCH_SEL)
    page.fill(SEARCH_SEL, "")
    page.type(SEARCH_SEL, term, delay=40)
    page.keyboard.press("Enter")
    page.wait_for_timeout(6000)
    return " ".join((page.inner_text("body") or "").split())


def _fresh(datestr: str, today: dt.date) -> bool:
    """Is this row inside the lookback window? An unparseable date counts as
    fresh -- see WHICH WAY TO BE WRONG."""
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            when = dt.datetime.strptime(datestr, fmt).date()
        except ValueError:
            continue
        return (today - when).days <= LOOKBACK_DAYS
    return True


def verdict(text: str, today: dt.date = None) -> str:
    """What the searched list says about this address: "" for nothing in the
    way, otherwise a short phrase naming what is blocking."""
    today = today or dt.date.today()
    rows = _ROW_RE.findall(text or "")
    for status, datestr in rows:
        if status.lower() in BLOCKING and _fresh(datestr, today):
            return status + " " + datestr
    if rows:
        return ""                      # only drafts / dead / stale rows
    # Nothing parsed. If the page still counted results, something matched that
    # this doesn't understand -- block rather than risk a duplicate.
    if "Showing" in (text or ""):
        return "a packet this report couldn't classify"
    return ""


ABSENT = "zzz-nobody-has-this@example.invalid"


def _canaries(page, known_sent: str, today: dt.date) -> None:
    """Prove the search still works BEFORE trusting a word it says.

    This reads a screen nobody versions, and it can break in two directions
    that both look like a clean run:

      it stops FILTERING  -- every search returns the whole list, so everyone
                             reads "already has a packet" and nobody is sent.
                             Annoying, visible, recoverable.
      it stops FINDING    -- every search returns nothing, so everyone reads
                             clear and the batch mails a second packet to
                             people who already have one. That cannot be undone,
                             and it is the exact failure this check exists to
                             prevent.

    So: an address that cannot exist must come back clear, and a packet WE sent
    and logged ourselves must come back blocked. Costs ~20s once per run.
    """
    if verdict(_search(page, ABSENT), today):
        raise RuntimeError(
            "Blue Ink's search isn't filtering -- an address that cannot exist "
            "came back with a packet. Everyone would look already-sent. "
            "Rerun `--probe-sent` and remap before trusting this.")
    if known_sent:
        if not verdict(_search(page, known_sent), today):
            raise RuntimeError(
                "Blue Ink's search can't find a packet this report sent itself "
                f"({known_sent}, in the Blue Ink Log) -- so a clear result "
                "means nothing right now, and sending would duplicate. Rerun "
                "`--probe-sent` and remap.")


def screen(people: List[NewStart], headless: bool = True,
           known_sent: str = "") -> Dict[str, str]:
    """{lowercased email: what is blocking} for everyone who already has one.

    `known_sent` is an address this report has already sent and logged -- the
    positive canary. Pass one whenever the ledger has any; without it the only
    check on the search is the negative one, and a search that finds NOTHING
    would sail through.

    One browser for the whole roster -- relaunching per person would turn a
    ~7-minute check into an hour.
    """
    out: Dict[str, str] = {}
    todo = [p for p in people if (p.email or "").strip()]
    if not todo:
        return out
    today = dt.date.today()
    sync_playwright = S._sync_api()
    with sync_playwright() as p:
        browser, ctx = S.open_context(p, headless=headless)
        page = ctx.new_page()
        try:
            page.goto(DASHBOARD, wait_until="domcontentloaded",
                      timeout=NAV_TIMEOUT)
            page.wait_for_timeout(6000)
            if "/login" in page.url:
                raise RuntimeError(
                    "The Blue Ink session on this machine has expired. At the "
                    "keyboard here run: python -m "
                    "automations.blueink_docs.session --login")
            _canaries(page, known_sent, today)
            for person in todo:
                email = person.email.strip()
                why = verdict(_search(page, email), today)
                if not why:
                    # The address on the sheet is clear -- but the sheet's
                    # address is not always the one the packet went to. Ignacio
                    # Lara was sent (and had already signed) as
                    # iamlara3333@gmail.com while row 10 said
                    # iamlara33@yahoo.com, so the email search saw nothing and
                    # he came back as "still to send" (2026-08-24). Sending
                    # would have mailed onboarding paperwork to whoever owns
                    # the address on the sheet, which is worse than a duplicate.
                    # So when the email is clear, ask the same question by NAME.
                    name = (person.name or "").strip()
                    if name:
                        hit = verdict(_search(page, name), today)
                        if hit:
                            why = ("same name already has " + hit +
                                   " (sent to a different address than the "
                                   "sheet's) -- check this is the same person")
                if why:
                    out[email.lower()] = why
        finally:
            browser.close()
    return out


# --- diagnostics ------------------------------------------------------------

def _tids(page, want: str = "", limit: int = 40) -> str:
    seen = []
    for el in page.query_selector_all("[data-tid]"):
        t = el.get_attribute("data-tid")
        if t and t not in seen and (not want or want in t.lower()):
            seen.append(t)
        if len(seen) >= limit:
            break
    return ",".join(seen)


def _chunks(label: str, text: str, size: int = 200, most: int = 4) -> None:
    """logtail hands back ~470 characters a call, so long text goes out in
    numbered pieces that can be grepped one at a time."""
    for i in range(0, min(len(text), size * most), size):
        print("PROBE " + label + str(i // size) + ": " + text[i:i + size])


def probe(email: str = "", headless: bool = True) -> int:
    """Show what the list says for a signer who HAS a packet and one who has
    none -- the check above is only meaningful if those read differently.

    ALWAYS returns 0. This hangs off a report card, and a non-zero exit
    publishes a FAILED run: the first two versions opened incidents against
    themselves on 2026-08-24 for a diagnostic that sends nothing.
    """
    try:
        return _probe(email, headless)
    except Exception as exc:
        print("PROBE crashed: " + type(exc).__name__ + ": "
              + str(exc).splitlines()[0][:200])
        return 0


def _probe(email: str, headless: bool) -> int:
    sync_playwright = S._sync_api()
    with sync_playwright() as p:
        browser, ctx = S.open_context(p, headless=headless)
        page = ctx.new_page()
        try:
            page.goto(DASHBOARD, wait_until="domcontentloaded",
                      timeout=NAV_TIMEOUT)
            page.wait_for_timeout(6000)
            if "/login" in page.url:
                print("PROBE session is DEAD -- rerun session.py --login")
                return 0
            print("PROBE tids=" + _tids(page, "list", 8))
            known = email or "Angiep8k@gmail.com"
            miss = "zzz-nobody-has-this@example.invalid"
            for label, term in (("HAS", known), ("NONE", miss)):
                try:
                    text = _search(page, term)
                except Exception as exc:
                    print("PROBE " + label + " search failed: "
                          + str(exc).splitlines()[0][:120])
                    continue
                print("PROBE " + label + " term=" + term
                      + " len=" + str(len(text))
                      + " verdict=" + repr(verdict(text)))
                _chunks(label.lower() + "body", text, most=2)
        finally:
            browser.close()
    return 0

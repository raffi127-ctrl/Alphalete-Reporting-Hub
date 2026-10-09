"""Pull AppStream's Source Report (p=702) for one office and date range.

No file download is involved: the rendered table carries the same columns as the
.xls export, so we scrape it and hand the HTML to parse.load_table.
"""
from __future__ import annotations

import re

BASE = "https://applicantstream.com/index.cfm"
# The rqst token CONTAINS HYPHENS — and the ownerville-SSO path mints tokens
# with UNDERSCORES (seen live 2026-08-31: rqst=7D55E286_A725_...). A pattern
# missing either separator truncates the token and every page then answers
# "Your login is timed out", which reads like an auth failure but is really a
# malformed URL.
TOKRE = re.compile(r'rqst=([A-Za-z0-9_\-]+)')


def token(page):
    m = TOKRE.search(page.url) or TOKRE.search(page.content())
    if not m:
        raise RuntimeError("no rqst token on %s" % page.url)
    return m.group(1)


def select_office(page, tok, office_id, timeout=60000):
    page.goto("%s?p=104&rqst=%s&newOfficeId=%s" % (BASE, tok, office_id), timeout=timeout)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1500)


def owner_name(page):
    m = re.search(r'Owner:\s*([^|\n]+)', page.inner_text("body"))
    return m.group(1).strip() if m else ""


# Submitting this form has TWO failure modes and they pull in opposite
# directions, so the order here is the whole design.
#
# 1. `page.click` has to prove the element is visible, stable and unobstructed
#    before it fires. 2026-08-24: Kinsey Guenther (11906) ran clean at 04:00
#    and then spent the full 30s default timeout on this input at 12:00, with
#    the element RESOLVED ("locator resolved to ...") and the click never
#    landing — an overlay or a late reflow ate it.
# 2. But the click is ALSO the only thing that runs an inline `onclick` on the
#    submit, and these ColdFusion forms lean on those. `form.requestSubmit(b)`
#    looked like the clean fix (it posts the submitter's name/value, unlike a
#    bare `form.submit()`) and it is what funnel_board settled on for its own
#    form — but per spec it dispatches NO click event, so any onclick is
#    skipped. Tried on 11906 and the report came back with no table at all.
#
# So: the normal path stays the click that has worked for a month, and the JS
# `.click()` is the ESCAPE HATCH for when actionability blocks it. A DOM click
# fires the same onclick and posts the same submitter as a real click; the one
# thing it skips is Playwright's visibility gate, which is exactly the thing
# that failed. requestSubmit is deliberately not used.
_JS_CLICK = "b => { b.click(); return true; }"


def _submit(page, timeout):
    sel = 'input[name="sbmtSrcReport"]'
    if page.query_selector(sel) is None:
        raise RuntimeError("Source Report form has no %s submit" % sel)
    try:
        page.click(sel, timeout=timeout)
        return "page.click"
    except Exception as e:  # noqa: BLE001 — blocked click, not a missing button
        print("     click blocked (%s) — posting from the page instead"
              % str(e).splitlines()[0][:70], flush=True)
        try:
            page.eval_on_selector(sel, _JS_CLICK)
            return "js click"
        except Exception:  # noqa: BLE001 — see below; the element is GONE
            # THE SUBMIT ALREADY LANDED (2026-09-04). The escape hatch itself
            # started failing with `Failed to find element matching selector
            # "input[name=sbmtSrcReport]"` — and that error is not what it looks
            # like. The guard at the top of this function proved the button was
            # there moments ago, so a button that is gone NOW can only mean the
            # page navigated away while we were clicking it: the click DID post
            # the form, and Playwright's actionability gate kept waiting on an
            # element that the response was already replacing.
            #
            # Which is why it hit exactly three of 29 offices — Khalil Mansour
            # (11901), Rafael Hidalgo (11280), Kinsey Guenther (11906) — and hit
            # them on BOTH attempts rather than flaking: their Source Reports
            # are the slow ones, so the post reliably outlives the 30s click
            # timeout. The other blocked clicks that morning (12 in all) were
            # rescued by the JS fallback because their forms were still on
            # screen. Nothing about those three pages changed; the timeout is
            # just shorter than their report takes.
            #
            # Raising here threw away a POST that had already succeeded and
            # left three offices' weeks untouched. Instead: say so and let the
            # caller scrape. If the post really did fail, _one_pass' own
            # "no Source Report table came back" says that truthfully a moment
            # later and the retry still runs — we lose nothing by looking.
            if page.query_selector(sel) is None:
                print("     …the form is already gone — the click posted before "
                      "it timed out; scraping the response", flush=True)
                return "click landed during timeout"
            raise


# Row count of the biggest table that carries the Source Report header — the same
# pick _one_pass scrapes, counted in-page so a poll costs one round-trip.
_TABLE_ROWS_JS = """() => {
  let n = 0;
  for (const t of document.querySelectorAll('table')) {
    if ((t.innerText || '').includes('Email Subject'))
      n = Math.max(n, t.querySelectorAll('tr').length);
  }
  return n;
}"""


# THE TABLE GETS ITS OWN BUDGET (2026-10-09). The 10-02 poll above reused the
# 120s load timeout, and Rafael Hidalgo (11280) still dropped at 1 AM on 10-07
# and 10-09 (10-08 only made it on the retry). It is never a 1 PM miss: the 1 PM
# pass runs the whole roster in ~5 min, the 1 AM pass takes ~18, and his report
# is the biggest on it (~230 raw rows, twice the next office). AppStream is just
# slower overnight than 30s click + networkidle + 120s. Five minutes only costs
# time on an office whose table has not arrived; a ready table still returns on
# the second poll.
TABLE_WAIT_MS = 300000


def _page_says(page):
    """One line on what the page showed when no table came back — so a miss is
    evidence (an error page? the form again? a login?) and not a guess."""
    try:
        url = page.url
    except Exception:  # noqa: BLE001
        url = "?"
    try:
        txt = page.evaluate("() => (document.body ? document.body.innerText : '')")
    except Exception:  # noqa: BLE001
        txt = ""
    txt = " ".join((txt or "").split())[:160]
    return "url=%s page=%r" % (url.split("rqst=")[0], txt)


def _wait_for_table(page, timeout, poll=2000):
    """Wait until the Source Report table is on the page AND has stopped growing.

    A FIXED 1.8s WAIT LOST RAFAEL HIDALGO (11280) ON 2026-10-02. His report is
    the slow one, so his post always takes the "click landed during timeout"
    path in _submit — and on that path the response is still being built when
    networkidle returns (it answers for the page we are leaving, not the one
    on its way). 1.8s later there was no table yet, both attempts, and the
    office dropped with "no Source Report table came back" at 01:39 — the same
    office that had pulled 68 rows fine at 17:00 the day before. So: poll for
    the table, and once it is there, require two equal row counts in a row so
    a half-streamed table is never scraped. Returns the last count (0 = never
    showed up; the caller raises the usual error)."""
    waited, last = 0, 0
    while waited <= timeout:
        try:
            n = page.evaluate(_TABLE_ROWS_JS)
        except Exception:  # noqa: BLE001 — mid-navigation: context was replaced
            n = 0
        if n and n == last:
            return n
        last = n
        page.wait_for_timeout(poll)
        waited += poll
    return last


# Group the report by Original Subject as well (Carlos 2026-10-02): subjects
# carry the posting's location, so same-title ads in different cities stay
# separate rows — "once the location changes it's a new ad". Off by default;
# ad_sales_board turns it on per run with --group-subject.
GROUP_SUBJECT = False


def _one_pass(page, tok, start, end, timeout):
    """A single load → set period → post → scrape cycle."""
    page.goto("%s?p=702&rqst=%s" % (BASE, tok), timeout=60000)
    page.wait_for_load_state("networkidle", timeout=45000)
    page.wait_for_timeout(900)
    owner = owner_name(page)
    # Checkboxes BEFORE the dates (Carlos, 2026-10-02): toggling them after
    # can reset the period fields on some office schemas.
    cb = page.query_selector("#breakDownByEmail")
    if cb and not cb.is_checked():
        cb.check()          # gives the Email Inbox column, needed for accounts
    if GROUP_SUBJECT:
        gb = page.query_selector("#groupByOriginalSubject")
        if gb is None:
            # id unknown on this schema — find the checkbox by its label text
            for c in page.query_selector_all("input[type=checkbox]"):
                try:
                    around = c.evaluate(
                        "e => (e.parentElement ? e.parentElement.innerText : '')")
                except Exception:  # noqa: BLE001
                    around = ""
                if "original subject" in (around or "").lower():
                    gb = c
                    print("     (subject checkbox found by label; id=%r)"
                          % c.get_attribute("id"), flush=True)
                    break
        if gb is None:
            raise RuntimeError("Group-by-Original-Subject checkbox not found "
                               "on this office's p=702 form")
        if not gb.is_checked():
            gb.check()
    page.fill("#startDate", start)
    page.fill("#endDate", end)
    # The visible inputs are mirrored into hidden mm/dd/yyyy fields the form posts.
    page.eval_on_selector("#startDate2", 'e=>e.value="%s"' % start.replace("-", "/"))
    page.eval_on_selector("#endDate2", 'e=>e.value="%s"' % end.replace("-", "/"))
    _submit(page, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=timeout)
    _wait_for_table(page, max(timeout, TABLE_WAIT_MS))
    best, n = None, 0
    for t in page.query_selector_all("table"):
        rows = len(t.query_selector_all("tr"))
        if rows > n and "Email Subject" in (t.inner_text() or ""):
            best, n = t, rows
    if best is None:
        print("     no table — %s" % _page_says(page), flush=True)
        raise RuntimeError("no Source Report table came back")
    return "<table>" + best.inner_html() + "</table>", owner, n


def source_report(page, tok, start, end, timeout=120000, attempts=2):
    """Run p=702 for start/end (mm-dd-yyyy) and return the table HTML.

    Retries the WHOLE pass, not just the post: a failed attempt leaves the page
    somewhere unknown (mid-navigation, or on an error page), so re-posting the
    old form throws on fields that are no longer there. Retrying here rather
    than at the office level means one flaky office costs a re-post instead of
    dropping its rows for the day — which is the difference between a silent
    self-heal and a Slack alert nobody can act on.
    """
    last = None
    for i in range(max(1, attempts)):
        try:
            return _one_pass(page, tok, start, end, timeout)
        except Exception as e:  # noqa: BLE001 — the retry is the whole point
            last = e
            if i + 1 < attempts:
                print("     retry %d/%d after: %s"
                      % (i + 1, attempts - 1, str(e).splitlines()[0][:90]), flush=True)
                page.wait_for_timeout(2500)
    raise last

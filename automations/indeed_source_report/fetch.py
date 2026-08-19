"""Pull AppStream's Source Report (p=702) for one office and date range.

No file download is involved: the rendered table carries the same columns as the
.xls export, so we scrape it and hand the HTML to parse.load_table.
"""
from __future__ import annotations

import re

BASE = "https://applicantstream.com/index.cfm"
# The rqst token CONTAINS HYPHENS. A [A-Za-z0-9]+ pattern truncates it and every
# page then answers "Your login is timed out", which reads like an auth failure
# but is really a malformed URL.
TOKRE = re.compile(r'rqst=([A-Za-z0-9\-]+)')


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


def source_report(page, tok, start, end, timeout=120000):
    """Run p=702 for start/end (mm-dd-yyyy) and return the table HTML."""
    page.goto("%s?p=702&rqst=%s" % (BASE, tok), timeout=60000)
    page.wait_for_load_state("networkidle", timeout=45000)
    page.wait_for_timeout(900)
    owner = owner_name(page)
    page.fill("#startDate", start)
    page.fill("#endDate", end)
    # The visible inputs are mirrored into hidden mm/dd/yyyy fields the form posts.
    page.eval_on_selector("#startDate2", 'e=>e.value="%s"' % start.replace("-", "/"))
    page.eval_on_selector("#endDate2", 'e=>e.value="%s"' % end.replace("-", "/"))
    cb = page.query_selector("#breakDownByEmail")
    if cb and not cb.is_checked():
        cb.check()          # gives the Email Inbox column, needed for accounts
    page.click('input[name="sbmtSrcReport"]')
    page.wait_for_load_state("networkidle", timeout=timeout)
    page.wait_for_timeout(1800)
    best, n = None, 0
    for t in page.query_selector_all("table"):
        rows = len(t.query_selector_all("tr"))
        if rows > n and "Email Subject" in (t.inner_text() or ""):
            best, n = t, rows
    if best is None:
        raise RuntimeError("no Source Report table came back")
    return "<table>" + best.inner_html() + "</table>", owner, n

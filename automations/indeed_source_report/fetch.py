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


# Post the form from the page instead of clicking the submit input.
#
# `page.click` has to prove the element is visible, stable and unobstructed
# before it will fire, and on this site that check is what fails — not the
# submit itself. 2026-08-24: Kinsey Guenther (11906) ran clean at 04:00 and
# then spent the full 30s default timeout on `input[name="sbmtSrcReport"]`
# at 12:00, with the element RESOLVED ("locator resolved to ...") and the
# click never landing. Same office, same form, four hours apart — an overlay
# or a late reflow ate the click, and one flaky office fails the whole run's
# alert. funnel_board hit this on the same site and stopped clicking too.
#
# requestSubmit(button) is the right call, NOT form.submit(): it fires the
# submit event and INCLUDES the submitter's name/value in the POST, exactly
# like a click, so `sbmtSrcReport` still reaches ColdFusion. A bare
# form.submit() would drop it — and it is shadowed anyway on forms that carry
# an input named "submit". The JS .click() fallback covers an old engine
# without requestSubmit; the Playwright click stays as the last resort so a
# page whose markup changed still gets the original path.
_SUBMIT_JS = """b => {
    if (!b.form) { b.click(); return "click(no form)"; }
    if (b.form.requestSubmit) { b.form.requestSubmit(b); return "requestSubmit"; }
    b.click();
    return "click";
}"""


def _submit(page, timeout):
    sel = 'input[name="sbmtSrcReport"]'
    if page.query_selector(sel) is None:
        raise RuntimeError("Source Report form has no %s submit" % sel)
    try:
        return page.eval_on_selector(sel, _SUBMIT_JS)
    except Exception:  # noqa: BLE001 — fall back to the original path
        page.click(sel, timeout=timeout)
        return "page.click"


def _one_pass(page, tok, start, end, timeout):
    """A single load → set period → post → scrape cycle."""
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
    _submit(page, timeout=30000)
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

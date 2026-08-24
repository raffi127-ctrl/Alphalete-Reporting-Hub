"""Who already has a packet -- read off the WEB APP's own Sent list.

Why not the API (recent.py): that path needs a private API key, and on
2026-08-24 no machine in the fleet had one -- Lucy 1, Lucy 2 and Lucy 3 all
came back "No such file: blueink-creds.json". API Access is an Enterprise-only
feature on this plan and both API send paths already 403, so leaning the
pre-send duplicate check on a credential nobody has is what turned the report
red. The web app is the route that demonstrably works: it is where the team's
own ~50-90 sends a week go, where this report's four 2026-08-24 packets went,
and Lucy 2 already holds a signed-in session for it.

So this asks the same question against the same screens a person would use:
open the bundle list, search the signer's email, read the statuses that come
back.

PROBE FIRST. The bundle list's markup is not mapped yet, so this module ships
with `probe()` -- run it on the machine that HAS the session and it reports
which URL is the list, what a row looks like, and whether the search box
narrows it. `python -m automations.blueink_docs.run --probe-sent`.
"""
from __future__ import annotations

from typing import Dict, List

from automations.blueink_docs import session as S
from automations.blueink_docs.roster import NewStart

APP_ROOT = "https://secure.blueink.com"

# The list has moved before and the app is a SPA, so try the plausible ones and
# report which actually rendered a table rather than hardcoding a guess.
CANDIDATE_URLS = [
    f"{APP_ROOT}/dashboard/bundles",
    f"{APP_ROOT}/dashboard/sent",
    f"{APP_ROOT}/dashboard/documents",
    f"{APP_ROOT}/dashboard/",
]

NAV_TIMEOUT = 90_000
STEP_TIMEOUT = 30_000


def _describe(page) -> str:
    """One compact line about what this page is showing."""
    rows = page.query_selector_all("tr")
    tids = []
    for el in page.query_selector_all("[data-tid]")[:40]:
        t = el.get_attribute("data-tid")
        if t and t not in tids:
            tids.append(t)
    return f"url={page.url} rows={len(rows)} tids={','.join(tids[:12])}"


def probe(email: str = "", headless: bool = True) -> int:
    """Describe the Sent list so the real reader below can be written against
    it. Prints a handful of compact lines -- `lucy logtail` only returns ~470
    characters at a time, so this stays deliberately terse."""
    sync_playwright = S._sync_api()
    with sync_playwright() as p:
        browser, ctx = S.open_context(p, headless=headless)
        page = ctx.new_page()
        try:
            best = None
            for url in CANDIDATE_URLS:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                    page.wait_for_timeout(3000)
                except Exception as exc:
                    print(f"PROBE {url} -> ERROR {str(exc).splitlines()[0][:80]}")
                    continue
                line = _describe(page)
                print(f"PROBE {line}")
                if "/login" in page.url:
                    print("PROBE session is DEAD -- rerun session.py --login")
                    return 1
                rows = page.query_selector_all("tr")
                if best is None and len(rows) > 1:
                    best = url
            if not best:
                print("PROBE no candidate URL rendered a table")
                return 1

            page.goto(best, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.wait_for_timeout(3000)
            print(f"PROBE list is {best}")
            for i, tr in enumerate(page.query_selector_all("tr")[:4]):
                txt = " ".join((tr.inner_text() or "").split())
                print(f"PROBE row{i}: {txt[:150]}")

            boxes = page.query_selector_all("input[type='search'], input[type='text']")
            print(f"PROBE search inputs: {len(boxes)}")
            if boxes and email:
                boxes[0].click()
                boxes[0].type(email, delay=40)
                page.wait_for_timeout(4000)
                trs = page.query_selector_all("tr")
                print(f"PROBE after search {email!r}: rows={len(trs)}")
                for i, tr in enumerate(trs[:3]):
                    txt = " ".join((tr.inner_text() or "").split())
                    print(f"PROBE hit{i}: {txt[:150]}")
        finally:
            browser.close()
    return 0


def screen(people: List[NewStart]) -> Dict[str, str]:
    """{email: what we saw} for everyone the Sent list already shows a packet
    for. Not wired yet -- probe() has to map the list first."""
    raise NotImplementedError(
        "recent_ui.screen is not mapped yet -- run "
        "`python -m automations.blueink_docs.run --probe-sent` on the machine "
        "with the Blue Ink session and write it against what that reports.")

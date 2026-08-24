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


def _tids(page, limit: int = 30) -> str:
    seen = []
    for el in page.query_selector_all("[data-tid]"):
        t = el.get_attribute("data-tid")
        if t and t not in seen:
            seen.append(t)
        if len(seen) >= limit:
            break
    return ",".join(seen)


def probe(email: str = "", headless: bool = True) -> int:
    """Describe the Sent list so the real reader below can be written against
    it. Deliberately terse -- `lucy logtail` returns ~470 characters a call.

    ALWAYS returns 0. This is a diagnostic on a report card: a non-zero exit
    publishes a FAILED run and opens an incident, which is what the first
    version did to itself on 2026-08-24.
    """
    sync_playwright = S._sync_api()
    with sync_playwright() as p:
        browser, ctx = S.open_context(p, headless=headless)
        page = ctx.new_page()
        try:
            # The app is a SPA with no <table>, so counting <tr> proves nothing
            # (v1 reported rows=0 everywhere). Read the SIDEBAR instead and let
            # the app say where its own bundle list lives.
            page.goto(f"{APP_ROOT}/dashboard/", wait_until="domcontentloaded",
                      timeout=NAV_TIMEOUT)
            page.wait_for_timeout(4000)
            if "/login" in page.url:
                print("PROBE session is DEAD -- rerun session.py --login")
                return 0
            print(f"PROBE landed={page.url}")
            for a in page.query_selector_all("a[href*='/dashboard']")[:20]:
                href = (a.get_attribute("href") or "").strip()
                txt_ = " ".join((a.inner_text() or "").split())[:40]
                tid = a.get_attribute("data-tid") or ""
                if href:
                    print(f"PROBE nav {href} | {txt_} | {tid}")

            for url in CANDIDATE_URLS:
                try:
                    page.goto(url, wait_until="domcontentloaded",
                              timeout=NAV_TIMEOUT)
                    page.wait_for_timeout(4000)
                except Exception as exc:
                    print(f"PROBE {url} ERROR {str(exc).splitlines()[0][:70]}")
                    continue
                body = " ".join((page.inner_text("body") or "").split())
                notfound = "nub-notFound" in (page.content() or "")
                print(f"PROBE page={url} notFound={notfound} "
                      f"len={len(body)} tids={_tids(page, 14)}")
                print(f"PROBE text: {body[:260]}")
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

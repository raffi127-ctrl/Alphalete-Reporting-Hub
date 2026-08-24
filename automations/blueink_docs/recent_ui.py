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


def _tids(page, want: str = "", limit: int = 40) -> str:
    """Distinct data-tid values, optionally only those containing `want`."""
    seen = []
    for el in page.query_selector_all("[data-tid]"):
        t = el.get_attribute("data-tid")
        if t and t not in seen and (not want or want in t.lower()):
            seen.append(t)
        if len(seen) >= limit:
            break
    return ",".join(seen)


def _chunks(label: str, text: str, size: int = 200, most: int = 12) -> None:
    """logtail hands back ~470 characters a call, so long text goes out in
    numbered pieces that can be grepped one at a time."""
    for i in range(0, min(len(text), size * most), size):
        print(f"PROBE {label}{i // size}: {text[i:i + size]}")


def probe(email: str = "", headless: bool = True) -> int:
    """Map the dashboard so the reader below can be written against it.

    ALWAYS returns 0. This is a diagnostic on a report card: a non-zero exit
    publishes a FAILED run and opens an incident, which is what the first
    version did to itself on 2026-08-24.

    What v2 established: every /dashboard/<name> guess (bundles, sent,
    documents) renders nub-notFound, and the sidebar holds no <a href> to
    follow -- it's a router. /dashboard/ itself is the real screen, so this
    reads THAT.
    """
    sync_playwright = S._sync_api()
    with sync_playwright() as p:
        browser, ctx = S.open_context(p, headless=headless)
        page = ctx.new_page()
        try:
            page.goto(f"{APP_ROOT}/dashboard/", wait_until="domcontentloaded",
                      timeout=NAV_TIMEOUT)
            page.wait_for_timeout(6000)
            if "/login" in page.url:
                print("PROBE session is DEAD -- rerun session.py --login")
                return 0
            print(f"PROBE landed={page.url}")
            print(f"PROBE navtids={_tids(page, 'nav')}")
            print(f"PROBE listtids={_tids(page, 'row')}|{_tids(page, 'bundle')}"
                  f"|{_tids(page, 'list')}|{_tids(page, 'table')}"
                  f"|{_tids(page, 'search')}")
            for i, inp in enumerate(page.query_selector_all("input")[:8]):
                print(f"PROBE input{i} name={inp.get_attribute('name')!r} "
                      f"type={inp.get_attribute('type')!r} "
                      f"ph={inp.get_attribute('placeholder')!r} "
                      f"tid={inp.get_attribute('data-tid')!r}")
            body = " ".join((page.inner_text("body") or "").split())
            print(f"PROBE bodylen={len(body)}")
            _chunks("dash", body)

            if email:
                boxes = page.query_selector_all(
                    "input[type='search'], input[type='text']")
                if boxes:
                    boxes[0].click()
                    boxes[0].type(email, delay=40)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(5000)
                    after = " ".join((page.inner_text("body") or "").split())
                    print(f"PROBE searched={email} len={len(after)}")
                    _chunks("hit", after, most=6)
                else:
                    print("PROBE no search input on the dashboard")
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

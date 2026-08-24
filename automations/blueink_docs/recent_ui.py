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


def _search(page, term: str) -> str:
    """Type `term` into the dashboard's list search and return the body text.

    The box is re-queried on every call ON PURPOSE: a search re-renders the
    list and the previous ElementHandle goes stale, which is what killed the
    second search of the 2026-08-24 probe run.
    """
    sel = "[data-tid='nub-listSearch'] input"
    if page.query_selector(sel) is None:
        sel = "input[placeholder='Search...']"
        if page.query_selector(sel) is None:
            return ""
    page.click(sel)
    page.fill(sel, "")
    page.fill(sel, term)
    page.keyboard.press("Enter")
    page.wait_for_timeout(5000)
    return " ".join((page.inner_text("body") or "").split())


def probe(email: str = "", headless: bool = True) -> int:
    """Map the dashboard's search so screen() can be written against it.

    ALWAYS returns 0, and now actually keeps that promise -- v4 said so in its
    docstring but let a stale-handle exception escape, which published a FAILED
    run and opened a second incident against a diagnostic that sends nothing.

    Established so far: /dashboard/<anything> is nub-notFound, the sidebar is a
    router with no <a href>, and /dashboard/ itself carries the list plus a
    search box at [data-tid=nub-listSearch] input. Searching a signer's email
    narrows it and the page reports "Showing N of M" -- Angelica Pedroza, the
    one person known to have been sent twice today, comes back "Showing 2 of 2".

    The open question is the NEGATIVE case: an address with no packet has to
    read differently, or screen() would block everybody.
    """
    try:
        return _probe(email, headless)
    except Exception as exc:                 # a probe must never fail the card
        print(f"PROBE crashed: {type(exc).__name__}: "
              f"{str(exc).splitlines()[0][:200]}")
        return 0


def _probe(email: str, headless: bool) -> int:
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

            for tag in ("envelope", "bundle", "row", "list", "status"):
                got = _tids(page, tag, 12)
                if got:
                    print(f"PROBE tid[{tag}]={got}")

            known = email or "Angiep8k@gmail.com"
            miss = "zzz-nobody-has-this@example.invalid"
            for label, term in (("HAS", known), ("NONE", miss)):
                try:
                    text = _search(page, term)
                except Exception as exc:
                    print(f"PROBE {label} search failed: "
                          f"{str(exc).splitlines()[0][:120]}")
                    continue
                mark = ""
                for needle in ("Showing", "No Envelopes"):
                    i = text.find(needle)
                    if i >= 0:
                        mark += f" | {text[i:i + 60]}"
                print(f"PROBE {label} term={term} len={len(text)}{mark}")
                _chunks(f"{label.lower()}body", text, most=4)
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

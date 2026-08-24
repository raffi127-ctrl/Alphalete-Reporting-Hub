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


SEARCH_SEL = "input[placeholder='Search...']"


def _search(page, term: str) -> str:
    """Type `term` into the dashboard's list search and return the body text.

    Three things this has to get right, all learned the hard way on 2026-08-24:

    Target the box by its PLACEHOLDER. [data-tid=nub-listSearch] wraps more
    than one input -- the Date Range field is in there too -- so a selector
    ending in ` input` resolves to whichever comes first and the search term
    went somewhere harmless. The list stayed at its unfiltered "Showing 40 of
    436" for a real signer and an absent address alike.

    Re-resolve it every call: a search re-renders the list, so a handle held
    across searches is stale and throws.

    And TYPE, don't fill: page.fill() sets the value without the keystrokes the
    app listens for, so the list never narrows.
    """
    if page.query_selector(SEARCH_SEL) is None:
        return ""
    page.click(SEARCH_SEL)
    page.keyboard.press("Meta+A")
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    page.type(SEARCH_SEL, term, delay=40)
    # Read the value back: proof the characters landed in the box we meant,
    # rather than inferring it from a list that may not have filtered.
    got = ""
    box = page.query_selector(SEARCH_SEL)
    if box is not None:
        got = box.get_attribute("value") or box.input_value() or ""
    print(f"PROBE typed={term!r} boxvalue={got!r}")
    page.keyboard.press("Enter")
    page.wait_for_timeout(6000)
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
                _chunks(f"{label.lower()}body", text, most=2)
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

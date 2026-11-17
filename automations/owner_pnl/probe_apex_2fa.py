"""READ-ONLY look: how does Apex offer the 2-step code? Text AND app, or one?

WHY (Eve, 2026-11-17). Lucy Eco will sign into the owner's Apex with an
auth-app key. The question before asking Jairo for anything: when the app is
turned on, does the owner keep getting his text message (two doors), or does
the app replace it (then the owner needs a code app too)? This looks at the
account / security pages in Carlos's warm Apex window on Lucy 2 and prints
what they say about 2-step, so the answer comes from Apex's own screen.

Under Lucy's Apex lock in "block" mode (icd_alerts.apex_guard): nothing that
could change anything leaves the browser. Only page loads -- no buttons are
clicked. Every digit and email in the printed text is masked (phone numbers,
pay). Opens its own tab and closes it; Carlos's window is left as it was.

    python -m automations.owner_pnl.probe_apex_2fa      # Lucy 2 only
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urljoin, urlsplit

# Pages that could hold the 2-step settings: links whose address or words say so.
HINT = re.compile(r"profile|account|security|setting|user|2fa|two|factor|mfa|"
                  r"auth|verif|password|login", re.I)
# Common routes tried too, in case the link sits behind a menu that needs a click.
GUESSES = ("/profile", "/account", "/my-account", "/settings", "/security",
           "/user/profile", "/users/profile", "/two-factor", "/2fa")
# Words that answer the question when they show up on a page.
KEYWORDS = re.compile(r"authenticator|text message|\bsms\b|two[- ]factor|2fa|"
                      r"two[- ]step|2[- ]step|verification|one[- ]time|"
                      r"google auth|qr", re.I)
SKIP = re.compile(r"logout|log-out|sign-?out", re.I)


def mask(text: str) -> str:
    """No phone numbers, no money, no emails in the log."""
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", text)
    return re.sub(r"\d", "#", text)


def candidates(base: str, links) -> list:
    """Same-site links whose address or text hints at account / 2-step,
    then the guessed routes; no logout, no repeats, in order."""
    host = urlsplit(base).netloc
    out, seen = [], set()
    for href, words in links:
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urljoin(base, href)
        if urlsplit(url).netloc != host or SKIP.search(href + " " + words):
            continue
        if HINT.search(href) or HINT.search(words):
            if url not in seen:
                seen.add(url)
                out.append(url)
    for g in GUESSES:
        url = urljoin(base, g)
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def keyword_lines(text: str, limit: int = 25) -> list:
    out = []
    for line in text.splitlines():
        t = " ".join(line.split())
        if t and KEYWORDS.search(t) and t not in out:
            out.append(t[:200])
    return out[:limit]


def main(argv=None) -> int:
    from automations.carlos_payroll_pull import run as AP
    from automations.icd_alerts import apex_guard as G

    AP.ensure_chrome()
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{AP.CDP_PORT}")
        ctx = browser.contexts[0]
        guard = G.install(ctx, "block")       # before anything loads
        page = ctx.new_page()
        try:
            page.goto(AP.APEX_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if AP.logged_out(page):
                print("probe: Apex is signed out on Lucy 2 -- nothing looked at")
                return 1
            # Fresh sessions show Apex's own "set up 2-step" box: read it first.
            first = keyword_lines(page.inner_text("body", timeout=10_000))
            if first:
                print("2-STEP WORDS ON THE HOME PAGE (before closing any box):")
                for h in first:
                    print("    " + mask(h))
            AP._dismiss_modal(page)
            links = page.eval_on_selector_all(
                "a[href]", "els => els.map(a => [a.getAttribute('href'), "
                "(a.innerText || a.getAttribute('aria-label') || '').trim()])")
            print("links on the home page (%d):" % len(links))
            for href, words in links:
                print("  %s  %s" % (mask(href or ""), mask(words)[:60]))
            found_any = False
            for url in candidates(page.url, links):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(3000)
                    text = page.inner_text("body", timeout=10_000)
                except Exception as e:  # noqa: BLE001
                    print("\n== %s: did not load (%s)" % (mask(url), type(e).__name__))
                    continue
                hits = keyword_lines(text)
                print("\n== %s  (now at %s)" % (mask(url), mask(page.url)))
                if hits:
                    found_any = True
                    print("  2-STEP WORDS ON THIS PAGE:")
                    for h in hits:
                        print("    " + mask(h))
                else:
                    print("  first lines: " + mask(" | ".join(
                        " ".join(l.split()) for l in text.splitlines()
                        if l.strip())[:400]))
            print("\nanswer found on a page: %s" % ("YES" if found_any else "NO"))
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
    print("lock stopped: %s" % (", ".join(
        "%s x%d" % kv for kv in sorted(guard.stopped.items())) or "nothing"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

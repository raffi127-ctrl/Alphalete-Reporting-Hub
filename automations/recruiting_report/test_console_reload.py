"""Where the rqst token comes from when the console has to be reloaded
(2026-09-18).

THE INCIDENT. On the 18:30 Daily Focus refill, one "Get Report" click hung for
its full 30s on Chan Park - LA's last week and left the page off the AppStream
console. `_switch_office` then found no #searchMC, called `_reload_console` to
recover — and `_reload_console` looked for the rqst token in `page.url`.

That is the one place it is never going to be. "Get Report" POSTs to
index.cfm, so every post-submit URL in that run's log is exactly

    https://applicantstream.com/index.cfm

with no rqst= on it, and the page is in that state for nearly the whole run. So
the reload fell through to a bare index.cfm — which is Login, which has no
switcher — and raised "#searchMC not present even after a console reload". Every
remaining office on the tab hit the same wall: Chan Park - LA, Chan Park - MS
and COEL REIF all dropped out of the fill off ONE flaked submit, and the tab
only came back when the next captainship logged in from scratch.

That fresh login is the tell. It restores the console by re-keying off the
saved rqst_<TOKEN> COOKIE (tableau_patchright._reuse_appstream_storage_state),
which is the recovery that works. `_console_tokens` asks the same cookies, so
the reload can do what the re-login was doing.

What's pinned here:
  • the token is found on a post-submit (tokenless) URL — the actual failure;
  • a URL token still wins, cookies only extend the list;
  • a token that loads WITHOUT #searchMC is stale and the next one is tried —
    a goto that returns is not a console that came back;
  • with no token anywhere, the old land-on-index.cfm behaviour is unchanged,
    so the caller's error still describes the page it is looking at;
  • _ensure_on_retention_report no longer raises on a tokenless URL.

Run:  python -m automations.recruiting_report.test_console_reload
      (or via pytest)

3.9-safe — the mini runs Python 3.9.
"""
from __future__ import annotations

import sys

from patchright.sync_api import TimeoutError as PWTimeout

from automations.recruiting_report import fetch_office as fo

CONSOLE = "https://applicantstream.com/index.cfm"

# The URL every "Get Report" submit leaves behind — verbatim from the
# 2026-09-18 log's "[picker] AFTER submit/navigation" lines.
POST_SUBMIT_URL = CONSOLE


class _Context:
    def __init__(self, cookies):
        self._cookies = cookies

    def cookies(self):
        return self._cookies


class _Page:
    """Stands in for the AppStream tab — only the calls the reload makes.

    `console_tokens` is the set of tokens this fake server would actually honour
    with a switcher; any other token loads a page with no #searchMC on it, which
    is what a stale rqst really does (Login renders, nothing errors)."""

    def __init__(self, url, cookies=(), console_tokens=(), goto_raises=()):
        self.url = url
        self.context = _Context(list(cookies))
        self._console_tokens = set(console_tokens)
        self._goto_raises = set(goto_raises)
        self.visited = []
        self._has_switcher = False

    def goto(self, url, **kw):
        self.visited.append(url)
        tok = ""
        if "rqst=" in url:
            tok = url.split("rqst=", 1)[1].split("&", 1)[0]
        if tok and tok in self._goto_raises:
            raise PWTimeout("navigation blew up for %s" % tok)
        self.url = url
        self._has_switcher = bool(tok) and tok in self._console_tokens

    def wait_for_selector(self, selector, timeout=None):
        if selector == "#searchMC" and not self._has_switcher:
            raise PWTimeout("no #searchMC here")
        return object()

    def wait_for_timeout(self, ms):
        return None


def _cookie(token):
    return {"name": "rqst_" + token, "value": "1", "domain": "applicantstream.com"}


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_token_found_on_a_post_submit_url():
    """THE BUG. Tokenless URL + a live cookie = the token is still found."""
    page = _Page(POST_SUBMIT_URL, cookies=[_cookie("LIVE-TOKEN-1")])
    _check(fo._console_tokens(page) == ["LIVE-TOKEN-1"],
           "cookie token not found on a post-submit URL: %r"
           % (fo._console_tokens(page),))


def test_url_token_wins_and_cookies_extend():
    page = _Page(CONSOLE + "?rqst=FROM-URL&p=701",
                 cookies=[_cookie("FROM-URL"), _cookie("FROM-COOKIE")])
    _check(fo._console_tokens(page) == ["FROM-URL", "FROM-COOKIE"],
           "URL token must come first and repeats must collapse: %r"
           % (fo._console_tokens(page),))


def test_no_tokens_anywhere():
    page = _Page(POST_SUBMIT_URL)
    _check(fo._console_tokens(page) == [], "invented a token out of nothing")


def test_cookie_probe_never_raises():
    """A recovery probe that throws would replace the reload with a crash."""
    class _Angry:
        def cookies(self):
            raise RuntimeError("context is gone")

    page = _Page(POST_SUBMIT_URL)
    page.context = _Angry()
    _check(fo._console_tokens(page) == [], "a dead context must read as no tokens")


def test_reload_recovers_the_console_from_a_cookie():
    """The regression itself: the 3 dropped sections all died right here."""
    page = _Page(POST_SUBMIT_URL, cookies=[_cookie("LIVE-TOKEN-1")],
                 console_tokens=["LIVE-TOKEN-1"])
    fo._reload_console(page)
    _check(page.visited == [CONSOLE + "?rqst=LIVE-TOKEN-1&p=701"],
           "expected one re-key off the cookie, got %r" % (page.visited,))
    _check(page._has_switcher, "console did not come back")


def test_reload_skips_a_stale_token_for_a_live_one():
    """A stale rqst serves Login without erroring — only #searchMC settles it."""
    page = _Page(POST_SUBMIT_URL,
                 cookies=[_cookie("STALE"), _cookie("LIVE-TOKEN-1")],
                 console_tokens=["LIVE-TOKEN-1"])
    fo._reload_console(page)
    _check(page.visited == [CONSOLE + "?rqst=STALE&p=701",
                            CONSOLE + "?rqst=LIVE-TOKEN-1&p=701"],
           "stale token was not stepped over: %r" % (page.visited,))
    _check(page._has_switcher, "console did not come back off the live token")


def test_reload_survives_a_goto_that_raises():
    page = _Page(POST_SUBMIT_URL,
                 cookies=[_cookie("EXPLODES"), _cookie("LIVE-TOKEN-1")],
                 console_tokens=["LIVE-TOKEN-1"], goto_raises=["EXPLODES"])
    fo._reload_console(page)
    _check(page._has_switcher, "a raising goto stopped the recovery")


def test_reload_with_no_token_still_lands_on_index():
    """Unchanged fallback, so `#searchMC not present` still names the real page."""
    page = _Page(POST_SUBMIT_URL)
    fo._reload_console(page)
    _check(page.visited == [CONSOLE],
           "lost the bare-index fallback: %r" % (page.visited,))


def test_ensure_on_report_no_longer_raises_on_a_tokenless_url():
    page = _Page(POST_SUBMIT_URL, cookies=[_cookie("LIVE-TOKEN-1")],
                 console_tokens=["LIVE-TOKEN-1"])
    fo._ensure_on_retention_report(page)
    _check(fo.RETENTION_REPORT_PAGE in page.url,
           "did not get back on the retention report: %r" % (page.url,))


def test_ensure_on_report_is_a_no_op_when_already_there():
    page = _Page(CONSOLE + "?rqst=LIVE-TOKEN-1&p=701")
    fo._ensure_on_retention_report(page)
    _check(page.visited == [], "navigated when it was already on the report")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001 — this IS the runner
            failed += 1
            print("FAIL %s: %s" % (t.__name__, e))
        else:
            print("ok   %s" % t.__name__)
    print("%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

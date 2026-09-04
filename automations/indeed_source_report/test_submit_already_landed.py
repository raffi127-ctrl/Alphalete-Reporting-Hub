"""A post that already succeeded must not be thrown away as a failure.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.indeed_source_report.test_submit_already_landed

WHAT THIS GUARDS (2026-09-04). Ad Sales Board alerted "3 of 29 office(s) did not
refresh" — Khalil Mansour (11901), Rafael Hidalgo (11280), Kinsey Guenther
(11906), all three with:

    Page.eval_on_selector: Failed to find element matching selector
    "input[name=\"sbmtSrcReport\"]"

That error reads like the page changed under us. It isn't. `_submit` proves the
button exists before it clicks, so a button that is gone by the time the JS
escape hatch runs can only mean the page navigated — i.e. the click DID post the
form, and Playwright's actionability gate went on waiting for an element the
response was already replacing.

Which is why it was those three and not a random three: their Source Reports are
the slow ones, so the post reliably outlives the 30s click timeout. It hit them
on BOTH attempts instead of flaking. The same log shows 12 blocked clicks that
morning; the ones on faster offices still had their form on screen, so the JS
fallback rescued them and nobody noticed.

The cost of raising was three offices' weeks left untouched for a POST that had
already succeeded.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.indeed_source_report import fetch

SEL = 'input[name="sbmtSrcReport"]'


class _Page:
    """Minimal stand-in for the Playwright page `_submit` drives."""

    def __init__(self, *, button_before=True, click_raises=False,
                 js_raises=False, button_after=False):
        self._button_before = button_before
        self._click_raises = click_raises
        self._js_raises = js_raises
        self._button_after = button_after
        self._clicked = False
        self.js_calls = 0

    def query_selector(self, sel):
        assert sel == SEL, sel
        if not self._clicked:
            return object() if self._button_before else None
        return object() if self._button_after else None

    def click(self, sel, timeout=None):
        self._clicked = True
        if self._click_raises:
            raise TimeoutError("Page.click: Timeout 30000ms exceeded.")

    def eval_on_selector(self, sel, js):
        self.js_calls += 1
        if self._js_raises:
            raise RuntimeError(
                'Page.eval_on_selector: Failed to find element matching '
                'selector "%s"' % SEL)


class TheHappyPathIsUnchanged(unittest.TestCase):

    def test_a_clean_click_never_touches_the_fallback(self):
        p = _Page()
        self.assertEqual(fetch._submit(p, timeout=1000), "page.click")
        self.assertEqual(p.js_calls, 0)

    def test_a_missing_button_up_front_still_raises(self):
        """The guard that catches a REAL page change stays exactly as it was."""
        p = _Page(button_before=False)
        with self.assertRaises(RuntimeError) as ctx:
            fetch._submit(p, timeout=1000)
        self.assertIn("has no", str(ctx.exception))

    def test_a_blocked_click_still_uses_the_js_escape_hatch(self):
        """The 2026-08-24 case — form still on screen, JS click rescues it."""
        p = _Page(click_raises=True, button_after=True)
        self.assertEqual(fetch._submit(p, timeout=1000), "js click")
        self.assertEqual(p.js_calls, 1)


class AVanishedFormMeansTheClickLanded(unittest.TestCase):
    """THE BUG — the exact 2026-09-04 shape."""

    def _submit(self):
        p = _Page(click_raises=True, js_raises=True, button_after=False)
        return fetch._submit(p, timeout=1000), p

    def test_it_does_not_raise(self):
        note, _p = self._submit()
        self.assertEqual(note, "click landed during timeout")

    def test_the_fallback_was_genuinely_attempted_first(self):
        """It must not short-circuit past the escape hatch — that hatch is what
        rescues the offices whose form IS still there."""
        _note, p = self._submit()
        self.assertEqual(p.js_calls, 1)


class AGenuineFallbackFailureStillRaises(unittest.TestCase):
    """Do not over-swallow: if the button is STILL on the page and the JS click
    blew up, something really is wrong and the caller must hear about it."""

    def test_button_still_present_plus_js_error_raises(self):
        p = _Page(click_raises=True, js_raises=True, button_after=True)
        with self.assertRaises(RuntimeError):
            fetch._submit(p, timeout=1000)


if __name__ == "__main__":
    unittest.main()

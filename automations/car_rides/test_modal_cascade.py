"""One failed edit must not fail every edit behind it.

2026-09-24, the 10:30 pass: `rodolfo` timed out waiting for the select2 search
box, apply_edit returned False with the Edit Layer modal still open, and the
seven territories after it all died on "<div id=territoryModal> intercepts
pointer events". 8 flags, 0 edits applied. The manifest is what made it
visible — those flags exit 3, which the wrapper publishes as `success`.

    python -m unittest automations.car_rides.test_modal_cascade -v
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.car_rides import run


class FakePage:
    """A page whose modal closes after `closes_after` dismiss attempts."""

    def __init__(self, open_now=True, closes_after=1):
        self.open = open_now
        self.left = closes_after
        self.keys: list[str] = []
        self.clicked: list[str] = []

    # --- the surface apply_edit / _dismiss_modal touch ---
    class _Keyboard:
        def __init__(self, page):
            self.page = page

        def press(self, key):
            self.page.keys.append(key)
            self.page._attempt()

    @property
    def keyboard(self):
        return FakePage._Keyboard(self)

    def _attempt(self):
        self.left -= 1
        if self.left <= 0:
            self.open = False

    def locator(self, sel):
        page = self

        class _Loc:
            first = None

            def click(self, timeout=None):
                page.clicked.append(sel)
                page._attempt()

        loc = _Loc()
        loc.first = loc
        return loc

    def wait_for_timeout(self, _ms):
        pass


class DismissModalTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(run, "_modal_open",
                                  side_effect=lambda p: p.open)
        patch.start()
        self.addCleanup(patch.stop)

    def test_nothing_open_is_free(self):
        p = FakePage(open_now=False)
        self.assertTrue(run._dismiss_modal(p, log=lambda m: None))
        self.assertEqual(p.keys, [])

    def test_escape_closes_it(self):
        p = FakePage(closes_after=1)
        self.assertTrue(run._dismiss_modal(p, log=lambda m: None))
        self.assertEqual(p.keys, ["Escape"])

    def test_a_select2_swallows_the_first_escape(self):
        """Inside an open select2 the first Escape closes the DROPDOWN and the
        modal stays put — which is why the second press exists."""
        p = FakePage(closes_after=2)
        self.assertTrue(run._dismiss_modal(p, log=lambda m: None))
        self.assertEqual(p.keys, ["Escape", "Escape"])

    def test_it_falls_back_to_the_close_control(self):
        p = FakePage(closes_after=3)
        self.assertTrue(run._dismiss_modal(p, log=lambda m: None))
        self.assertEqual(p.clicked, [run._MODAL_CLOSE])

    def test_a_stuck_modal_is_reported_not_hidden(self):
        said = []
        p = FakePage(closes_after=99)
        self.assertFalse(run._dismiss_modal(p, log=said.append))
        self.assertIn("will not close", said[0])

    def test_the_close_control_never_reaches_the_page_behind_it(self):
        """A miss here would click a territory row underneath the modal."""
        self.assertNotIn(":not(", run._MODAL_CLOSE)
        for part in run._MODAL_CLOSE.split(","):
            self.assertTrue(part.strip().startswith(".modal"), part)


class ApplyEditLeavesThePageClean(unittest.TestCase):
    """The three places a leftover modal used to poison the next territory."""

    def _source(self):
        import inspect
        return inspect.getsource(run.apply_edit)

    def test_it_clears_a_leftover_before_clicking_a_row(self):
        head = self._source().split("try:")[0]
        self.assertIn("_dismiss_modal", head)

    def test_both_failure_paths_dismiss(self):
        src = self._source()
        tails = [b for b in src.split("except Exception as e:")[1:]]
        self.assertEqual(len(tails), 2)
        for t in tails:
            self.assertIn("_dismiss_modal", t.split("return False")[0])


if __name__ == "__main__":
    unittest.main()

"""Launch a PINNED Chrome, not whatever Google shipped overnight.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_pinned_chrome

WHY (2026-09-01). Chrome auto-updated to 152.0.7977.65 at 01:45 and began
crashing — EXC_BREAKPOINT in ChromeMain on macOS 26.6.2, 26 crashes that day
against zero on every prior day. One crash took harvest_prime from 17/17 to
1/17; the same TargetClosedError killed the captainship reports,
fiber_activations, the B2B tracker boards and org_sales_board's delta boxes.

Every other fix that day mitigated the blast radius. This is the one that
removes the cause: pin the browser, installed beside the team's Chrome so
nobody's own browser is touched.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import os
import unittest
from pathlib import Path

from automations.shared import tableau_patchright as tp


class PinnedChromeTest(unittest.TestCase):

    def setUp(self):
        self._prev = os.environ.get("CHROME_BINARY")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._prev is None:
            os.environ.pop("CHROME_BINARY", None)
        else:
            os.environ["CHROME_BINARY"] = self._prev

    def test_no_pinned_build_means_the_launch_is_unchanged(self):
        """A machine nobody has set up must behave exactly as before."""
        os.environ.pop("CHROME_BINARY", None)
        if tp._pinned_chrome() is not None:
            self.skipTest("this machine HAS a pinned build installed")
        kw = tp._chrome_launch_kwargs({"headless": True})
        self.assertEqual(kw.get("channel"), "chrome")
        self.assertNotIn("executable_path", kw)

    def test_channel_and_executable_path_are_never_both_set(self):
        """Playwright treats them as mutually exclusive — sending both is an
        immediate launch error, which on these runners means a dead report."""
        os.environ["CHROME_BINARY"] = __file__      # any existing path
        kw = tp._chrome_launch_kwargs({"headless": True})
        self.assertIn("executable_path", kw)
        self.assertNotIn("channel", kw)

    def test_a_nonexistent_override_is_ignored_rather_than_fatal(self):
        """A typo'd CHROME_BINARY must fall back to the system Chrome, not take
        every browser report down with 'executable doesn't exist'."""
        os.environ["CHROME_BINARY"] = "/nope/not/here/chrome"
        if tp._pinned_chrome() is not None:
            self.skipTest("this machine HAS a pinned build installed")
        kw = tp._chrome_launch_kwargs({"headless": True})
        self.assertEqual(kw.get("channel"), "chrome")

    def test_the_base_kwargs_are_not_mutated(self):
        """The caller reuses `base` across the retry ladder."""
        base = {"headless": True}
        tp._chrome_launch_kwargs(base)
        self.assertEqual(base, {"headless": True})


if __name__ == "__main__":
    unittest.main()

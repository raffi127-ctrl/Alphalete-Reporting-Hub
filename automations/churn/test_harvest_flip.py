"""The harvest-cache flip on the shared churn runner (Megan 2026-08-25).

This module is where BOTH churn pulls happen for every caller — daily_metrics,
office_metrics (all 11 offices), rashad_metrics, aya_metrics, and hand runs —
so the switch lives here rather than in new_internet_churn / wireless_churn,
which have no process of their own on the scheduled path.

The payoff is office_metrics: `offices.CHURN_USE_ALL_OFFICE` is True, so all 11
offices pull the SAME two org-wide views and slice to their owner in Python.
That was 22 live pulls a day of 2 distinct views.

Pinned here:
  * main() turns the cache on by default
  * HARVEST_MODE=off in the environment still wins — rollback with no deploy
  * the flip happens BEFORE argument-driven early exits, so every path that
    reaches a pull has it set

That the views still hash to declared needs is pinned in
automations/harvest/test_cutover_coverage.py; the hit/miss/fallback seam itself
is pinned in automations/owners_metrics_churn/test_harvest_flip.py.

Run:  python -m automations.churn.test_harvest_flip   (or via pytest)

3.9-safe (no walrus, no match, no PEP-604 unions evaluated at runtime).
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock


class TestMainDefault(unittest.TestCase):
    def setUp(self):
        self._saved = dict((k, os.environ.get(k))
                           for k in ("HARVEST_MODE", "HARVEST_VERBOSE"))
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _harvest_mode_after_main(self):
        from automations.churn import run as churn_run
        # --skip-download with no cached CSV returns 1 before any Tableau, Sheet
        # or Slack work. The flip sits above the argument parser, so it has
        # already happened by then.
        with mock.patch.object(sys, "stdout", new=mock.MagicMock()):
            with mock.patch("pathlib.Path.exists", return_value=False):
                churn_run.main(["--skip-download"])
        return os.environ.get("HARVEST_MODE")

    def test_default_is_on(self):
        self.assertEqual(self._harvest_mode_after_main(), "on")

    def test_explicit_off_survives(self):
        os.environ["HARVEST_MODE"] = "off"
        self.assertEqual(self._harvest_mode_after_main(), "off")

    def test_verbose_is_set_so_the_morning_log_shows_cache_hits(self):
        self._harvest_mode_after_main()
        self.assertEqual(os.environ.get("HARVEST_VERBOSE"), "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)

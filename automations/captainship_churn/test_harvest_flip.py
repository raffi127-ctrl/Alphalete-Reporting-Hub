"""The harvest-cache flip on this report (Megan 2026-08-25).

Both of this report's views are already pulled every morning by harvest_prime
(order 8); this report ran at order 18 and scraped them again. Reading the cache
instead removes 2 duplicate Tableau accesses a day.

The seam itself (hit serves cache / miss falls through / off never consults the
adapter) is pinned in owners_metrics_churn.test_harvest_flip against the same
`_dl` shape. What is pinned HERE is the per-report switch, because that is what
differs between reports:

  * main() turns the cache on by default
  * HARVEST_MODE=off in the environment still wins -- a rollback with no deploy

That the two views actually still HASH to declared needs (a flip is a silent
no-op if they don't) is pinned in automations/harvest/test_cutover_coverage.py.

Run:  python -m automations.captainship_churn.test_harvest_flip  (or pytest)

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
        from automations.captainship_churn import run as cc_run
        # Stop right after the flip: --skip-download with no cached CSV returns 1
        # before any Tableau or Sheet work, and the flip sits above that.
        with mock.patch.object(sys, "stdout", new=mock.MagicMock()):
            with mock.patch("pathlib.Path.exists", return_value=False):
                cc_run.main(["--skip-download"])
        return os.environ.get("HARVEST_MODE")

    def test_default_is_on(self):
        self.assertEqual(self._harvest_mode_after_main(), "on")

    def test_explicit_off_survives(self):
        os.environ["HARVEST_MODE"] = "off"
        self.assertEqual(self._harvest_mode_after_main(), "off")


if __name__ == "__main__":
    unittest.main(verbosity=2)

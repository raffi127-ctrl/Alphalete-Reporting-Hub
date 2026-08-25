"""The harvest-cache flip on this report (Megan 2026-08-25).

Tableau flagged our account for over-use. harvest_prime already pulls all 19
churn views into the dated cache at order 8; this report runs at order 20 and
was re-scraping them, so it now reads the cache instead — worth ~11 of its 16
Tableau accesses a day (5 of its views aren't in the primed registry yet and
still go live).

What must stay true, because this report fills captains' churn numbers:

  (a) HARVEST_MODE=on  + a cache HIT  -> the cached file, NO live scrape
  (b) HARVEST_MODE=on  + a cache MISS -> falls through to the live scrape
  (c) HARVEST_MODE unset/off          -> live scrape, adapter never consulted
  (d) the adapter RAISING             -> still falls through to the live scrape
      (a broken cache must never take the report down)
  (e) main() turns it on by default, and HARVEST_MODE=off in the environment
      still wins — so a rollback needs no code change or deploy

Run:  python -m automations.owners_metrics_churn.test_harvest_flip  (or pytest)

3.9-safe (no walrus, no match, no PEP-604 unions evaluated at runtime).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from automations.owners_metrics_churn import pull

VIEW = "https://us-east-1.online.tableau.com/#/site/sci/views/WB/CHURN/g/X?:iid=1"
SHEET = "ICD Churn"


class _EnvGuard(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("HARVEST_MODE", "HARVEST_VERBOSE")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestDlCacheSeam(_EnvGuard):
    def _run(self, *, mode, cache_result=None, cache_raises=False):
        """_dl with the adapter and the live pull both stubbed. Returns
        (result, adapter_called, live_called)."""
        if mode is not None:
            os.environ["HARVEST_MODE"] = mode
        seen = {"adapter": 0, "live": 0}

        def _fake_try_cache(view_url, crosstab_sheet, out_path, **kw):
            seen["adapter"] += 1
            if cache_raises:
                raise RuntimeError("cache exploded")
            return cache_result

        def _fake_live(view_url, crosstab_sheet, out_path, **kw):
            seen["live"] += 1
            return Path("/live/pull.csv")

        fake_adapter = mock.Mock(try_cache_view=_fake_try_cache)
        fake_mod = mock.Mock(adapter=fake_adapter)
        with mock.patch.dict(sys.modules, {"automations.harvest": fake_mod,
                                           "automations.harvest.adapter": fake_adapter}):
            with mock.patch.object(pull, "_dcp", _fake_live):
                out = pull._dl(VIEW, SHEET, Path("/tmp/out.csv"))
        return out, seen["adapter"], seen["live"]

    def test_hit_serves_cache_and_skips_the_scrape(self):
        cached = Path("/cache/hit.csv")
        out, adapter_n, live_n = self._run(mode="on", cache_result=cached)
        self.assertEqual(out, cached)
        self.assertEqual(adapter_n, 1)
        self.assertEqual(live_n, 0, "a cache hit must not also scrape Tableau")

    def test_miss_falls_through_to_live(self):
        out, adapter_n, live_n = self._run(mode="on", cache_result=None)
        self.assertEqual(out, Path("/live/pull.csv"))
        self.assertEqual(adapter_n, 1)
        self.assertEqual(live_n, 1)

    def test_off_never_consults_the_cache(self):
        for mode in (None, "off", ""):
            with self.subTest(mode=mode):
                out, adapter_n, live_n = self._run(mode=mode, cache_result=Path("/cache/x"))
                self.assertEqual(out, Path("/live/pull.csv"))
                self.assertEqual(adapter_n, 0)
                self.assertEqual(live_n, 1)


class TestMainDefault(_EnvGuard):
    """main() flips it on, and an explicit off still wins (rollback with no deploy)."""

    def _harvest_mode_after_main(self):
        from automations.owners_metrics_churn import run as omc_run
        # Stop right after the flip: --only with no valid slug returns 1 before
        # any Tableau/Sheet work, and the flip sits above that.
        with mock.patch.object(sys, "stdout", new=mock.MagicMock()):
            omc_run.main(["--only", "definitely-not-a-slug"])
        return os.environ.get("HARVEST_MODE")

    def test_default_is_on(self):
        self.assertEqual(self._harvest_mode_after_main(), "on")

    def test_explicit_off_survives(self):
        os.environ["HARVEST_MODE"] = "off"
        self.assertEqual(self._harvest_mode_after_main(), "off")


if __name__ == "__main__":
    unittest.main(verbosity=2)

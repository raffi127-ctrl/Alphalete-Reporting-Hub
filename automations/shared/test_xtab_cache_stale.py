"""A cached Order Log export that is BEHIND is shared only within one pass:
past _XTAB_STALE_TTL_S it is a miss, so a retry re-downloads (2026-09-29)."""
import datetime as dt
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from automations.shared import tableau_patchright as tp

URL = "https://example/views/X/ORDERLOG/ALLREPS"
SHEET = "A.Order Log"


def _csv(day: dt.date) -> str:
    return "sp.Order Date (copy),Status Date,Rep\n%s,%s,A\n" % (
        day.strftime("%m/%d/%Y"), day.strftime("%m/%d/%Y"))


class StaleCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"METRICS_XTAB_CACHE": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _cache(self, text: str, age_s: float) -> Path:
        p = tp._xtab_cache_path(Path(self.tmp.name), URL, SHEET)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        t = time.time() - age_s
        os.utime(p, (t, t))
        return p

    def test_stale_and_old_is_a_miss(self):
        self._cache(_csv(dt.date.today() - dt.timedelta(days=2)), age_s=3600)
        self.assertIsNone(tp._xtab_cache_lookup(URL, SHEET, False))

    def test_stale_but_same_pass_is_a_hit(self):
        p = self._cache(_csv(dt.date.today() - dt.timedelta(days=2)), age_s=60)
        self.assertEqual(tp._xtab_cache_lookup(URL, SHEET, False), p)

    def test_fresh_and_old_is_a_hit(self):
        p = self._cache(_csv(dt.date.today() - dt.timedelta(days=1)), age_s=3600)
        self.assertEqual(tp._xtab_cache_lookup(URL, SHEET, False), p)

    def test_view_without_order_dates_is_a_hit(self):
        p = self._cache("Office,Sales\nA,3\n", age_s=3600)
        self.assertEqual(tp._xtab_cache_lookup(URL, SHEET, False), p)


if __name__ == "__main__":
    unittest.main()

"""Office-computer comparison of Indeed's check (Megan 2026-11-04)."""
import unittest

from automations.icd_alerts import resume_push as RP
from automations.oat_processing import run as OAT


class CfCompare(unittest.TestCase):
    def test_etime(self):
        self.assertEqual(RP._etime_min("05:09"), 5)
        self.assertEqual(RP._etime_min("02:05:09"), 125)
        self.assertEqual(RP._etime_min("1-02:05:09"), 1565)
        self.assertIsNone(RP._etime_min("junk"))

    def test_cf_stats_reset_with_the_session(self):
        OAT.CF_STATS.update({"opens": 3, "first": "auto"})
        OAT.reset_cf_session()
        self.assertEqual(OAT.CF_STATS, {})


class StuckChrome(unittest.TestCase):
    def test_raf_1105_errors_count_as_stuck(self):
        self.assertTrue(RP._is_stuck_chrome(TimeoutError(
            "BrowserType.connect_over_cdp: Timeout 180000ms exceeded.")))
        self.assertTrue(RP._is_stuck_chrome(RuntimeError(
            "Protocol error (Network.setCacheDisabled): Internal server "
            "error, session closed.")))

    def test_other_crashes_do_not_kill_chrome(self):
        self.assertFalse(RP._is_stuck_chrome(ValueError("bad office id")))
        self.assertFalse(RP._is_stuck_chrome(KeyError("start")))


if __name__ == "__main__":
    unittest.main()

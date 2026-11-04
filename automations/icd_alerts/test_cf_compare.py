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


if __name__ == "__main__":
    unittest.main()

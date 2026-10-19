"""A captain can skip section kinds its flavor carries (Atef's knocks, 2026-10-19)."""
import datetime as dt
import unittest

from automations.captainship_drafts import config


class SkipKinds(unittest.TestCase):
    MON = dt.date(2026, 10, 19)

    def test_atef_has_no_knock_sections(self):
        kinds = [k for _h, k in config.BY_KEY["atef"].sections_on(self.MON)]
        self.assertNotIn("daily_knocks", kinds)
        self.assertNotIn("knock_dispo", kinds)
        self.assertIn("churn_ni", kinds)

    def test_other_nds_captains_keep_them(self):
        kinds = [k for _h, k in config.BY_KEY["khalil"].sections_on(self.MON)]
        self.assertIn("daily_knocks", kinds)
        self.assertIn("knock_dispo", kinds)


if __name__ == "__main__":
    unittest.main()

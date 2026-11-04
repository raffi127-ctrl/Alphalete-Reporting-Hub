"""A captain can skip section kinds its flavor carries (Atef's knocks, 2026-10-19).

Atef was retired 2026-10-27, so the skip is checked on a copy of an NDS captain."""
import dataclasses
import datetime as dt
import unittest

from automations.captainship_drafts import config


class SkipKinds(unittest.TestCase):
    MON = dt.date(2026, 10, 19)

    def test_skipped_kinds_drop_out(self):
        cap = dataclasses.replace(
            config.BY_KEY["khalil"],
            skip_kinds=frozenset({"daily_knocks", "knock_dispo"}))
        kinds = [k for _h, k in cap.sections_on(self.MON)]
        self.assertNotIn("daily_knocks", kinds)
        self.assertNotIn("knock_dispo", kinds)
        self.assertIn("churn_ni", kinds)

    def test_other_nds_captains_keep_them(self):
        kinds = [k for _h, k in config.BY_KEY["khalil"].sections_on(self.MON)]
        self.assertIn("daily_knocks", kinds)
        self.assertIn("knock_dispo", kinds)

    def test_atef_retired(self):
        self.assertNotIn("atef", config.BY_KEY)


if __name__ == "__main__":
    unittest.main()

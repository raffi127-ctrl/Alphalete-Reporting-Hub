"""The per-owner ⏱ line: says where one owner's time went (2026-09-21).
Pure — no Sheets, no browser. Run:
    python -m unittest automations.focus_office_att.test_owner_timing"""
import unittest

from automations.focus_office_att.run_all_owners import _owner_timing_line


class OwnerTimingLine(unittest.TestCase):
    def test_full_owner_breaks_down_every_stage(self):
        marks = {"start": 30.0, "write": 130.0, "design": 150.0}
        line = _owner_timing_line(0.0, marks, 270.0)
        self.assertIn("4.5 min", line)
        self.assertIn("impersonate/nav 30s", line)
        self.assertIn("scrape 100s", line)
        self.assertIn("sheet write 20s", line)
        self.assertIn("design 120s", line)

    def test_owner_that_never_impersonated_shows_only_the_total(self):
        self.assertEqual(_owner_timing_line(0.0, {}, 42.0), "  ⏱ 0.7 min")

    def test_timeout_mid_scrape_charges_the_rest_to_scrape(self):
        line = _owner_timing_line(0.0, {"start": 10.0}, 300.0)
        self.assertIn("scrape 290s", line)
        self.assertNotIn("sheet write", line)


if __name__ == "__main__":
    unittest.main()

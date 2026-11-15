"""The Activation Revenue Overview on one picture: same four weeks, same
numbers as the two-picture thread version.

    python -m unittest automations.verizon_office.test_revenue_one
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.verizon_office import revenue as RV
from automations.verizon_office.test_order_log_tab import _file


class OneImageTest(unittest.TestCase):
    def test_four_weeks_newest_first_and_png_written(self):
        sv = _file()
        target = dt.date(2026, 11, 15)
        tabs, sub = RV.activation_tables(sv, target)
        self.assertEqual([t["label"] for t in tabs], ["11.8 - 11.14", "11.1 - 11.7", "10.25 - 10.31", "10.18 - 10.24"])
        # Diego's port line activated 11/11 -> this week's Activated $ (tier 4 port + premium plan + protect)
        this = {r["rep"]: r for r in tabs[0]["rows"]}
        self.assertEqual(this["Diego Chacon"]["posted"], 190 + 60 + 35 + 35)
        self.assertEqual(this["Will Bautista"]["pending"], 25)          # sold 11/8, not activated
        self.assertIn("Credico's statement is the pay", sub)
        out = RV.activation_revenue_one("Nicolas Murrugarra", sv, target, Path(tempfile.mkdtemp()))
        self.assertTrue(out.exists() and out.stat().st_size > 1000)
        self.assertTrue(out.name.endswith("_one.png"))

    def test_two_picture_version_unchanged(self):
        sv = _file()
        outs = RV.activation_revenue("Nicolas Murrugarra", sv, dt.date(2026, 11, 15), Path(tempfile.mkdtemp()))
        self.assertEqual([p.name[-10:] for p in outs], ["recent.png", "_older.png"])


if __name__ == "__main__":
    unittest.main()

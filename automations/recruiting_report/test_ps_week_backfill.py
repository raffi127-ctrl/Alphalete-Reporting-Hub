"""The arithmetic and the never-overwrite rule of ps_week_backfill, offline.

    python -m unittest automations.recruiting_report.test_ps_week_backfill
"""
import unittest

from automations.recruiting_report import ps_week_backfill as P

HDR = ["Owner Name", "Rep", "Product Type", "Mon", "Tue", "Wed", "Thu", "Fri",
       "Sat", "Sun", "Product Total"]
ROWS = [
    HDR,
    ["Nuri Burgos", "Total", "Total", "9", "9", "9", "9", "9", "9", "9", "63"],
    ["Nuri Burgos", "Ana Rep", "NEW INTERNET", "2", "1", "", "", "", "", "", "3"],
    ["Nuri Burgos", "Ana Rep", "WIRELESS", "1", "", "", "", "", "", "", "1"],
    ["Nuri Burgos", "Nuri Burgos", "VIDEO", "1", "1", "", "", "", "", "", "2"],
    ["Other Owner", "Bo Rep", "NEW INTERNET", "5", "", "", "", "", "", "", "5"],
]


class OfficeWeek(unittest.TestCase):
    def test_sums_weekdays_only_and_counts_selling_reps(self):
        got = P.office_week(ROWS, "nuri burgos")
        self.assertEqual(got["values"], {"New Internets": 3, "Upgrades": 0,
                                         "DTV": 2, "New Lines": 1})
        self.assertEqual(got["total_apps"], 6)
        self.assertEqual(got["headcount"], 2)            # Ana Rep + Nuri
        self.assertEqual(got["personal_production"], "2 DTV")


class NeverOverwrites(unittest.TestCase):
    def test_a_filled_cell_is_kept(self):
        grid = [["", "WE", "9/6/26"],
                ["", "New Internets", "41"],
                ["", "Upgrades", ""]]
        rows = {"new internets": 2, "upgrades": 3}
        res = {"values": {"New Internets": 3, "Upgrades": 1},
               "headcount": 0, "personal_production": ""}
        ups, wrote, kept = P.plan_week(grid, rows, 3, res)
        self.assertEqual([u["range"] for u in ups], ["C3"])
        self.assertTrue(any("already '41'" in k for k in kept))


if __name__ == "__main__":
    unittest.main()

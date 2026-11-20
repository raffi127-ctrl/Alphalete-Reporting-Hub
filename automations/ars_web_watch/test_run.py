import datetime as dt
import unittest

from automations.ars_web_watch import run

S, E = dt.date(2026, 11, 15), dt.date(2026, 11, 19)


class T(unittest.TestCase):
    def test_slug_matches_accented_tab(self):
        self.assertEqual(run.slug("Nicolás Luján"), "nicolas-lujan")
        self.assertEqual(run.slug("Drew Tepper New"), "drew-tepper-new")

    def test_ars_tab_counts_window_and_keeps_empty_tab(self):
        grid = [["Full Name", "Date 1st Rd"], ["a", "11/16/2026"], ["b", "11/01/2026"]]
        self.assertEqual(run.count_recent(grid, "Ellen Dent", "Date 1st Rd", S, E), {"ellen-dent": 1})
        old = [["Full Name", "Date 1st Rd"], ["b", "11/01/2026"]]
        self.assertEqual(run.count_recent(old, "Ellen Dent", "Date 1st Rd", S, E), {"ellen-dent": 0})

    def test_web_grid_groups_by_office_iso_dates(self):
        grid = [["id", "office", "Date 1st Rd"], ["1", "blue-mendoza", "2026-11-17"],
                ["2", "blue-mendoza", "2026-11-18"], ["3", "cody-cannon", "2026-11-02"]]
        self.assertEqual(run.count_recent(grid, "office", "Date 1st Rd", S, E), {"blue-mendoza": 2})

    def test_classify(self):
        web = {"a": 10, "b": 10, "c": 10, "d": 1}
        ars = {"a": 0, "b": 5, "d": 0}
        self.assertEqual(run.classify(web, ars), (["a"], ["c"]))


if __name__ == "__main__":
    unittest.main()

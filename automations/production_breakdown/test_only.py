"""`--only` fills one tab's Production Breakdown without rebuilding the rest.

    python -m unittest automations.production_breakdown.test_only
"""
import unittest

from automations.production_breakdown import run as R

TITLES = ["Recruiting", "_CSV_Input", "Template Fiber", "Hasani Lynch",
          "Nuri Burgos", "Austin Eldredge"]


class TabsToProcess(unittest.TestCase):
    def test_everyone_without_only(self):
        self.assertEqual(R.tabs_to_process(TITLES),
                         ["Hasani Lynch", "Nuri Burgos", "Austin Eldredge"])

    def test_only_one_tab_case_insensitive(self):
        self.assertEqual(R.tabs_to_process(TITLES, "nuri burgos "),
                         ["Nuri Burgos"])

    def test_only_never_reaches_a_non_icd_tab(self):
        self.assertEqual(R.tabs_to_process(TITLES, "Template Fiber"), [])


if __name__ == "__main__":
    unittest.main()

"""A week-pinned HTTP pull is judged against its Max Date, not the daily bar
(false stale thread on SARAPLUSSALESSUMMARYBYDAY, 2026-09-22)."""
import datetime as dt
import unittest

from automations.alphalete_org_report.tableau_http import _pinned_needs

TUE = dt.date(2026, 9, 22)


class PinnedNeeds(unittest.TestCase):
    def test_closed_week_needs_its_max_date(self):
        p = {"Min Date": "2026-09-14", "Max Date": "2026-09-20"}
        self.assertEqual(_pinned_needs(p, TUE), dt.date(2026, 9, 20))

    def test_current_week_keeps_daily_bar(self):
        p = {"Min Date": "2026-09-21", "Max Date": "2026-09-27"}
        self.assertIsNone(_pinned_needs(p, TUE))

    def test_max_date_equal_to_daily_bar_keeps_default(self):
        self.assertIsNone(_pinned_needs({"Max Date": "2026-09-21"}, TUE))

    def test_no_params_or_junk(self):
        self.assertIsNone(_pinned_needs(None, TUE))
        self.assertIsNone(_pinned_needs({}, TUE))
        self.assertIsNone(_pinned_needs({"Max Date": "soon"}, TUE))


if __name__ == "__main__":
    unittest.main()

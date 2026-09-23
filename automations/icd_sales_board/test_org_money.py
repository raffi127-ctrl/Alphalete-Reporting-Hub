"""DD + Overrides per ICD off the org tabs. No network."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_sales_board import org_money as OM


class WeekHeaderTests(unittest.TestCase):
    def test_the_tabs_own_date_spelling(self):
        self.assertEqual(OM._week(" 9.20.26 "), dt.date(2026, 9, 20))
        self.assertEqual(OM._week("12.28.25"), dt.date(2025, 12, 28))

    def test_anything_else_is_not_a_week(self):
        for bad in (" ICD ", " Total DD 2026 ", "", "9.20", "x.y.z"):
            self.assertIsNone(OM._week(bad), bad)


GRID = [
    [" ICD ", " Active ICD ", " Total DD 2026 ", " 9.20.26 ", " 9.13.26 "],
    [" Abel Draper ", " YES ", "$226,186.11", "", "$5,547.00"],
    [" Rafael Hidalgo ", " YES ", "$1.00", "$86,407.50", "$74,294.00"],
    # The overrides tab lists its leaders twice; section 1 comes first and is
    # the person's own figure.
    [" Rafael Hidalgo ", " YES ", "$9.99", "$1.00", "$2.00"],
]


class ReadTests(unittest.TestCase):
    def setUp(self):
        OM._CACHE.clear()

    def tearDown(self):
        OM._CACHE.clear()

    def _patched(self):
        ws = mock.Mock()
        ws.get_all_values.return_value = GRID
        book = mock.Mock()
        book.worksheet.return_value = ws
        return mock.patch("automations.recruiting_report.fill.open_by_key",
                          return_value=book)

    def test_weeks_are_found_by_header_not_position(self):
        with self._patched():
            got = OM._read("any")
        self.assertEqual(got["abeldraper"],
                         {dt.date(2026, 9, 20): "",
                          dt.date(2026, 9, 13): "$5,547.00"})

    def test_the_first_row_for_a_name_wins(self):
        with self._patched():
            got = OM._read("any")
        self.assertEqual(got["rafaelhidalgo"][dt.date(2026, 9, 20)],
                         "$86,407.50")

    def test_padding_and_case_do_not_matter(self):
        with self._patched():
            got = OM._read("any")
        self.assertIn("rafaelhidalgo", got)

    def test_a_tab_that_cannot_be_read_is_empty_not_a_crash(self):
        with mock.patch("automations.recruiting_report.fill.open_by_key",
                        side_effect=RuntimeError("no access")):
            self.assertEqual(OM._read("any"), {})

    def test_blank_cells_are_dropped_from_a_lookup(self):
        with self._patched(), \
             mock.patch.object(OM, "_names_for", return_value=["abeldraper"]):
            got = OM.for_icd("Abel Draper")
        # 9/20 was blank on the tab, so it is simply not there.
        self.assertEqual(list(got["Direct Deposit"]), [dt.date(2026, 9, 13)])


if __name__ == "__main__":
    unittest.main()

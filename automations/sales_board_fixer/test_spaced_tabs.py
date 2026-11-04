"""python -m unittest automations.sales_board_fixer.test_spaced_tabs"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.sales_board_fixer import spaced_tabs as S

TODAY = dt.date(2026, 11, 2)


class _Book:
    def __init__(self, sheets):
        self.sheets = sheets

    def fetch_sheet_metadata(self, params=None):
        return {"sheets": [{"properties": p} for p in self.sheets]}


class SpacedTest(unittest.TestCase):
    def test_cy_case_last_weeks_tab(self):
        self.assertEqual(S.spaced([" 10.26", "11.2", "10.19"], TODAY), [" 10.26"])

    def test_the_tabs_seen_on_real_boards(self):
        names = [" 11/08", "WE 11/1/26 ", "Copy of WE 11/1/26 "]
        self.assertEqual(S.spaced(names, TODAY), names)

    def test_double_space_inside_counts(self):
        self.assertEqual(S.spaced(["Sales Board  WE 11.1"], TODAY), ["Sales Board  WE 11.1"])

    def test_clean_names_stay_quiet(self):
        self.assertEqual(S.spaced(["10.26", "Sales Board WE 11.1", "11/08"], TODAY), [])

    def test_old_tabs_stay_quiet(self):
        self.assertEqual(S.spaced([" Sales Board 07/13", "WE 4.6.25 ", "WE 10/26/25 "], TODAY), [])

    def test_undated_tabs_stay_quiet(self):
        self.assertEqual(S.spaced(["Line Up ", "COLTEN - Leader Lanes "], TODAY), [])

    def test_window_edges(self):
        self.assertEqual(S.spaced([" 10.12", " 10.11", " 11.9", " 11.10"], TODAY),
                         [" 10.12", " 11.9"])

    def test_december_tab_read_in_january(self):
        self.assertEqual(S.spaced([" 12.29"], dt.date(2027, 1, 4)), [" 12.29"])

    def test_not_a_date(self):
        self.assertEqual(S.spaced([" 13.45"], TODAY), [])


class FindingsTest(unittest.TestCase):
    def test_hidden_tab_left_out_and_nothing_to_write(self):
        book = _Book([{"title": " 10.26"}, {"title": " 10.19", "hidden": True}])
        found = S.findings(book, TODAY)
        self.assertEqual([x.tab for x in found], [" 10.26"])
        self.assertFalse(found[0].fixable)


class TellOnceTest(unittest.TestCase):
    def test_each_tab_is_told_once(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "sub" / "told.json"
            self.assertEqual(S.new_ones(f, ["a", "b"]), ["a", "b"])
            self.assertEqual(S.new_ones(f, ["a", "b"]), [])
            self.assertEqual(S.new_ones(f, ["a", "c"]), ["c"])


if __name__ == "__main__":
    unittest.main()

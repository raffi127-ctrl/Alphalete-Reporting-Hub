"""PNL helpers — pure/offline, no sheet access.

    python -m unittest automations.commission_sheet.test_pnl
"""
import datetime as dt
import unittest

from automations.commission_sheet.pnl import (
    _as_date, _num, _split_name, banner_for, col_letter)


class WeekBanner(unittest.TestCase):
    def test_serial_date_from_pnl_a1(self):
        # PNL!A1 came back as 46264 for the 2026-08-30 week.
        self.assertEqual(_as_date(46264), dt.date(2026, 8, 30))

    def test_printed_dates(self):
        for text in ("Aug 30, 2026", "8/30/2026", "2026-08-30"):
            self.assertEqual(_as_date(text), dt.date(2026, 8, 30), text)

    def test_unreadable_date_raises(self):
        with self.assertRaises(ValueError):
            _as_date("week 35")

    def test_banner_is_unpadded(self):
        # The grid's banners read "WE 8/30" and "WE 1/4" — %-m is Mac-only, and
        # these reports have to run on Windows too.
        self.assertEqual(banner_for(dt.date(2026, 8, 30)), "WE 8/30")
        self.assertEqual(banner_for(dt.date(2026, 1, 4)), "WE 1/4")
        self.assertEqual(banner_for(dt.date(2026, 12, 27)), "WE 12/27")


class Numbers(unittest.TestCase):
    def test_currency_and_plain(self):
        self.assertEqual(_num("$1,803.00"), 1803.0)
        self.assertEqual(_num(1803), 1803.0)
        self.assertEqual(_num("0"), 0.0)

    def test_zero_is_a_value_but_blank_is_not(self):
        # A real 0 must be written; a blank must NOT overwrite anything.
        self.assertEqual(_num(0), 0.0)
        self.assertIsNone(_num(""))
        self.assertIsNone(_num(None))

    def test_spill_errors_are_not_numbers(self):
        self.assertIsNone(_num("#N/A (No matches are found in FILTER evaluation.)"))
        self.assertIsNone(_num("#REF!"))

    def test_parenthesised_negative(self):
        self.assertEqual(_num("($540.80)"), -540.80)


class Columns(unittest.TestCase):
    def test_letters(self):
        # WE 8/30 lives at DE/DF/DG.
        self.assertEqual(col_letter(0), "A")
        self.assertEqual(col_letter(6), "G")
        self.assertEqual(col_letter(108), "DE")
        self.assertEqual(col_letter(109), "DF")


class SplitName(unittest.TestCase):
    def test_two_and_three_part_names(self):
        self.assertEqual(_split_name("Chloe Johnson"), ("Chloe", "Johnson"))
        self.assertEqual(_split_name("Deavion Hunter Allen"),
                         ("Deavion", "Hunter Allen"))
        self.assertEqual(_split_name("Cher"), ("Cher", ""))


if __name__ == "__main__":
    unittest.main()

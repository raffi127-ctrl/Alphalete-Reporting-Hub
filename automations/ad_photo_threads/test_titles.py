"""python -m unittest automations.ad_photo_threads.test_titles"""
import unittest

from automations.ad_photo_threads.titles import TitleBook, norm, pretty

# Real spellings off Raf's tab, 2026-09-21.
SHEET = (
    ["AT&T Sales Agent, Arlington, TX,"] * 4
    + ["AT&T Sales Agent ? Arlington TX"] * 3
    + ["AT&T Sales Agent, McKinney, TX,"] * 5
    + ["AT&T Wireless Associate (Spanish), 2 locations"] * 6
    + ["AT&T Wireless Associate (Spanish) ? Frisco TX"] * 3
    + ["AT&T Enrollment Associate, Denton, TX,"] * 5
)


class TitleTests(unittest.TestCase):
    def setUp(self):
        self.book = TitleBook(SHEET)

    def test_separators_and_paste_junk_are_one_ad(self):
        a = self.book.resolve("AT&T Sales Agent, Arlington, TX,")
        self.assertEqual(a, self.book.resolve("AT&T Sales Agent ? Arlington TX"))
        self.assertEqual(a, self.book.resolve("New application for AT&T Sales Agent, Arlington, TX,"))
        self.assertEqual(a, self.book.resolve("AT&amp;T Sales Agent ? Arlington TX"))

    def test_cut_off_paste_folds_onto_its_one_ad(self):
        self.assertEqual(self.book.resolve("AT&T Sales Agent, Arlington, T"),
                         norm("AT&T Sales Agent, Arlington, TX"))

    def test_typo_folds(self):
        self.assertEqual(self.book.resolve("AT&T Erollment Associate, Denton, TX"),
                         norm("AT&T Enrollment Associate, Denton, TX"))

    def test_cut_off_of_two_ads_is_not_guessed(self):
        self.assertIsNone(self.book.resolve("AT&T Wireless Associate (Spanish)"))

    def test_different_city_is_a_different_ad(self):
        self.assertNotEqual(self.book.resolve("AT&T Sales Agent ? McKinney TX"),
                            self.book.resolve("AT&T Sales Agent ? Arlington TX"))

    def test_blank_is_none(self):
        self.assertIsNone(self.book.resolve("   "))

    def test_find_in_slack_line(self):
        line = ("Meghan Warnock: Arlington, customer service :white_check_mark: "
                "3 :star:, AT&amp;T Sales Agent ? Arlington TX")
        self.assertEqual(self.book.find_in_text(line), norm("AT&T Sales Agent Arlington TX"))

    def test_pretty(self):
        self.assertEqual(pretty("New application for AT&T Sales Agent ? Arlington TX,"),
                         "AT&T Sales Agent – Arlington TX")


if __name__ == "__main__":
    unittest.main()

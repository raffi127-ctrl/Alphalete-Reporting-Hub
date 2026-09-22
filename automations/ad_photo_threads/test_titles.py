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


class FirstNameFallbackTests(unittest.TestCase):
    def _c(self, name, ad="entry level assistant manager farmers branch tx"):
        from automations.ad_photo_threads import collect
        return collect.Candidate(name, "", "", "Qualify", "", "x", ad=ad)

    def setUp(self):
        from automations.ad_photo_threads.titles import TitleBook
        self.book = TitleBook(["Entry Level Assistant Manager – Farmers Branch TX"] * 3
                              + ["AT&T Sales Agent – Arlington TX"] * 3)
        self.ad = self.book.resolve("Entry Level Assistant Manager – Farmers Branch TX")
        self.msgs = [{"text": "3.15\nPedro Moreno - teacher - Entry Level Assistant "
                              "Manager – Farmers Branch TX\nStarla Kennedy - "
                              "AT&T Sales Agent – Arlington TX"}]

    def test_pedro_menendez_found_as_pedro_moreno(self):
        from automations.ad_photo_threads import collect
        pedro = self._c("Pedro Menendez", self.ad)
        starla = self._c("Starla Kennedy", self.book.resolve("AT&T Sales Agent – Arlington TX"))
        got = collect.first_name_matches(self.msgs, [pedro, starla], self.book)
        self.assertEqual([c.name for _, c in got[0]], ["Pedro Menendez"])
        self.assertEqual(pedro.alt_names, ["Pedro Moreno"])

    def test_not_taken_when_the_line_is_another_ad(self):
        from automations.ad_photo_threads import collect
        pedro = self._c("Pedro Menendez", self.book.resolve("AT&T Sales Agent – Arlington TX"))
        self.assertEqual(collect.first_name_matches(self.msgs, [pedro], self.book), {})

    def test_not_taken_when_two_pedros_share_the_ad(self):
        from automations.ad_photo_threads import collect
        two = [self._c("Pedro Menendez", self.ad), self._c("Pedro Alvarez", self.ad)]
        self.assertEqual(collect.first_name_matches(self.msgs, two, self.book), {})


if __name__ == "__main__":
    unittest.main()

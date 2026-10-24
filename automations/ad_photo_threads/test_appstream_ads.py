import datetime as dt
import unittest

from automations.ad_photo_threads import appstream_ads as aa


class ReportRowsTests(unittest.TestCase):
    """Eve 10/24: the ad off AppStream's "Sent to Call List" detail rows
    (First, Last, Email, Phone, Rating, Job Board, Date and Time, Ad)."""

    def row(self, first, last, ad):
        return [first, last, "x@y.com", "555", "", "Indeed", "10/13/2026 6:19 AM", ad]

    def test_one_ad_for_the_name(self):
        rows = [self.row("Antoinette", "Proveaux", "AT&T Sales Agent, McKinney, TX"),
                self.row("Bob", "Proveaux", "Customer Sales Associate, Plano, TX")]
        self.assertEqual(aa.ad_of(rows, "Antoinette Proveaux"), ["AT&T Sales Agent, McKinney, TX"])

    def test_wrapper_comes_off_and_repeats_fold(self):
        rows = [self.row("Carlo", "Palacio", "[Action required] New application for AT&T Team Member, Frisco, TX"),
                self.row("Carlo", "Palacio", "AT&T Team Member, Frisco, TX")]
        self.assertEqual(aa.ad_of(rows, "Carlo Palacio"), ["AT&T Team Member, Frisco, TX"])

    def test_two_ads_and_middle_names_and_accents(self):
        rows = [self.row("José Luis", "De la Cruz", "A, Dallas, TX"),
                self.row("Jose", "Cruz", "B, Irving, TX")]
        self.assertEqual(aa.ad_of(rows, "Jose Cruz"), ["A, Dallas, TX", "B, Irving, TX"])

    def test_one_word_name_or_short_row_is_nothing(self):
        self.assertEqual(aa.ad_of([self.row("Krystal", "Lee", "A")], "Krystal"), [])
        self.assertEqual(aa.ad_of([["Ana", "Lee"]], "Ana Lee"), [])

    def test_header_and_key(self):
        self.assertEqual(aa.header(dt.date(2026, 10, 3)), "Oct 3, 2026")
        self.assertEqual(aa.key(dt.date(2026, 10, 22), " Carlo Palacio "), "2026-10-22|carlo palacio")


class CollectUsesItTests(unittest.TestCase):
    """What a lookup kept puts the candidate on the ad's thread."""

    def test_found_ad_resolves(self):
        from automations.ad_photo_threads import collect
        from automations.ad_photo_threads.titles import TitleBook
        book = TitleBook(["AT&T Sales Agent, McKinney, TX"] * 3)
        c = collect.Candidate(name="Carlo Palacio", title_raw="", interviewer="", qualify="",
                              stars="", source="")
        d = dt.date(2026, 10, 22)
        found = {"2026-10-22|carlo palacio": "AT&T Sales Agent, McKinney, TX"}
        self.assertEqual(collect.appstream_ad(c, d, book, found=found),
                         book.resolve("AT&T Sales Agent, McKinney, TX"))
        self.assertIsNone(collect.appstream_ad(c, d, book, found={"2026-10-22|carlo palacio": ""}))
        self.assertIsNone(collect.appstream_ad(c, dt.date(2026, 10, 21), book, found=found))


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import unittest

from automations.ad_photo_threads import appstream_ads as aa


class AdsInTextTests(unittest.TestCase):
    """Eve 10/24: the ad off the Indeed mail kept on the AppStream record."""

    def test_reads_the_ad_after_the_wrapper(self):
        page = "Subject: [Action required] New application for AT&T Sales Agent, McKinney, TX\nFrom: Indeed"
        self.assertEqual(aa.ads_in_text(page), ["AT&T Sales Agent, McKinney, TX"])

    def test_cuts_the_date_after_the_subject(self):
        page = "New application for Entry Level Assistant Manager, Irving, TX   10/21/2026 3:14 PM"
        self.assertEqual(aa.ads_in_text(page), ["Entry Level Assistant Manager, Irving, TX"])

    def test_same_ad_twice_is_one_two_ads_are_two(self):
        page = ("New application for AT&T Team Member, Frisco, TX\n"
                "New application for AT&T Team Member, Frisco, TX\n"
                "New application for Customer Sales Associate, Plano, TX")
        self.assertEqual(len(aa.ads_in_text(page)), 2)

    def test_nothing_on_the_page(self):
        self.assertEqual(aa.ads_in_text("Applicant Info\nPhone"), [])

    def test_names_and_keys(self):
        self.assertEqual(aa.split_name("José  De la Cruz"), ("jose", "cruz"))
        self.assertEqual(aa.split_name("Krystal"), ("krystal", ""))
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

"""The by-day PDF is recognised under both names Adriana has used."""
import unittest

from automations.sci_campaigns import email_source as es


class ByDayNameTest(unittest.TestCase):
    def test_old_name(self):
        fn = "RANKED Residential Telecom Tracker W.E. 9.12 - Campaign Totals By Day.pdf"
        self.assertTrue(es._is_byday(fn))
        self.assertFalse(es._is_main(fn))

    def test_daily_production_name(self):
        # WE 9.26.2026, sent 10/5: same table, new file name.
        fn = "Daily Production W.E. 9.26.26.pdf"
        self.assertTrue(es._is_byday(fn))
        self.assertFalse(es._is_main(fn))

    def test_main_pdf(self):
        fn = "RANKED Residential Telecom Tracker W.E. 9.26.pdf"
        self.assertTrue(es._is_main(fn))
        self.assertFalse(es._is_byday(fn))

    def test_images_are_neither(self):
        fn = "RANKED Residential Telecom Tracker W.E. 8.22 - Campaign Totals By Day.jpg"
        self.assertFalse(es._is_byday(fn))
        self.assertFalse(es._is_main(fn))


if __name__ == "__main__":
    unittest.main()

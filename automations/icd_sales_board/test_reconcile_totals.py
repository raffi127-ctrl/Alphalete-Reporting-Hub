"""How each campaign's live total is added up. No network."""
import unittest

from automations.icd_sales_board import eco_feeds as E
from automations.icd_sales_board import reconcile as R

DAY = {"A": {"Int": 1, "Int Up": 2, "DTV": 0, "NL": 30},
       "B": {"Int": 1, "Int Up": 2, "DTV": 0, "NL": 20}}


def feed(campaign):
    return E.Feed("k", "Owner", campaign)


class LiveTotalTests(unittest.TestCase):
    def test_nds_counts_wireless_only(self):
        # Its Tableau view carries WIRELESS and nothing else, so anything
        # else on the live side is a unit that view can never show.
        self.assertEqual(R._live_total(feed("nds"), DAY), 50)
        self.assertEqual(R._live_total(feed("att_nds"), DAY), 50)

    def test_b2b_att_counts_every_product(self):
        self.assertEqual(R._live_total(feed("b2b_att"), DAY), 56)

    def test_box_counts_deals(self):
        self.assertEqual(
            R._live_total(feed("box"), {"A": {"Sales": 3, "Volume": 900}}), 3)

    def test_an_unknown_campaign_still_totals(self):
        self.assertEqual(R._live_total(feed("att"), DAY), 56)


if __name__ == "__main__":
    unittest.main()

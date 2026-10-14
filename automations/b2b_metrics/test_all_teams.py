"""Carlos's Tableau URLs open the B2B team filter to every team (2026-10-14:
"Carlos's Team" left the filter and his sections rendered blank).

    python -m unittest automations.b2b_metrics.test_all_teams
"""
import unittest
from urllib.parse import unquote

from automations.b2b_metrics import capture, offices, rep_boards


class AllTeams(unittest.TestCase):
    def test_carlos_urls_carry_every_team(self):
        o = offices.OFFICES["carlos"]
        for key in ("sales_metrics", "churn_wireless", "order_tiered_bonus",
                    "out_of_bounds"):
            url = unquote(capture._sliced_url(o, key))
            self.assertIn("B2B Captain's Teams (SFDC)=", url, key)
            for t in offices.B2B_ALL_TEAMS:
                self.assertIn(t, url, key)

    def test_owner_and_product_filters_survive(self):
        o = offices.OFFICES["carlos"]
        self.assertIn("Owner Name=Carlos Hidalgo",
                      unquote(capture._sliced_url(o, "sales_metrics")))
        self.assertIn("Product%20Type%20(Broken%20Out)=",
                      capture._sliced_url(o, "churn_wireless"))

    def test_other_offices_unchanged(self):
        o = offices.OFFICES["atef"]
        self.assertNotIn("Captain", unquote(capture._sliced_url(o, "churn_wireless")))

    def test_rep_board_churn_url(self):
        url = offices.with_all_teams(rep_boards.CHURN_VIEW + "?x=1")
        self.assertTrue(url.startswith(rep_boards.CHURN_VIEW + "?x=1&"))


if __name__ == "__main__":
    unittest.main()

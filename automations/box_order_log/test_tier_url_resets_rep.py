import unittest
from automations.box_order_log import tier_bonus as T


class TierUrlTest(unittest.TestCase):
    def test_url_slices_owner_and_resets_rep_filter(self):
        u = T.view_url("Ryan McSpadden")
        self.assertIn("Owner%20Name=Ryan%20McSpadden", u)
        self.assertIn("&Rep%20Name=&", u)   # empty value = (All), sticky state cleared


if __name__ == "__main__":
    unittest.main()

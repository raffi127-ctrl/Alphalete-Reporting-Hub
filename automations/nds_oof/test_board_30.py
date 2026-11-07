"""'Knocks Last 30 Min': knocks since the previous board (Carlos 2026-11-07)."""
import datetime as dt
import unittest

from automations.nds_oof import config as C
from automations.nds_oof import run as R

D = dt.date(2026, 11, 7)


class Since(unittest.TestCase):
    def test_first_board_counts_from_zero_then_deltas(self):
        rows = [{"Rep": "Ana Griffin", "Total Knocks": "12"},
                {"Rep": "Nathaly Benitez", "Total Knocks": "7"}]
        state = {}
        self.assertEqual(R.knocks_since_last(rows, state, D), {"Ana Griffin": 12, "Nathaly Benitez": 7})
        R.remember_board_knocks(rows, state, D)
        later = [{"Rep": "Ana Griffin", "Total Knocks": "20"},
                 {"Rep": "nathaly benitez", "Total Knocks": "6"},      # corrected down
                 {"Rep": "New Rep", "Total Knocks": "3"}]
        self.assertEqual(R.knocks_since_last(later, state, D),
                         {"Ana Griffin": 8, "nathaly benitez": 0, "New Rep": 3})

    def test_new_day_resets(self):
        rows = [{"Rep": "Ana Griffin", "Total Knocks": "5"}]
        state = {"last_board_knocks": {"ana griffin": 40}, "last_board_knocks_day": "2026-11-06"}
        self.assertEqual(R.knocks_since_last(rows, state, D), {"Ana Griffin": 5})

    def test_routes_split_for_the_test(self):
        from automations.b2b_dispositions import config as B
        self.assertTrue(C.BOARD_30_TEST)
        self.assertEqual(B.TEXT_ROUTES[(C.CAMPAIGN_LABEL, C.KIND_BOARD_30)], [B.TEXT_GROUP_ALL])
        self.assertEqual(B.TEXT_ROUTES[(C.CAMPAIGN_LABEL, C.KIND_BOARD)], [B.TEXT_GROUP_ATT])


if __name__ == "__main__":
    unittest.main()

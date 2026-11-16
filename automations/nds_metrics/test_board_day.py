"""Monday's NDS Revenue Board is the week that just closed (Carlos 2026-11-16:
"The revenue sales board you sent out should've been the Monday - Sunday")."""
import datetime as dt
import unittest

from automations.nds_metrics import revenue_extras as RX
from automations.vantura_revenue_board.run import week_of


class BoardDay(unittest.TestCase):

    def test_monday_shows_the_week_that_just_closed(self):
        asof = RX.board_day(dt.date(2026, 11, 16))          # a Monday
        self.assertEqual(asof, dt.date(2026, 11, 15))       # Sunday
        self.assertEqual(week_of(asof), dt.date(2026, 11, 9))

    def test_every_other_day_is_the_live_week(self):
        for d in range(17, 23):                             # Tue .. Sun
            day = dt.date(2026, 11, d)
            self.assertEqual(RX.board_day(day), day)
            self.assertEqual(week_of(RX.board_day(day)), dt.date(2026, 11, 16))


if __name__ == "__main__":
    unittest.main()

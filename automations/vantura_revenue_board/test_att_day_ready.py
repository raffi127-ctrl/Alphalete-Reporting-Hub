"""The AT&T Revenue Board holds for an empty day only while the export might
still be loading it. 2026-09-21: Carlos's office sold nothing on Sunday 9/20,
and the B2B Metrics runner held the board at 7:45 and 8:30 waiting for rows
that never existed — the section never posted.

    python -m unittest automations.vantura_revenue_board.test_att_day_ready
"""
import datetime as dt
import unittest

from automations.vantura_revenue_board import run as rb

SUN = dt.date(2026, 9, 20)


def _reps(days):
    return {"Aaron De La Torre": {"days": days, "elig": 0.0, "payable": 0.0}}


class AttDayReady(unittest.TestCase):

    def test_a_day_with_sales_is_ready_at_any_hour(self):
        self.assertTrue(rb.att_day_ready(_reps({SUN: 250.0}), SUN,
                                         dt.datetime(2026, 9, 21, 5, 20)))

    def test_an_empty_day_holds_while_the_export_may_still_load(self):
        self.assertFalse(rb.att_day_ready(_reps({}), SUN,
                                          dt.datetime(2026, 9, 21, 5, 50)))

    def test_an_empty_sunday_is_a_real_zero_by_the_745_run(self):
        # The exact morning that dropped the section.
        self.assertTrue(rb.att_day_ready(_reps({}), SUN,
                                         dt.datetime(2026, 9, 21, 7, 45)))

    def test_the_cutoff_is_the_standalone_boards_625(self):
        self.assertFalse(rb.att_day_ready(_reps({}), SUN,
                                          dt.datetime(2026, 9, 21, 6, 24)))
        self.assertTrue(rb.att_day_ready(_reps({}), SUN,
                                         dt.datetime(2026, 9, 21, 6, 25)))

    def test_other_days_sales_do_not_count_for_the_target_day(self):
        sat = SUN - dt.timedelta(days=1)
        self.assertFalse(rb.att_day_ready(_reps({sat: 900.0}), SUN,
                                          dt.datetime(2026, 9, 21, 6, 0)))


if __name__ == "__main__":
    unittest.main()

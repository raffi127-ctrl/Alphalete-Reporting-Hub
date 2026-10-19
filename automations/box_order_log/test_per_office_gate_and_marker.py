"""Per-office runs (2026-10-19, Ryan McSpadden): his team sold nothing Sat/Sun,
the per-office pass read the TEAM export via --from-file — where run.py never
asked "did the org sell that day?" — so his Monday thread was held as a stale
feed (and reported as Carlos's). And per-office runs claimed Carlos's day
marker, so on a machine where Carlos had posted, Ryan would be skipped.

    python -m unittest automations.box_order_log.test_per_office_gate_and_marker
"""
import datetime as dt
import unittest
from unittest import mock

from automations.box_order_log import day_marker, window as W

D = dt.date
MON = D(2026, 10, 19)
SUN = D(2026, 10, 18)
FRI = D(2026, 10, 16)


class GateTest(unittest.TestCase):
    def _block(self, org_sold_on):
        with mock.patch.object(W, "_extract_moved_today", return_value=False):
            return W.should_block_send(FRI, MON, org_sold_on=org_sold_on)

    def test_office_quiet_weekend_passes_when_the_team_file_has_sunday(self):
        team_days = {FRI, D(2026, 10, 17), SUN}      # Roshan sold Sunday
        self.assertEqual(self._block(lambda d: d in team_days), "")

    def test_still_blocks_when_nobody_in_the_org_has_sunday(self):
        team_days = {FRI}
        self.assertTrue(self._block(lambda d: d in team_days))

    def test_no_org_answer_keeps_the_old_block(self):
        self.assertTrue(self._block(None))


class MarkerTest(unittest.TestCase):
    def test_office_marker_is_not_carlos_marker(self):
        stem = day_marker.office_post_stem("C123")
        self.assertNotEqual(stem, day_marker.POST_STEM)
        self.assertIn("C123", stem)
        self.assertNotEqual(day_marker.path(stem, MON),
                            day_marker.path(day_marker.POST_STEM, MON))

    def test_two_offices_never_share_a_marker(self):
        self.assertNotEqual(day_marker.office_post_stem("C1"),
                            day_marker.office_post_stem("C2"))


if __name__ == "__main__":
    unittest.main()

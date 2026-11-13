"""Jairo's text-group standings also post to Slack every 3 sales (2026-11-13)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import config as C
from automations.icd_alerts import post as P


class Due(unittest.TestCase):
    def test_jairo_every_3_others_off(self):
        self.assertEqual(C.slack_standings_every("jairo15"), 3)
        self.assertEqual(C.slack_standings_every("ryan"), 0)

    def test_posts_at_each_multiple(self):
        self.assertEqual(P.slack_standings_due(0, 2, 3), (False, 0))
        self.assertEqual(P.slack_standings_due(0, 3, 3), (True, 1))
        self.assertEqual(P.slack_standings_due(1, 5, 3), (False, 1))
        self.assertEqual(P.slack_standings_due(1, 7, 3), (True, 2))  # 2 sales, one read

    def test_first_read_records_only(self):
        self.assertEqual(P.slack_standings_due(None, 10, 3), (False, 3))
        self.assertEqual(P.slack_standings_due(2, 10, 3, first_read=True), (False, 3))

    def test_drop_does_not_repost(self):
        self.assertEqual(P.slack_standings_due(2, 5, 3), (False, 2))
        self.assertEqual(P.slack_standings_due(2, 6, 3), (False, 2))

    def test_state_round_trip_and_day_rollover(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(P, "SLACK_STANDINGS_PATH", Path(d) / "s.json"):
                day = dt.date(2026, 11, 13)
                self.assertIsNone(P._slack_standings_step("jairo15", day))
                P._save_slack_standings_step("jairo15", day, 4)
                self.assertEqual(P._slack_standings_step("jairo15", day), 4)
                nxt = day + dt.timedelta(days=1)
                P._save_slack_standings_step("jairo15", nxt, 0)
                self.assertIsNone(P._slack_standings_step("jairo15", day))


if __name__ == "__main__":
    unittest.main()

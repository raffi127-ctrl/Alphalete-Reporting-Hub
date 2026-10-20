"""A Lucy restarts its own silent queue reader -- conservatively (2026-10-20).

    python -m unittest automations.day_orchestrator.test_queue_selfheal
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.day_orchestrator.queue_selfheal import should_kick

NOW = dt.datetime(2026, 10, 20, 19, 0)
M = lambda n: NOW - dt.timedelta(minutes=n)  # noqa: E731


class ShouldKick(unittest.TestCase):

    def test_silent_queue_is_kicked(self):
        self.assertTrue(should_kick(M(64), None, NOW))

    def test_fresh_beat_is_left_alone(self):
        self.assertFalse(should_kick(M(9), None, NOW))

    def test_unreadable_sheet_never_kicks(self):
        self.assertFalse(should_kick(None, None, NOW))

    def test_one_kick_per_half_hour(self):
        self.assertFalse(should_kick(M(64), M(10), NOW))
        self.assertTrue(should_kick(M(64), M(40), NOW))


if __name__ == "__main__":
    unittest.main()

"""A mint that keeps failing must ask for the restart that actually mints.

WHY (Megan 2026-08-31). The mint failed from ~15:05 to 19:21, every attempt
re-keying the SAME token — 66F074FE at 16:57 and again at 18:54 — because
ownerville's warm page hands back the token it already issued. For four hours
the holder logged "session stale — re-seed once" to itself, fed nothing to the
fleet, and paged a human at 18:43. It only recovered when an unrelated code push
restarted it at 19:21.

The restart is the cure and this file already knew it: on 8/29 a token hit
`1m left` at 08:04, the holder restarted at 08:10, and by 08:11 it was handing a
fresh one to the fleet — "the restart minted what four re-hop cycles could not."
Nothing connected that to a failing mint, so the holder sat there.

    python -m unittest automations.shared.test_holder_mint_restart -v
"""
from __future__ import annotations

import unittest

from automations.shared import session_holder as sh


class MintFailureCounting(unittest.TestCase):

    def setUp(self):
        sh._MINT_FAILURES.clear()
        sh._MINT_FAILURES["n"] = 0

    def test_a_single_miss_does_not_ask_for_a_restart(self):
        # One miss can be ownerville mid-refresh, which the replay fallback
        # rides out. Restarting on every blip would churn the fleet's session.
        self.assertEqual(sh._note_mint_result(False), 1)
        self.assertLess(1, sh.MINT_FAILURES_BEFORE_RESTART)

    def test_consecutive_misses_reach_the_threshold(self):
        sh._note_mint_result(False)
        self.assertGreaterEqual(sh._note_mint_result(False),
                                sh.MINT_FAILURES_BEFORE_RESTART)

    def test_a_success_clears_the_count(self):
        # The 8/31 failure was CONSECUTIVE. A mint that works between misses
        # means the holder is fine and must not be restarted for old history.
        sh._note_mint_result(False)
        sh._note_mint_result(True)
        self.assertEqual(sh._MINT_FAILURES["n"], 0)
        self.assertEqual(sh._note_mint_result(False), 1)

    def test_threshold_is_reached_well_inside_the_remint_margin(self):
        # Mints are throttled to one per MINT_MIN_INTERVAL_MIN, so the threshold
        # costs threshold*interval minutes. That has to fit inside the margin the
        # holder has before the token dies, or the restart arrives after the
        # outage it was meant to prevent.
        cost = sh.MINT_FAILURES_BEFORE_RESTART * sh.MINT_MIN_INTERVAL_MIN
        self.assertLessEqual(cost, sh.REMINT_MARGIN_MIN * 2 + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""The holder must never overwrite a FRESHER session than its own.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_holder_no_clobber

WHY (2026-09-01, watched live). Lucy 1 self-renewed its AppStream session to a
full 120 minutes at 15:17. Seconds later the file was back to AE4BC60A with 10
minutes on it — the token the holder had been carrying since a 13:28 push.

The holder re-exports its context every cycle. When that context holds an OLD
token and something else has just written a NEWER one, the export clobbers the
new session with the stale one — every six minutes. That is why renewals
appeared to work and then vanished, and why a person kept being asked to log in
again all day.

An export must move the session FORWARD.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import time
import unittest

from automations.shared import session_holder as sh


class BestRqstMinutesTest(unittest.TestCase):

    def test_reads_the_longest_lived_token(self):
        now = time.time()
        cookies = [{"name": "rqst_A", "expires": now + 600},
                   {"name": "rqst_B", "expires": now + 7200}]
        self.assertAlmostEqual(sh._best_rqst_minutes(cookies), 120, delta=1)

    def test_no_rqst_cookie_is_zero(self):
        self.assertEqual(sh._best_rqst_minutes(
            [{"name": "CFID", "expires": time.time() + 9999}]), 0.0)

    def test_a_session_cookie_carries_no_life_we_can_claim(self):
        """expires -1 means 'unknown', and calling that alive is how a dead
        token gets pushed to three machines."""
        self.assertEqual(sh._best_rqst_minutes([{"name": "rqst_A",
                                                 "expires": -1}]), 0.0)

    def test_empty_and_none_are_zero_not_a_crash(self):
        self.assertEqual(sh._best_rqst_minutes([]), 0.0)
        self.assertEqual(sh._best_rqst_minutes(None), 0.0)

    def test_the_stale_context_loses_to_the_fresh_file(self):
        """The exact 15:17 case: ours 10 min, disk 120 min — do not export."""
        now = time.time()
        ours = sh._best_rqst_minutes([{"name": "rqst_old", "expires": now + 600}])
        disk = sh._best_rqst_minutes([{"name": "rqst_new", "expires": now + 7200}])
        self.assertGreater(disk, ours + 1.0,
                           "a 10-minute context must not overwrite a "
                           "120-minute file")

    def test_a_fresher_context_still_exports(self):
        """The guard must not freeze the holder out of its normal job."""
        now = time.time()
        ours = sh._best_rqst_minutes([{"name": "rqst_new", "expires": now + 7200}])
        disk = sh._best_rqst_minutes([{"name": "rqst_old", "expires": now + 600}])
        self.assertFalse(disk > ours + 1.0)


if __name__ == "__main__":
    unittest.main()

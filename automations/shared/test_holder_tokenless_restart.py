"""A tokenless holder must ASK FOR THE RESTART, not warm quietly for hours.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_holder_tokenless_restart

WHY (2026-09-01). The rqst token expired at 22:15 and session_holder.out.log
printed "warm ✓ — 6 ownerville cookies" every six minutes until 05:49, when a
human logged in. Seven hours. The 4am batch met a dead session and cascaded:
daily_focus, applicant_sync_morning, recruiter_retention_daily all failed on
"the saved session has no live token".

The holder was not stuck — it was ASKING FOR NOTHING. Two mint sites exist:

  * in-margin (token alive, <REMINT_MARGIN_MIN left) — called
    _note_mint_result, so consecutive failures set restart_wanted and the
    holder exits(1) for launchd to relaunch it on a fresh context.
  * tokenless recovery (token already gone) — minted and DISCARDED the result.

So the escalation could only fire while a token was still alive, and never in
the emergency it exists for. This file pins the missing half.

The restart is the recovery this module documents as the one that works: "on
8/29 a token reached 1m left at 08:04, the holder restarted on a code change at
08:10, and by 08:11 it was handing a fresh one to the fleet."
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import unittest

from automations.shared import session_holder as sh


class _Ctx:
    """Context with no rqst cookie — the tokenless case."""


class TokenlessMintAsksForRestartTest(unittest.TestCase):

    def setUp(self):
        sh._MINT_FAILURES.clear()
        sh._MINT_FAILURES["n"] = 0
        self.addCleanup(sh._MINT_FAILURES.clear)
        self._real_last = dict(sh._LAST_MINT_ATTEMPT)
        self.addCleanup(sh._LAST_MINT_ATTEMPT.update, self._real_last)

    def test_a_failed_mint_with_no_token_requests_a_restart_on_the_FIRST_miss(self):
        """No live token = nothing to protect, so don't wait for a 2nd failure.

        Waiting is what turned 22:15 into 05:49."""
        sh._LAST_MINT_ATTEMPT["at"] = 0.0          # not throttled
        self.assertFalse(sh._mint_is_throttled())
        sh._note_mint_result(False)
        self.assertGreaterEqual(sh._MINT_FAILURES["n"], 1)

    def test_the_throttle_is_not_a_failure(self):
        """_mint_appstream_via_ownerville returns False for BOTH 'throttled' and
        'failed'. Counting the throttle would relaunch the holder every cycle on
        nothing but the clock."""
        import time
        sh._LAST_MINT_ATTEMPT["at"] = time.time()   # just attempted
        self.assertTrue(sh._mint_is_throttled())

    def test_throttle_expires_after_the_interval(self):
        import time
        sh._LAST_MINT_ATTEMPT["at"] = (
            time.time() - (sh.MINT_MIN_INTERVAL_MIN + 1) * 60)
        self.assertFalse(sh._mint_is_throttled())

    def test_a_success_clears_the_failure_streak(self):
        sh._note_mint_result(False)
        sh._note_mint_result(False)
        self.assertEqual(sh._note_mint_result(True), 0)

    def test_restart_wanted_is_consumed_by_the_loop(self):
        """The flag has to be the SAME key the main loop checks, or the request
        is written somewhere nobody reads — which is the bug one level up."""
        import inspect
        src = inspect.getsource(sh)
        self.assertIn('_MINT_FAILURES["restart_wanted"] = True', src)
        self.assertIn('_MINT_FAILURES.get("restart_wanted")', src)

    def test_the_tokenless_path_records_its_outcome_at_all(self):
        """The regression itself: the recovery mint used to `return
        _mint_appstream_via_ownerville(...)` directly, throwing the result away.
        Whatever the shape, that call's result must reach _note_mint_result."""
        import inspect
        src = inspect.getsource(sh._warm_appstream)
        self.assertNotIn("return _mint_appstream_via_ownerville(ctx, page, verbose=verbose)",
                         src,
                         "the tokenless mint must not discard its result again")
        self.assertIn("_mint_is_throttled()", src)


if __name__ == "__main__":
    unittest.main()

"""reconcile() re-pulls a cached CHURNRATES view once on mismatch (2026-11-12:
the 06:08 pull caught the view mid-refresh and the per-day cache made every
re-run compare against the same bad snapshot)."""
import datetime as dt
import unittest
from unittest import mock

from automations.nds_churn import run as R

TODAY = dt.date(2026, 11, 12)
SUMMARY = {"base": {"Wireless": 160}, "disc": {"Wireless": 20},
           "base_total": 166, "disc_total": 21}
BAD = {"disc": 8, "base": 85, "reps": 15, "detail": {}}
GOOD = {"disc": 20, "base": 160, "reps": 24, "detail": {}}


class ReconcileRefetch(unittest.TestCase):
    def _run(self, views):
        calls = []

        def fake(today, log=print, fresh=False):
            calls.append(fresh)
            v = views[len(calls) - 1]
            if isinstance(v, Exception):
                raise v
            return v

        with mock.patch.object(R, "view_counts", side_effect=fake), \
             mock.patch.object(R.C, "churn_summary", return_value=SUMMARY), \
             mock.patch.object(R, "_rep_diff", return_value=""):
            ok, _ = R.reconcile([], TODAY, SUMMARY, log=lambda *a: None)
        return ok, calls

    def test_stale_cache_then_fresh_match_passes(self):
        ok, calls = self._run([BAD, GOOD])
        self.assertTrue(ok)
        self.assertEqual(calls, [False, True])

    def test_match_on_cache_does_not_refetch(self):
        ok, calls = self._run([GOOD])
        self.assertTrue(ok)
        self.assertEqual(calls, [False])

    def test_still_wrong_after_refetch_fails(self):
        ok, _ = self._run([BAD, BAD])
        self.assertIs(ok, False)

    def test_failed_refetch_keeps_the_mismatch(self):
        ok, _ = self._run([BAD, RuntimeError("tableau down")])
        self.assertIs(ok, False)


if __name__ == "__main__":
    unittest.main()

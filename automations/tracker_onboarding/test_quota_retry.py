"""A Sheets read-quota 429 waits and retries the leg instead of BLOCKING it.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tracker_onboarding.test_quota_retry

2026-10-13: the 03:15 pass went BLOCKED on 'dispositions' with a 429 and the
11:27 hand rerun hit it on 'metrics' + 'dispositions'.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.tracker_onboarding import auto_commit as ac


class _Quota(Exception):
    def __init__(self):
        super().__init__("APIError: [429]: Quota exceeded for quota metric "
                         "'Read requests'")


class LegRetry(unittest.TestCase):
    def setUp(self):
        p = mock.patch("time.sleep")
        self.sleep = p.start()
        self.addCleanup(p.stop)

    def test_quota_then_ok_returns_the_legs_result(self):
        calls = iter([_Quota(), _Quota(), 0])

        def fn():
            v = next(calls)
            if isinstance(v, Exception):
                raise v
            return v
        self.assertEqual(ac._leg(fn), 0)
        self.assertEqual(self.sleep.call_count, 2)

    def test_quota_that_never_clears_still_raises(self):
        def fn():
            raise _Quota()
        with self.assertRaises(_Quota):
            ac._leg(fn, waits=(1, 1))
        self.assertEqual(self.sleep.call_count, 2)

    def test_other_errors_are_not_retried(self):
        def fn():
            raise ValueError("bad row")
        with self.assertRaises(ValueError):
            ac._leg(fn)
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

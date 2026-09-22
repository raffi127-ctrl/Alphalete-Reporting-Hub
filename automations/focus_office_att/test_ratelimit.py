"""The Sheets pacer/retry layer: paces to Google's per-USER cap, waits out a
429 visibly, and reports where the time went (2026-09-22). Pure — no Sheets.
Run:  python -m unittest automations.focus_office_att.test_ratelimit"""
import unittest
from unittest import mock

from automations.focus_office_att import _ratelimit as rl


class _Err(Exception):
    pass


def _fail_then_ok(fails, msg):
    calls = {"n": 0}

    def do(method, *a, **k):
        calls["n"] += 1
        if calls["n"] <= fails:
            raise _Err(msg)
        return "ok"
    return do, calls


class QuotaRetry(unittest.TestCase):
    def setUp(self):
        rl.take_stats()
        for q in rl._calls.values():
            q.clear()

    def test_429_is_waited_out_counted_and_printed(self):
        do, calls = _fail_then_ok(2, "APIError: [429]: Quota exceeded for quota metric "
                                     "'Read requests' and limit 'Read requests per minute per user'")
        with mock.patch.object(rl.time, "sleep") as sleep, \
                mock.patch("builtins.print") as out:
            self.assertEqual(rl._call(do, "GET", (), {}), "ok")
        self.assertEqual(calls["n"], 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],
                         [rl._RETRY_SLEEP, rl._RETRY_SLEEP])
        printed = " ".join(str(c.args[0]) for c in out.call_args_list)
        self.assertIn("429", printed)
        self.assertIn("read quota", printed)
        st = rl.take_stats()
        self.assertEqual(st["quota_waits"], 2)
        self.assertEqual(st["quota_wait_s"], 2 * rl._RETRY_SLEEP)
        self.assertEqual(rl.take_stats()["quota_waits"], 0, "take_stats resets")

    def test_429_that_never_clears_raises_after_the_budget(self):
        do, calls = _fail_then_ok(99, "[429]: Quota exceeded")
        with mock.patch.object(rl.time, "sleep"), mock.patch("builtins.print"):
            with self.assertRaises(_Err):
                rl._call(do, "GET", (), {})
        self.assertEqual(calls["n"], rl._MAX_RETRIES)

    def test_5xx_retries_without_counting_as_quota(self):
        do, calls = _fail_then_ok(1, "APIError: [503]: The service is currently unavailable")
        with mock.patch.object(rl.time, "sleep") as sleep:
            self.assertEqual(rl._call(do, "POST", (), {}), "ok")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleep.call_args_list[0].args[0], 1)
        self.assertEqual(rl.take_stats()["quota_waits"], 0)

    def test_other_errors_raise_at_once(self):
        do, calls = _fail_then_ok(1, "APIError: [403]: forbidden")
        with self.assertRaises(_Err):
            rl._call(do, "GET", (), {})
        self.assertEqual(calls["n"], 1)


class Pacing(unittest.TestCase):
    def setUp(self):
        rl.take_stats()
        for q in rl._calls.values():
            q.clear()

    def test_limits_are_the_per_user_caps(self):
        self.assertLessEqual(rl._READ_LIMIT_PER_MIN, 60)
        self.assertLessEqual(rl._WRITE_LIMIT_PER_MIN, 60)

    def test_read_bucket_holds_the_call_past_the_cap(self):
        clock = {"t": 1000.0}
        slept = []

        def fake_sleep(s):
            slept.append(s)
            clock["t"] += s
        with mock.patch.object(rl.time, "time", lambda: clock["t"]), \
                mock.patch.object(rl.time, "sleep", fake_sleep):
            for _ in range(rl._READ_LIMIT_PER_MIN):
                rl._pace("get")
            self.assertEqual(slept, [], "under the cap: no waiting")
            rl._pace("get")
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], rl._WINDOW, delta=0.1)
        self.assertAlmostEqual(rl.take_stats()["paced_s"], rl._WINDOW, delta=0.1)

    def test_writes_have_their_own_bucket(self):
        with mock.patch.object(rl.time, "sleep") as sleep:
            for _ in range(rl._READ_LIMIT_PER_MIN):
                rl._pace("get")
            rl._pace("post")
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

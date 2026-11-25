"""The Apex window waits out a busy profile, and a crash says what it was.

Jairo's finish window crashed 3 seconds after pnl's hourly check closed its
own browser on the same profile (2026-11-25 13:32), and the alert said only
"finish crashed (Error)".
"""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import apex_2fa_setup as S
from automations.icd_alerts import apex_signin as AS


class _G:
    @staticmethod
    def launch_args():
        return {}


class _Chromium:
    def __init__(self, fails):
        self.fails, self.calls = fails, 0

    def launch_persistent_context(self, *a, **k):
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError("Failed to create a ProcessSingleton")
        return "ctx"


class _P:
    def __init__(self, fails):
        self.chromium = _Chromium(fails)


class LaunchRetry(unittest.TestCase):
    def test_busy_profile_then_free(self):
        p = _P(fails=2)
        freed = []
        ctx = S.launch_window(p, "/x", _G, log=lambda *_: None, wait_s=0,
                              free=lambda d, log: freed.append(d))
        self.assertEqual(ctx, "ctx")
        self.assertEqual(p.chromium.calls, 3)
        self.assertEqual(freed, ["/x"])      # leftover holder ended ONCE

    def test_free_profile_launch_never_frees(self):
        freed = []
        S.launch_window(_P(fails=0), "/x", _G, log=lambda *_: None, wait_s=0,
                        free=lambda d, log: freed.append(d))
        self.assertEqual(freed, [])

    def test_never_frees_raises_the_real_error(self):
        p = _P(fails=99)
        with self.assertRaises(RuntimeError):
            S.launch_window(p, "/x", _G, log=lambda *_: None, wait_s=0,
                            free=lambda d, log: 0)
        self.assertEqual(p.chromium.calls, S.LAUNCH_TRIES)


class BoxesNeverHoldTheWindow(unittest.TestCase):
    """2026-11-25: the 12:27 finish window waited on "Apex wants one more
    click" (OK never pressed), kept the profile, and the next two crashed."""

    class _SlowAsk:
        def __init__(self):
            self.gate = threading.Event()

        def message(self, body, error=False):
            self.gate.wait(5)

    def test_say_returns_at_once(self):
        ask = self._SlowAsk()
        t0 = time.time()
        S.say(ask, "hi")
        self.assertLess(time.time() - t0, 1)
        ask.gate.set()

    def test_backup_photo_waits_for_ok(self):
        ask = self._SlowAsk()
        threading.Timer(0.3, ask.gate.set).start()
        t = S.say(ask, S.SAY_BACKUP, wait_s=3)
        self.assertFalse(t.is_alive())


class LockKnowsItsHolder(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.p = mock.patch.object(AS, "APEX_SIGNIN_LOCK", Path(d) / "l")
        self.p.start()

    def tearDown(self):
        self.p.stop()

    @unittest.skipIf(os.name == "nt", "pid check is Mac/Linux")
    def test_live_holder_is_open_however_old(self):
        AS.APEX_SIGNIN_LOCK.write_text("2026-11-25T12:27:00 %d" % os.getpid())
        self.assertTrue(AS.signin_open())

    @unittest.skipIf(os.name == "nt", "pid check is Mac/Linux")
    def test_dead_holder_is_not_open(self):
        AS.APEX_SIGNIN_LOCK.write_text("2026-11-25T12:27:00 999999")
        self.assertFalse(AS.signin_open())

    def test_old_lock_keeps_ten_minute_rule(self):
        import datetime as dt
        AS.APEX_SIGNIN_LOCK.write_text("2026-11-25T12:27:00")
        self.assertFalse(AS.signin_open(now=dt.datetime(2026, 11, 25, 12, 40)))
        self.assertTrue(AS.signin_open(now=dt.datetime(2026, 11, 25, 12, 30)))

    def test_mark_open_writes_pid(self):
        AS.mark_open()
        self.assertTrue(AS.APEX_SIGNIN_LOCK.read_text().endswith(" %d" % os.getpid()))


class CrashLine(unittest.TestCase):
    def test_summary_carries_the_message(self):
        try:
            raise RuntimeError("Target page, context or browser has been closed\nmore")
        except RuntimeError as e:
            summary, detail = S.crash_line("finish", e)
        self.assertEqual(summary, "finish crashed (RuntimeError: Target page, "
                                  "context or browser has been closed)")
        self.assertIn("Traceback", detail)


if __name__ == "__main__":
    unittest.main()

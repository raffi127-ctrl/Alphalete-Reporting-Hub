"""The Apex window waits out a busy profile, and a crash says what it was.

Jairo's finish window crashed 3 seconds after pnl's hourly check closed its
own browser on the same profile (2026-11-25 13:32), and the alert said only
"finish crashed (Error)".
"""
import unittest

from automations.icd_alerts import apex_2fa_setup as S


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
        ctx = S.launch_window(p, "/x", _G, log=lambda *_: None, wait_s=0)
        self.assertEqual(ctx, "ctx")
        self.assertEqual(p.chromium.calls, 3)

    def test_never_frees_raises_the_real_error(self):
        p = _P(fails=99)
        with self.assertRaises(RuntimeError):
            S.launch_window(p, "/x", _G, log=lambda *_: None, wait_s=0)
        self.assertEqual(p.chromium.calls, S.LAUNCH_TRIES)


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

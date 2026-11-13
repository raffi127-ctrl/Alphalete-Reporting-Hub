"""The OwnerVille re-sign-in in a real window nobody sees -- one office first
(Megan, 2026-11-13: "yes build it with raf first").

Pinned here:
  * only a trial office's Mac uses it, and never after it has failed once;
  * the hidden window gets the flags that keep Chrome running at full speed,
    the window in view does not change at all;
  * the guard hides Lucy's browser when it comes forward and hands the front
    back to what the owner was using -- and leaves every other app alone;
  * a failed hidden sign-in ends the trial on that computer and says so.
"""
import inspect
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import ov_read as OV
from automations.icd_alerts import quiet_window as QW


class WhoUsesIt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        note = Path(self.tmp.name) / "quiet-window-failed.txt"
        for p in (mock.patch.object(QW, "_note_path", return_value=note),
                  mock.patch.object(QW.C, "app_dir", return_value=None),
                  mock.patch.object(QW.platform, "system", return_value="Darwin")):
            p.start()
            self.addCleanup(p.stop)

    def _enrolled(self, *keys):
        return mock.patch.object(QW.C, "enrollments",
                                 return_value=[{"office_key": k} for k in keys])

    def test_only_the_trial_office(self):
        with self._enrolled("some-other-office"):
            self.assertFalse(QW.use_quiet())
        with self._enrolled(QW.TRIAL_OFFICES[0]):
            self.assertTrue(QW.use_quiet())

    def test_the_trial_is_one_office(self):
        self.assertEqual(QW.TRIAL_OFFICES, ("raf",))

    def test_one_failure_ends_it_on_that_computer(self):
        with self._enrolled(QW.TRIAL_OFFICES[0]):
            self.assertTrue(QW.use_quiet())
            QW.note_failed("did not open a working session")
            self.assertFalse(QW.use_quiet())

    def test_not_on_windows_yet(self):
        with self._enrolled(QW.TRIAL_OFFICES[0]), \
                mock.patch.object(QW.platform, "system", return_value="Windows"):
            self.assertFalse(QW.use_quiet())

    def test_an_unreadable_enrolment_is_a_no(self):
        with mock.patch.object(QW.C, "enrollments", side_effect=OSError("x")):
            self.assertFalse(QW.use_quiet())


class TheWindow(unittest.TestCase):
    def _launch(self, headless, quiet):
        p = mock.MagicMock()
        with mock.patch.object(OV.C, "OV_PROFILE_DIR", Path(tempfile.mkdtemp())), \
                mock.patch("automations.shared.browser_banner.attach"):
            OV._context(p, headless, quiet=quiet)
        return p.chromium.launch_persistent_context.call_args

    def test_a_hidden_real_window_gets_the_full_speed_flags(self):
        call = self._launch(False, True)
        self.assertFalse(call.kwargs["headless"])
        for f in QW.FLAGS:
            self.assertIn(f, call.kwargs["args"])

    def test_the_window_in_view_and_the_hidden_browser_are_unchanged(self):
        self.assertEqual(self._launch(False, False).kwargs["args"],
                         ["--disable-sync"])
        self.assertEqual(self._launch(True, True).kwargs["args"],
                         ["--disable-sync"])


class TheGuard(unittest.TestCase):
    def _run(self, fronts, lucy=(500, 501)):
        hidden, activated = [], []
        seq = iter(fronts)
        g = QW.Guard("/tmp/some-profile")
        g._front = lambda: next(seq, 42)
        g._hide = hidden.append
        g._activate = activated.append
        g._started = time.time()
        n = [0]

        def wait(_):                    # one pass per front app, then stop
            n[0] += 1
            if n[0] >= len(fronts):
                g._stop.set()
        g._stop.wait = wait
        with mock.patch.object(QW, "_pids", return_value=list(lucy)):
            g._loop()
        return g, hidden, activated

    def test_lucys_window_is_hidden_and_the_owners_app_put_back(self):
        g, hidden, activated = self._run([42, 500, 42])
        self.assertEqual(hidden, [500])
        self.assertEqual(activated, [42])
        self.assertEqual(g.hidden, 1)

    def test_other_apps_are_left_alone(self):
        g, hidden, activated = self._run([42, 43, 44])
        self.assertEqual((hidden, activated, g.hidden), ([], [], 0))

    def test_off_a_mac_it_does_nothing(self):
        with mock.patch.object(QW.platform, "system", return_value="Windows"):
            g = QW.Guard("/tmp/x").start()
        self.assertIsNone(g._thread)
        g.stop()


class Wiring(unittest.TestCase):
    def setUp(self):
        self.src = inspect.getsource(OV.read_knocks)

    def test_a_failed_hidden_sign_in_ends_the_trial_and_reports(self):
        i = self.src.index("except KnocksProblem as e:")
        block = self.src[i:i + 900]
        self.assertIn("QW.note_failed(", block)
        self.assertIn("QW.report(False", block)
        self.assertIn("raise", block)

    def test_success_is_only_claimed_for_a_real_sign_in(self):
        self.assertIn('if quiet and any("has lapsed" in m for m in seen):',
                      self.src)

    def test_the_guard_is_always_stopped(self):
        i = self.src.rindex("finally:")
        self.assertIn("guard.stop()", self.src[i:i + 300])

    def test_no_window_at_all_while_sign_in_is_on_hold(self):
        # unchanged: the hold is checked before any window, hidden or not
        self.assertLess(self.src.index("held = ov_hold_message()"),
                        self.src.index("QW.use_quiet()"))


if __name__ == "__main__":
    unittest.main()

"""The sweep cadence lives in two files, and they have to agree.

`dist/setup.py` writes the schedule on a FRESH install; `sweep_cadence.py`
retimes the offices that are already running. If they drift, half the fleet
sweeps on one clock and half on another, and nothing anywhere says so.

The retime itself is tested against a real plist on disk, because the thing
that can actually go wrong is a rewrite that mangles the file -- on a machine
we cannot reach, that is an office whose agent never runs again.
"""
from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import sweep_cadence as SC

HERE = pathlib.Path(__file__).resolve().parent


def _load_setup():
    """dist/setup.py is not importable as a module path (it ships as the
    installed copy's top-level `setup.py`), so load it by file."""
    spec = importlib.util.spec_from_file_location(
        "_icd_setup", HERE / "dist" / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
  <key>Label</key><string>com.alphalete.lucy-reports</string>
  <key>ProgramArguments</key>
  <array><string>/Users/kash/.lucy-reports/venv/bin/python</string></array>
  <key>StartInterval</key><integer>180</integer>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
"""


class TheTwoConstantsAgree(unittest.TestCase):

    def test_installer_and_retimer_use_the_same_number(self):
        self.assertEqual(
            _load_setup().EVERY_MINUTES, SC.EVERY_MINUTES,
            "dist/setup.py and sweep_cadence.py disagree about how often an "
            "office sweeps -- new installs and existing ones would run on "
            "different clocks")


class TheMacRetime(unittest.TestCase):

    def _with_plist(self, body):
        d = pathlib.Path(tempfile.mkdtemp())
        path = d / "com.alphalete.lucy-reports.plist"
        path.write_text(body)
        return path

    def test_rewrites_only_the_interval(self):
        path = self._with_plist(PLIST)
        with mock.patch.object(SC, "_plist_path", return_value=path), \
                mock.patch.object(SC.subprocess, "run") as run:
            self.assertTrue(SC.ensure(log=lambda *_a: None))
        after = path.read_text()
        self.assertIn("<integer>%d</integer>" % (SC.EVERY_MINUTES * 60), after)
        # EVERYTHING ELSE UNTOUCHED. The python path and the label were
        # computed on the office's own disk; guessing them is how an agent
        # stops running.
        self.assertIn("/Users/kash/.lucy-reports/venv/bin/python", after)
        self.assertEqual(after.count("<key>"), PLIST.count("<key>"))
        # THE RELOAD IS NOT RUN INLINE ANY MORE, and that is the point.
        # `launchctl unload` kills the job's running processes -- which is
        # this one -- so the load on the next line never ran and the agent
        # was left unloaded with no error anywhere. Kash's iMac and Cyrus's
        # laptop both stopped that way (2026-09-16).
        self.assertEqual(run.call_args_list, [],
                         "unloading inline kills the sweep doing it")

    def test_already_right_does_nothing(self):
        path = self._with_plist(
            PLIST.replace("180", str(SC.EVERY_MINUTES * 60)))
        before = path.read_text()
        with mock.patch.object(SC, "_plist_path", return_value=path), \
                mock.patch.object(SC.subprocess, "run") as run:
            self.assertFalse(SC.ensure(log=lambda *_a: None))
        self.assertEqual(path.read_text(), before)
        run.assert_not_called()          # no needless unload/load of the agent

    def test_missing_plist_is_not_a_failure(self):
        missing = pathlib.Path(tempfile.mkdtemp()) / "nope.plist"
        with mock.patch.object(SC, "_plist_path", return_value=missing):
            self.assertFalse(SC.ensure(log=lambda *_a: None))

    def test_unrecognisable_plist_is_left_alone(self):
        path = self._with_plist("<plist><dict></dict></plist>")
        before = path.read_text()
        with mock.patch.object(SC, "_plist_path", return_value=path), \
                mock.patch.object(SC.subprocess, "run") as run:
            self.assertFalse(SC.ensure(log=lambda *_a: None))
        self.assertEqual(path.read_text(), before)
        run.assert_not_called()

    def test_never_raises(self):
        with mock.patch.object(SC, "_plist_path", side_effect=OSError("disk")):
            said = []
            self.assertFalse(SC.ensure(log=said.append))
        self.assertTrue(any("skipped" in s for s in said), said)


class TheWindowsRetime(unittest.TestCase):
    """schtasks cannot run here; these are the decisions around the call."""

    def _bat(self, exists=True):
        d = pathlib.Path(tempfile.mkdtemp())
        if exists:
            (d / "run-agent.bat").write_text("@echo off\r\n")
        return d

    def test_overwrites_rather_than_deleting_first(self):
        # A Delete that succeeds and a Create that fails leaves an unreachable
        # machine with no trigger at all.
        with mock.patch.object(SC, "BASE", self._bat()), \
                mock.patch.object(SC, "_current_windows_minutes",
                                  return_value=3), \
                mock.patch.object(SC.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.assertTrue(SC._ensure_windows(log=lambda *_a: None))
        argv = run.call_args.args[0]
        self.assertIn("/Create", argv)
        self.assertIn("/F", argv)
        self.assertNotIn("/Delete", argv)
        self.assertEqual(argv[argv.index("/MO") + 1], str(SC.EVERY_MINUTES))

    def test_unreadable_task_is_left_alone(self):
        # Re-creating a trigger we could not inspect would be rewriting a
        # working schedule on a guess.
        with mock.patch.object(SC, "BASE", self._bat()), \
                mock.patch.object(SC, "_current_windows_minutes",
                                  return_value=None), \
                mock.patch.object(SC.subprocess, "run") as run:
            self.assertFalse(SC._ensure_windows(log=lambda *_a: None))
        run.assert_not_called()

    def test_no_bat_means_no_windows_install_here(self):
        with mock.patch.object(SC, "BASE", self._bat(exists=False)), \
                mock.patch.object(SC.subprocess, "run") as run:
            self.assertFalse(SC._ensure_windows(log=lambda *_a: None))
        run.assert_not_called()

    def test_a_failed_create_says_what_the_office_is_still_on(self):
        with mock.patch.object(SC, "BASE", self._bat()), \
                mock.patch.object(SC, "_current_windows_minutes",
                                  return_value=3), \
                mock.patch.object(SC.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1)
            said = []
            self.assertFalse(SC._ensure_windows(log=said.append))
        self.assertTrue(any("still running every 3 min" in s for s in said),
                        said)


if __name__ == "__main__":
    unittest.main()


class TheRetimeMustNotKillTheSweepDoingIt(unittest.TestCase):
    """Kash's iMac and Cyrus's laptop both stopped dead on 2026-09-14 and
    nobody knew until 2026-09-16.

    `launchctl unload` terminates the job's running processes -- and this code
    runs AS that job. So the unload killed the sweep mid-flight, the `load` on
    the very next line never executed, and the LaunchAgent was left unloaded:
    no traceback, no fault, nothing in the log after "self-update: updated N
    file(s)". A desktop that simply stopped.

    Three things had to line up and did: an office on the older cadence, a
    self-update carrying EVERY_MINUTES 3 -> 2, and this running inside the
    job.
    """

    PLIST = ('<plist><dict><key>Label</key><string>x</string>'
             '<key>StartInterval</key><integer>180</integer>'
             '<key>ProgramArguments</key>'
             '<array><string>/Users/kash/.lucy-reports/venv/bin/python'
             '</string></array></dict></plist>')

    def _plist(self):
        import pathlib, tempfile
        d = pathlib.Path(tempfile.mkdtemp())
        path = d / "com.alphalete.lucy-reports.plist"
        path.write_text(self.PLIST)
        return path

    def test_the_unload_is_never_run_inline(self):
        path = self._plist()
        with mock.patch.object(SC, "_plist_path", return_value=path), \
                mock.patch.object(SC.subprocess, "run") as run, \
                mock.patch.object(SC.subprocess, "Popen"):
            SC.ensure(log=lambda *_a: None)
        self.assertEqual(run.call_args_list, [],
                         "this is the call that killed the two machines")

    def test_the_reload_is_detached_from_this_job(self):
        """start_new_session puts it in its own session, so launchd taking
        down this job does not take it with it."""
        path = self._plist()
        with mock.patch.object(SC, "_plist_path", return_value=path), \
                mock.patch.object(SC.subprocess, "Popen") as popen:
            SC.ensure(log=lambda *_a: None)
        self.assertTrue(popen.call_args.kwargs.get("start_new_session"))

    def test_unload_and_load_are_one_command(self):
        """So there is no window in which a second process has to survive
        between them -- that window is how a machine ends up unloaded."""
        path = self._plist()
        with mock.patch.object(SC, "_plist_path", return_value=path), \
                mock.patch.object(SC.subprocess, "Popen") as popen:
            SC.ensure(log=lambda *_a: None)
        shell = popen.call_args.args[0][-1]
        self.assertIn("unload", shell)
        self.assertIn("load", shell)
        self.assertLess(shell.index("unload"), shell.index("; launchctl load"))

    def test_the_plist_is_correct_even_if_the_reload_never_happens(self):
        """Then the new cadence takes effect at the next login or boot, and
        the machine keeps sweeping on the old one until then. The failure
        mode has to be 'slower than intended', never 'stopped'."""
        path = self._plist()
        with mock.patch.object(SC, "_plist_path", return_value=path), \
                mock.patch.object(SC.subprocess, "Popen",
                                  side_effect=OSError("no")):
            self.assertTrue(SC.ensure(log=lambda *_a: None))
        self.assertIn("<integer>%d</integer>" % (SC.EVERY_MINUTES * 60),
                      path.read_text())

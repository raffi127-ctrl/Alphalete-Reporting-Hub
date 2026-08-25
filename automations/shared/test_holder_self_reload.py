"""A holder fix that needs a human to restart it is a fix nobody knows is off.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_holder_self_reload

WHY (Megan 2026-08-25). The holder runs for days, so it keeps whatever code it
started with — `git pull` changes files on disk and nothing else. Both of this
week's holder fixes sat inert because of it:

  a965a8a (8/24)  widened AppStream warming to all three Lucys
  6665dff (8/25)  taught the holder to pick up a pushed token

Neither did anything until someone remembered `lucy restart_holder`. That is
worse than no fix: it reads as "we tried that and it didn't help", and it cost a
day of diagnosis pointed at the wrong thing. mini_control's poller has re-execed
on a HEAD change since 2026-07-05 for exactly this reason.

WHY EXIT AND NOT os.execv — the difference from the poller. The poller owns no
browser; this process owns a live Chrome. Replacing the image out from under it
would orphan or kill that Chrome mid-session. Exiting is the restart path this
file already uses twice (dead browser, stale export), and launchd's KeepAlive
(deploy/com.alphalete.session-holder.plist, 30s throttle) relaunches onto the
persistent profile and re-seeds with no human.

The probe is best-effort ON PURPOSE: a git hiccup answering "" must read as "no
change", never as a restart loop and never as a stall.
"""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from automations.shared import session_holder as sh


class TheHeadProbe(unittest.TestCase):

    def _run(self, *, returncode=0, stdout="abc123\n", exc=None):
        if exc is not None:
            ctx = mock.patch.object(subprocess, "run", side_effect=exc)
        else:
            ctx = mock.patch.object(
                subprocess, "run",
                return_value=mock.Mock(returncode=returncode, stdout=stdout))
        with ctx:
            return sh._git_head()

    def test_it_returns_the_head_sha(self):
        self.assertEqual(self._run(stdout="deadbeefcafe\n"), "deadbeefcafe")

    def test_a_nonzero_exit_reads_as_no_change(self):
        """Not a git repo, detached, permissions — all mean 'don't restart'."""
        self.assertEqual(self._run(returncode=128, stdout=""), "")

    def test_a_timeout_reads_as_no_change(self):
        self.assertEqual(
            self._run(exc=subprocess.TimeoutExpired("git", 10)), "")

    def test_any_exception_reads_as_no_change(self):
        """A probe must never break the holder — this runs every cycle."""
        self.assertEqual(self._run(exc=OSError("git missing")), "")

    def test_it_asks_about_this_repo(self):
        """-C the holder's own repo, not whatever cwd launchd happened to give."""
        with mock.patch.object(subprocess, "run",
                               return_value=mock.Mock(returncode=0,
                                                      stdout="x\n")) as run:
            sh._git_head()
        argv = run.call_args[0][0]
        self.assertEqual(argv[:3], ["git", "-C", str(sh._REPO_ROOT)])
        self.assertIn("rev-parse", argv)


class TheRestartRule(unittest.TestCase):
    """The comparison the loop makes, stated directly. `start` is the SHA the
    process booted with; `now` is what the probe answers this cycle."""

    @staticmethod
    def _should_restart(start: str, now: str) -> bool:
        return bool(start and now and now != start)

    def test_a_changed_head_restarts(self):
        self.assertTrue(self._should_restart("aaa", "bbb"))

    def test_an_unchanged_head_does_not(self):
        self.assertFalse(self._should_restart("aaa", "aaa"))

    def test_an_unreadable_probe_now_does_not_restart(self):
        """The dangerous one: '' != 'aaa' is True, so a naive compare would
        restart every cycle git hiccups — a hot loop against KeepAlive."""
        self.assertFalse(self._should_restart("aaa", ""))

    def test_an_unreadable_head_at_boot_never_restarts(self):
        """Booted somewhere git can't answer: stay up rather than churn."""
        self.assertFalse(self._should_restart("", "bbb"))

    def test_both_unreadable_does_not_restart(self):
        self.assertFalse(self._should_restart("", ""))


class ItIsWiredIntoTheLoop(unittest.TestCase):

    def test_the_loop_records_head_at_start_and_compares_each_cycle(self):
        import inspect
        src = inspect.getsource(sh)
        self.assertIn("head_at_start = _git_head()", src)
        self.assertIn("head_now = _git_head()", src)
        self.assertIn("if head_at_start and head_now and head_now != head_at_start:",
                      src, "the guard must require BOTH reads before restarting")

    def test_it_exits_rather_than_execv(self):
        """os.execv would orphan the holder's live Chrome. The restart has to go
        through launchd, the way the dead-browser path already does."""
        import inspect
        src = inspect.getsource(sh)
        # A CALL, not the word — the rationale comment names os.execv on purpose.
        self.assertNotIn("os.execv(", src)
        self.assertIn("exiting (rc=1) so launchd relaunches", src)


if __name__ == "__main__":
    unittest.main()

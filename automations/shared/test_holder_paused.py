"""An ownerville login must pause the holder — and always give it back.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_holder_paused

WHY (2026-09-01). Ownerville is one session per account: a fresh login BUMPS
whatever session that account already has, and the holder's session is the one
every impersonating report rides on. The autorenew logged in without pausing it
and took Rep Gap Alerts down — clean ticks through 14:15, the login at 14:22,
then "Couldn't impersonate 'Calvin Ribera' in ownerville: name not found" on
every tick until the holder was restarted at 16:07. The names were never wrong;
the session under them had been bumped. tableau_patchright warned about this in
as many words and the warning was not heeded.

A holder left DOWN is strictly worse than a stale token — the token expires in
two hours, a dead holder is dark until somebody notices — so the restart has to
survive an exception.
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import subprocess
import unittest
from unittest import mock

from automations.shared import appstream_autorenew as ar


class HolderPausedTest(unittest.TestCase):

    def _fake_run(self, calls, boot_rc=0):
        def run(cmd, **kw):
            calls.append(list(cmd))
            rc = boot_rc if "bootout" in cmd else 0
            return subprocess.CompletedProcess(cmd, rc, "", "")
        return run

    def test_it_stops_the_holder_before_and_restarts_after(self):
        calls = []
        with mock.patch("subprocess.run", side_effect=self._fake_run(calls)), \
             mock.patch.object(ar.time, "sleep", lambda *_: None):
            with ar._holder_paused(verbose=False):
                self.assertTrue(any("bootout" in c for c in calls),
                                "must stop the holder BEFORE the login")
                self.assertFalse(any("bootstrap" in c for c in calls),
                                 "must not restart it until the login is done")
        self.assertTrue(any("bootstrap" in c for c in calls),
                        "must restart the holder afterwards")

    def test_the_holder_comes_back_even_when_the_login_raises(self):
        """The whole point. A crash mid-login must not leave the fleet dark."""
        calls = []
        with mock.patch("subprocess.run", side_effect=self._fake_run(calls)), \
             mock.patch.object(ar.time, "sleep", lambda *_: None):
            with self.assertRaises(ValueError):
                with ar._holder_paused(verbose=False):
                    raise ValueError("login blew up")
        self.assertTrue(any("bootstrap" in c for c in calls),
                        "the holder must be restored on the exception path too")

    def test_a_holder_that_was_not_running_is_not_bootstrapped(self):
        """Nothing was stopped, so nothing should be started — otherwise we
        would start a holder on a machine that deliberately has none."""
        calls = []
        with mock.patch("subprocess.run", side_effect=self._fake_run(calls, boot_rc=1)), \
             mock.patch.object(ar.time, "sleep", lambda *_: None):
            with ar._holder_paused(verbose=False):
                pass
        self.assertFalse(any("bootstrap" in c for c in calls))


if __name__ == "__main__":
    unittest.main()

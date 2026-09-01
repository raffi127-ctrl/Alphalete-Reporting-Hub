"""Switching the ownerville account must not take the other logins with it.

One file holds ownerville, AppStream and Double Entry. A rewrite that dropped
the others would trade one broken report for several, and the machine it runs
on is the one nobody is sitting at.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from automations.shared import creds
from automations.shared import set_ownerville_login as SOL

OTHERS = {
    "appstream_username": "rcaptain",
    "appstream_password": "as-secret",
    "doubleentry_username": "de-user",
    "doubleentry_password": "de-secret",
}


class SetLogin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ownerville-creds.json"
        start = dict(OTHERS)
        start.update({"ownerville_username": "chidalgo",
                      "ownerville_password": "old-secret"})
        self.path.write_text(json.dumps(start))
        self._real = creds._CREDS_PATH
        creds._CREDS_PATH = self.path
        creds.reload()

    def tearDown(self):
        creds._CREDS_PATH = self._real
        creds.reload()
        self.tmp.cleanup()

    def test_switches_the_ownerville_account(self):
        was = SOL.set_login("rhidalgo", "new-secret")
        self.assertEqual(was, "chidalgo")
        data = json.loads(self.path.read_text())
        self.assertEqual(data["ownerville_username"], "rhidalgo")
        self.assertEqual(data["ownerville_password"], "new-secret")

    def test_leaves_the_other_logins_alone(self):
        SOL.set_login("rhidalgo", "new-secret")
        data = json.loads(self.path.read_text())
        for key, val in OTHERS.items():
            self.assertEqual(data[key], val, key)

    def test_backs_up_before_overwriting(self):
        SOL.set_login("rhidalgo", "new-secret")
        baks = list(self.path.parent.glob(self.path.name + ".bak.*"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(json.loads(baks[0].read_text())["ownerville_username"],
                         "chidalgo")

    def test_the_file_stays_owner_only(self):
        """It holds live passwords — 0600 before, 0600 after."""
        SOL.set_login("rhidalgo", "new-secret")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_the_reader_sees_the_new_account_immediately(self):
        """creds caches the file for the life of the process, so a caller that
        set the login and then read it back used to get the OLD account."""
        SOL.set_login("rhidalgo", "new-secret")
        self.assertEqual(creds.ownerville_username(), "rhidalgo")


class _NoTTY(io.StringIO):
    def isatty(self):
        return False


class ReadPasswordWithoutATerminal(unittest.TestCase):
    """A Run button / a pipe / `ssh` without -t gives getpass nowhere to draw a
    prompt. That used to surface as a bare EOFError traceback, which reads as a
    broken command — Megan ran it and reported "nothing popped up"."""

    def setUp(self):
        self._stdin = sys.stdin
        self._getpass = SOL.getpass.getpass
        SOL.getpass.getpass = self._boom

    def tearDown(self):
        sys.stdin = self._stdin
        SOL.getpass.getpass = self._getpass

    @staticmethod
    def _boom(_prompt):
        raise EOFError

    def test_empty_stdin_explains_itself_and_changes_nothing(self):
        sys.stdin = _NoTTY("")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertIsNone(SOL._read_password("rhidalgo"))
        out = buf.getvalue()
        self.assertIn("no terminal", out)
        self.assertIn("-t", out)            # names the actual fix
        self.assertIn("Nothing was changed", out)

    def test_a_piped_password_is_still_honoured(self):
        """Piping is a deliberate choice, not an accident of the terminal."""
        sys.stdin = _NoTTY("piped-secret\n")
        self.assertEqual(SOL._read_password("rhidalgo"), "piped-secret")


if __name__ == "__main__":
    unittest.main()

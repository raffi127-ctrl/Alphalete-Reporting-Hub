"""Switching the ownerville account must not take the other logins with it.

One file holds ownerville, AppStream and Double Entry. A rewrite that dropped
the others would trade one broken report for several, and the machine it runs
on is the one nobody is sitting at.
"""
import json
import os
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()

"""Resume pushing on the office's own machine needs THEIR AppStream login.

Carlos 2026-10-05: on Lucy 2 the push takes up the screen and is slow across
that many offices. These pin what the installer must do for it.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
SETUP = (HERE / "dist" / "setup.py").read_text()
from automations.icd_alerts.test_install_completeness import _install_problems


class TheInstallerAsksForAppStream(unittest.TestCase):

    def test_it_asks_only_offices_that_push(self):
        self.assertIn("if ask_about_resume_pushing():", SETUP)
        self.assertIn("as_ok = appstream_until_it_works()", SETUP)

    def test_the_login_is_verified_not_just_saved(self):
        # A wrong AppStream username does not error; only the console is proof.
        self.assertIn('"automations.icd_alerts.as_signin"', SETUP)

    def test_a_failed_check_is_reported(self):
        self.assertIn("AppStream did not verify during setup", SETUP)

    def test_the_sign_in_ships_to_the_office(self):
        files = (HERE / "agent_files.txt").read_text().split()
        self.assertIn("automations/icd_alerts/as_signin.py", files)
        from automations.icd_alerts import package
        self.assertIn("automations/icd_alerts/as_signin.py", package.AGENT_FILES)

    def test_the_cloudflare_waits_are_not_shortened(self):
        from automations.shared import ownerville_knocks as K
        self.assertGreaterEqual(K.CLOUDFLARE_WAIT_MS, 20_000)
        self.assertGreaterEqual(K.PRE_SUBMIT_PAUSE_MS, 20_000)


class AMissingLoginIsSaid(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def _write(self, push):
        (self.tmp / "install.json").write_text(
            json.dumps([{"office_key": "x", "push_resumes": push}]))

    def test_wants_push_without_login_is_a_note_not_a_block(self):
        self._write(True)
        blocking, notes = _install_problems(
            self.tmp, sara=True,
            files=["saraplus-creds.json", "ownerville-creds.json"])
        self.assertFalse(blocking)
        self.assertTrue(any("AppStream" in n for n in notes))

    def test_no_push_no_note(self):
        self._write(False)
        _, notes = _install_problems(
            self.tmp, sara=True,
            files=["saraplus-creds.json", "ownerville-creds.json"])
        self.assertFalse(any("AppStream" in n for n in notes))

    def test_login_saved_no_note(self):
        self._write(True)
        _, notes = _install_problems(
            self.tmp, sara=True,
            files=["saraplus-creds.json", "ownerville-creds.json",
                   "appstream-creds.json"])
        self.assertFalse(any("AppStream" in n for n in notes))


class TheCredsReader(unittest.TestCase):

    def test_none_saved_is_empty_not_an_error(self):
        from automations.icd_alerts import config as C
        with mock.patch.object(C, "AS_CREDS_PATH",
                               pathlib.Path(tempfile.mkdtemp()) / "nope.json"):
            self.assertEqual(C.appstream_creds(), {})


if __name__ == "__main__":
    unittest.main()

"""The Blue Ink sign-in the installer collects once, and never leaks."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import blueink_setup as BS


class _Ask:
    """Stands in for dialogs: answers, and records what it was asked."""
    class Cancelled(Exception):
        pass

    def __init__(self, text="", password="", cancel=False):
        self._text, self._password, self._cancel = text, password, cancel
        self.asked = []

    def text(self, prompt):
        self.asked.append(prompt)
        if self._cancel:
            raise self.Cancelled()
        return self._text

    def password(self, prompt):
        self.asked.append(prompt)
        if self._cancel:
            raise self.Cancelled()
        return self._password


class SavingIt(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "blueink-creds.json"
        self.p1 = mock.patch.object(BS, "ECO_DIR", self.dir)
        self.p2 = mock.patch.object(BS, "CREDS_PATH", self.path)
        self.p1.start()
        self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)

    def test_the_api_key_already_there_is_not_thrown_away(self):
        """Rewriting the file from scratch would lose the key and the
        template id to save a password -- and the key is the half that
        cannot be typed again on a non-Enterprise plan."""
        self.path.write_text(json.dumps({"blueink_api_key": "K",
                                         "envelope_template_id": "T-1"}))
        BS.save_login("a@b.com", "pw")
        got = json.loads(self.path.read_text())
        self.assertEqual(got["blueink_api_key"], "K")
        self.assertEqual(got["envelope_template_id"], "T-1")
        self.assertEqual(got["email"], "a@b.com")

    def test_a_missing_or_broken_file_is_still_written(self):
        self.path.write_text("not json at all")
        BS.save_login("a@b.com", "pw")
        self.assertEqual(json.loads(self.path.read_text())["email"], "a@b.com")

    def test_it_is_readable_by_nobody_else(self):
        BS.save_login("a@b.com", "pw")
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)


class AskingForIt(unittest.TestCase):

    def test_an_office_that_already_has_one_is_not_asked_again(self):
        ask = _Ask(text="a@b.com", password="pw")
        with mock.patch.object(BS, "have_login", return_value=True):
            self.assertEqual(BS.ask_login(ask, log=lambda *_a: None),
                             "sign-in saved")
        self.assertEqual(ask.asked, [], "it asked an office that had answered")

    def test_half_an_answer_saves_nothing(self):
        """An email with no password would be typed into the page and
        submitted blank, which counts as a failed attempt on the account."""
        for kw in ({"text": "a@b.com", "password": ""}, {"text": "", "password": "pw"}):
            ask = _Ask(**kw)
            with mock.patch.object(BS, "have_login", return_value=False), \
                 mock.patch.object(BS, "save_login") as saver:
                said = BS.ask_login(ask, log=lambda *_a: None)
            self.assertEqual(said, "no sign-in saved")
            saver.assert_not_called()

    def test_cancelling_is_not_a_failure(self):
        ask = _Ask(cancel=True)
        with mock.patch.object(BS, "have_login", return_value=False):
            self.assertEqual(BS.ask_login(ask, log=lambda *_a: None),
                             "no sign-in saved")

    def test_the_password_never_reaches_the_log(self):
        said = []
        ask = _Ask(text="a@b.com", password="hunter2")
        with mock.patch.object(BS, "have_login", return_value=False), \
             mock.patch.object(BS, "save_login"):
            BS.ask_login(ask, log=said.append)
        self.assertNotIn("hunter2", " ".join(said))

    def test_the_boxes_say_it_stays_on_this_computer(self):
        """An owner typing a password into a box somebody else built is owed
        a plain sentence about where it goes."""
        self.assertIn("this computer", BS.ASK_PASSWORD)


if __name__ == "__main__":
    unittest.main()

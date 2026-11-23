"""Signing in to Blue Ink with the saved password: what it refuses to do."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.blueink_docs import auto_login as AL
from automations.blueink_docs import config


def _source() -> str:
    with open(AL.__file__) as fh:
        return fh.read()


class TheCredentialIsTheOfficesOwn(unittest.TestCase):

    def _creds_file(self, payload):
        d = Path(tempfile.mkdtemp())
        p = d / "blueink-creds.json"
        p.write_text(json.dumps(payload))
        return p

    def test_it_reads_the_email_and_password_from_the_one_blue_ink_file(self):
        p = self._creds_file({"blueink_api_key": "k", "email": "a@b.com",
                              "password": "pw"})
        with mock.patch.object(config, "creds_path", lambda: p), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.login_creds(),
                             {"email": "a@b.com", "password": "pw"})

    def test_no_password_is_not_an_error(self):
        """A machine without one signs in by hand, which is what every
        machine did before. Raising here would break those."""
        p = self._creds_file({"blueink_api_key": "k"})
        with mock.patch.object(config, "creds_path", lambda: p), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.login_creds(), {})
            self.assertFalse(AL.can_try())

    def test_half_a_credential_is_no_credential(self):
        """An email with no password would be typed into the page and then
        submitted blank, which counts as a failed attempt against the
        account."""
        for payload in ({"email": "a@b.com"}, {"password": "pw"},
                        {"email": "", "password": "pw"}):
            p = self._creds_file(payload)
            with mock.patch.object(config, "creds_path", lambda: p), \
                 mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(config.login_creds(), {}, payload)

    def test_a_missing_file_is_not_a_crash(self):
        gone = Path(tempfile.mkdtemp()) / "nope.json"
        with mock.patch.object(config, "creds_path", lambda: gone), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.login_creds(), {})


class WhatItRefusesToDo(unittest.TestCase):

    def test_it_never_retries_a_rejected_password(self):
        """One attempt. Steve McElwee's OwnerVille box re-typed a password
        that was not working and every attempt was a strike toward the
        account locking; a locked Blue Ink account stops an office's
        paperwork for everybody."""
        src = _source()
        self.assertNotIn("for attempt in", src)
        self.assertIn("It was tried \"\n                \"once", src)

    def test_the_browser_is_hidden(self):
        """It runs by itself on somebody's office computer and nobody has to
        act, so nothing appears on their screen."""
        src = _source()
        self.assertIn("headless=True", src)
        self.assertNotIn("headless=False", src)

    def test_a_page_that_changed_never_carries_the_password_into_the_error(self):
        """Playwright's fill() error quotes the value it was given, and that
        text goes into a log file and a Slack post."""
        src = _source()
        i = src.index("page.fill(EMAIL_BOX")
        j = src.index("page.click(LOGIN_BUTTON")
        guarded = src[i:j]
        self.assertIn("from None", guarded)
        self.assertIn("type(exc).__name__", guarded)

    def test_being_signed_in_already_is_not_a_reason_to_type(self):
        src = _source()
        self.assertLess(src.index("already signed in"),
                        src.index("page.fill(EMAIL_BOX"))

    def test_a_sign_in_is_confirmed_twice_before_it_is_believed(self):
        """The app routes itself to /dashboard while still logged out, which
        is how an empty session was saved and called success on 2026-09-08."""
        looks = [True, False]
        page = mock.Mock()
        page.wait_for_timeout = mock.Mock()
        with mock.patch("automations.blueink_docs.session.signed_in",
                        side_effect=lambda _p: looks.pop(0)):
            self.assertFalse(AL._signed_in_twice(page))


if __name__ == "__main__":
    unittest.main()


class TheSignInIsTwoScreens(unittest.TestCase):
    """Read off the live page on 2026-11-23, after the first cut timed out.

    Blue Ink asks for the EMAIL alone, with a Continue button, and the
    password box does not exist in the document until that is pressed. The
    screenshot this was first written from showed both boxes at once because
    that browser already remembered the email -- so the code expected one
    screen and matched nothing. The email field is type="text" as well, which
    is why asking for input[type='email'] found no field at all.
    """

    def test_the_email_box_is_not_asked_for_by_type_alone(self):
        self.assertIn("name='email'", AL.EMAIL_BOX)
        self.assertIn("#loginForm-email", AL.EMAIL_BOX)

    def test_continue_is_pressed_before_the_password_is_looked_for(self):
        src = _source()
        self.assertLess(src.index("page.click(CONTINUE_BUTTON"),
                        src.index("wait_for_selector(PASSWORD_BOX"))
        self.assertLess(src.index("wait_for_selector(PASSWORD_BOX"),
                        src.index("page.fill(PASSWORD_BOX"))

    def test_a_rejected_email_is_named_as_that(self):
        """"No password box" sends somebody to read the page when the answer
        is that the address is not an account."""
        self.assertIn("may not be an account", _source())


class TheFilesAnswerDifferentQuestions(unittest.TestCase):
    """A password saved into the home copy must not hide a key in the repo one.

    2026-11-23: the installer's sign-in box created ~/.config/lucy-reports/
    blueink-creds.json with an email and a password in it. creds_path() picks
    ONE file, so that copy immediately shadowed the repo copy where this
    machine's API key lives, and Blue Ink went from working to "No Blue Ink
    API key" with nothing about a key having changed. An Apex dry run found
    it, which is not a mechanism.
    """

    def _two_files(self, eco, repo):
        d = Path(tempfile.mkdtemp())
        eco_path, repo_root = d / "eco.json", d / "repo"
        repo_root.mkdir()
        eco_path.write_text(json.dumps(eco))
        (repo_root / "blueink-creds.json").write_text(json.dumps(repo))
        return mock.patch.multiple(config, ECO_CREDS_PATH=eco_path,
                                   REPO_ROOT=repo_root)

    def test_a_password_in_one_does_not_hide_a_key_in_the_other(self):
        with self._two_files({"email": "a@b.com", "password": "pw"},
                             {"blueink_api_key": "K",
                              "envelope_template_id": "T-1"}), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.api_key(), "K")
            self.assertEqual(config.template_id(), "T-1")
            self.assertEqual(config.login_creds()["email"], "a@b.com")

    def test_the_offices_own_key_still_wins_where_it_has_one(self):
        with self._two_files({"blueink_api_key": "THEIRS"},
                             {"blueink_api_key": "OURS"}), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.api_key(), "THEIRS")

    def test_an_empty_value_does_not_count_as_an_answer(self):
        with self._two_files({"blueink_api_key": ""},
                             {"blueink_api_key": "OURS"}), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.api_key(), "OURS")

    def test_own_key_means_a_key_not_a_file(self):
        """assert_key_belongs_to leans on this to stop one office sending out
        of another's account. A file holding only a password said "own key"
        about a machine still reading Alphalete's."""
        with self._two_files({"email": "a@b.com", "password": "pw"},
                             {"blueink_api_key": "OURS"}):
            self.assertFalse(config.using_own_key())
        with self._two_files({"blueink_api_key": "THEIRS"},
                             {"blueink_api_key": "OURS"}):
            self.assertTrue(config.using_own_key())

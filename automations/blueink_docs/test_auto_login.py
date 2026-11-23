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

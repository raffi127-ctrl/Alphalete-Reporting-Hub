"""The owner's Blue Ink sign-in: what it says, and what it never does."""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_alerts import blueink_signin as BS
from automations.blueink_docs import auto_login as AUTO
from automations.blueink_docs import session as SESSION


class _Dialogs:
    def __init__(self):
        self.said = []

    def message(self, body, **kw):
        self.said.append(body)


class WhoseAccountItNames(unittest.TestCase):

    def test_our_machine_still_names_the_shared_account(self):
        with mock.patch("automations.icd_alerts.config.install", return_value={}):
            self.assertEqual(SESSION.whose_account(),
                             "alphaletemarketing@gmail.com")

    def test_an_office_machine_is_never_told_to_use_ours(self):
        """Signing an ICD in as alphaletemarketing would send THEIR new starts
        OUR contract bundle. Same mistake as the pre-filled bundle name."""
        with mock.patch("automations.icd_alerts.config.install",
                        return_value={"office_key": "vincent"}):
            self.assertEqual(SESSION.whose_account(), "")

    def test_the_prompt_never_names_a_password(self):
        with open(BS.__file__) as fh:
            src = fh.read().lower()
        for word in ("password", "creds", "getpass"):
            self.assertNotIn(word + " =", src)


class NoTestEverReachesTheRealScreen(unittest.TestCase):
    """2026-11-23: two real boxes appeared on Megan's Mac, from a test that
    believed it had replaced them. mock.patch.dict("sys.modules", ...) does
    not intercept `from automations.icd_alerts import dialogs` -- that reads
    an attribute off the already-imported PACKAGE, so the real module was
    used and the suite popped dialogs on a working machine."""

    def test_the_surfaces_are_arguments_not_imports(self):
        import inspect
        sig = inspect.signature(BS.run)
        for name in ("dialogs", "auto"):
            self.assertIn(name, sig.parameters,
                          "run() must take %s so a test can pass its own, "
                          "rather than patch an import that will not take"
                          % name)

    def test_nothing_imports_dialogs_inside_run(self):
        """Checked on the parsed code, not the text -- the docstring of run()
        talks about the import it must not make."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(BS.run).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names]
                self.assertNotIn("dialogs", names,
                                 "run() imports dialogs instead of taking it")


class WhatTheOwnerIsTold(unittest.TestCase):

    def _run(self, login, auto=False):
        """`auto` = whether the saved password signs in by itself.

        MOCKED ON PURPOSE, not left to the machine. ensure() reaches for a
        real session and would launch a browser on any box that has one, so a
        test that did not mock it would pass here and hang in CI.
        """
        dlg = _Dialogs()
        fake_auto = mock.Mock()
        fake_auto.ensure = lambda log=print: auto
        with mock.patch.object(SESSION, "login", login):
            code = BS.run(log=lambda *_a: None, dialogs=dlg, auto=fake_auto)
        return code, dlg.said

    def test_the_saved_password_means_the_owner_sees_nothing(self):
        """The whole point: a sign-in that needs no person opens no window.
        A box nobody needed is what Lucy is not supposed to put on a screen."""
        def never(say=print):
            raise AssertionError("login() should not be reached")
        code, said = self._run(never, auto=True)
        self.assertEqual(code, 0)
        self.assertEqual(said, [])

    def test_a_good_sign_in_says_there_is_nothing_else_to_do(self):
        code, said = self._run(lambda say=print: 0)
        self.assertEqual(code, 0)
        self.assertTrue(any("signed in" in s.lower() for s in said))
        self.assertTrue(any("nothing else" in s.lower() for s in said))

    def test_nobody_signing_in_says_so_instead_of_claiming_success(self):
        code, said = self._run(lambda say=print: 1)
        self.assertEqual(code, 1)
        joined = " ".join(said).lower()
        self.assertIn("nobody signed in", joined)
        self.assertNotIn("you're signed in", joined)

    def test_a_crash_is_not_reported_as_a_sign_in(self):
        """A prompt that falls over leaves the owner believing they did it,
        and the paperwork silently still on hold."""
        def boom(say=print):
            raise RuntimeError("playwright is not installed")
        code, said = self._run(boom)
        self.assertEqual(code, 2)
        joined = " ".join(said).lower()
        self.assertIn("nothing has changed", joined)
        self.assertNotIn("signed in to blue ink", joined)

    def test_the_owner_gets_two_boxes_at_most(self):
        """One before, one after. login() narrates four or five times, and a
        person clicking through five dialogs stops reading them."""
        _code, said = self._run(
            lambda say=print: [say("a"), say("b"), say("c"), 0][-1])
        self.assertLessEqual(len(said), 2)


if __name__ == "__main__":
    unittest.main()

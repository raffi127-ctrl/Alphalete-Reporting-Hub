"""Every Mac dialog is raised inside System Events after `activate`, so it
opens in FRONT of the Terminal (Hasani's install, 2026-10-21: the "Is that
you?" box sat hidden for ten minutes)."""
import unittest
from unittest import mock

from automations.icd_alerts import dialogs as D


class DialogsComeToTheFront(unittest.TestCase):
    def _captured(self, fn, *args, **kw):
        seen = {}

        def fake_run(cmd, **_):
            seen["script"] = cmd[2]
            return mock.Mock(returncode=0, stdout=b"Yes", stderr=b"")

        with mock.patch.object(D, "IS_MAC", True), \
                mock.patch.object(D.subprocess, "run", fake_run):
            fn(*args, **kw)
        return seen["script"]

    def test_choose_activates_first(self):
        s = self._captured(D.choose, "Is that you?", ["Yes", "No"])
        self.assertTrue(s.startswith('tell application "System Events"\nactivate\n'))
        self.assertIn("choose from list", s)
        self.assertTrue(s.rstrip().endswith("end tell"))

    def test_text_password_and_message_too(self):
        for fn, args in ((D.text, ("x",)), (D.password, ("x",)),
                         (D.message, ("x",))):
            s = self._captured(fn, *args)
            self.assertIn("\nactivate\n", s, fn.__name__)
            self.assertTrue(s.rstrip().endswith("end tell"), fn.__name__)


if __name__ == "__main__":
    unittest.main()

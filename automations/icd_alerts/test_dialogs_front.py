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
        self.assertTrue(s.startswith('with timeout of 86400 seconds\ntell application "System Events"\nactivate\n'))
        self.assertIn("choose from list", s)
        self.assertTrue(s.rstrip().endswith("end tell\nend timeout"))

    def test_text_password_and_message_too(self):
        for fn, args in ((D.text, ("x",)), (D.password, ("x",)),
                         (D.message, ("x",))):
            s = self._captured(fn, *args)
            self.assertIn("\nactivate\n", s, fn.__name__)
            self.assertTrue(s.rstrip().endswith("end tell\nend timeout"), fn.__name__)



class SystemEventsFailureFallsBackToThePlainBox(unittest.TestCase):
    def test_a_timed_out_wrapper_retries_bare(self):
        calls = []

        def fake_run(cmd, **_):
            calls.append(cmd[2])
            if "System Events" in cmd[2]:
                return mock.Mock(returncode=1, stdout=b"",
                                 stderr=b"42:274: execution error: System Events got an error: AppleEvent timed out. (-1712)")
            return mock.Mock(returncode=0, stdout=b"omar@x.com", stderr=b"")

        with mock.patch.object(D, "IS_MAC", True), \
                mock.patch.object(D.subprocess, "run", fake_run):
            self.assertEqual(D.text("Your SaraPlus email:"), "omar@x.com")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("System Events", calls[1])

    def test_a_real_cancel_still_cancels(self):
        def fake_run(cmd, **_):
            return mock.Mock(returncode=1, stdout=b"", stderr=b"execution error: User canceled. (-128)")
        with mock.patch.object(D, "IS_MAC", True), \
                mock.patch.object(D.subprocess, "run", fake_run):
            with self.assertRaises(D.Cancelled):
                D.password("x")


if __name__ == "__main__":
    unittest.main()

"""finish_setup only opens the My Service Cloud sign-in when the session is
really gone (Megan 2026-11-10: ask only for what's missing)."""
import unittest
from unittest import mock

from automations.icd_alerts import box_read, box_signin, finish_setup as FS


class BoxCheckFirst(unittest.TestCase):
    def _run(self, alive):
        with mock.patch.object(FS.C, "uses_servicecloud", return_value=True), \
             mock.patch.object(box_read, "session_alive", return_value=alive), \
             mock.patch.object(box_signin, "run", return_value=0) as signin:
            said = FS._service_cloud(lambda *_a: None)
        return said, signin.called

    def test_signed_in_asks_nothing(self):
        self.assertEqual(self._run(True), ("already working", False))

    def test_signed_out_opens_sign_in(self):
        self.assertEqual(self._run(False), ("done", True))

    def test_cant_tell_still_asks(self):
        self.assertEqual(self._run(None), ("done", True))


if __name__ == "__main__":
    unittest.main()

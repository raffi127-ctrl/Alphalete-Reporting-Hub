"""After SaraPlus refuses a login the agent stands back for a while, and a
person's sign-in clears the hold (Khalil: 123 refused logins in a day)."""
import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import sara_read as SR


class SaraHoldTest(unittest.TestCase):
    def setUp(self):
        self.path = pathlib.Path(tempfile.mkdtemp()) / "hold.txt"
        self.p = mock.patch.object(SR, "SARA_HOLD_PATH", self.path)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_no_hold_by_default(self):
        self.assertIsNone(SR.sara_held_until())

    def test_a_refusal_holds_for_half_an_hour(self):
        SR.hold_sara(log=lambda *a: None)
        until = SR.sara_held_until()
        self.assertIsNotNone(until)
        mins = (until - dt.datetime.now()).total_seconds() / 60
        self.assertGreater(mins, 28)
        self.assertLessEqual(mins, 30)

    def test_an_expired_hold_is_gone(self):
        self.path.write_text((dt.datetime.now() - dt.timedelta(minutes=1))
                             .isoformat(timespec="seconds"))
        self.assertIsNone(SR.sara_held_until())
        self.assertFalse(self.path.exists())

    def test_a_persons_sign_in_clears_it(self):
        SR.hold_sara(log=lambda *a: None)
        SR.clear_sara_hold()
        self.assertIsNone(SR.sara_held_until())

    def test_the_sweep_honours_the_hold(self):
        from automations.icd_alerts import run as R
        import inspect
        src = inspect.getsource(R.cmd_once)
        self.assertIn("sara_held_until()", src)
        self.assertLess(src.index("sara_held_until()"), src.index('W.timed("sweep"'))
        self.assertIn("hold_sara(", src)


if __name__ == "__main__":
    unittest.main()

"""A failed or locked OwnerVille sign-in stops the agent from trying again
every sweep (Jenny/Figspire 2026-10-12: account locked, and the locked page
kept popping up on her screen every few minutes)."""
import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import config as C
from automations.icd_alerts import ov_read as OV
from automations.shared import ownerville_knocks as K

CREDS = {"username": "J*Figueroa28", "password": "pw1"}
quiet = lambda *a, **k: None  # noqa: E731


class _Page:
    def __init__(self, text):
        self.text = text

    def inner_text(self, sel, timeout=0):
        return self.text


class OvLoginHoldTest(unittest.TestCase):
    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.object(C, "OV_HOLD_PATH", d / "hold.json"),
            mock.patch.object(C, "OV_CREDS_PATH", d / "creds.json"),
            mock.patch.object(C, "app_dir", lambda: d),
            mock.patch.dict("os.environ", {}, clear=False),
        ]
        for p in self.patches:
            p.start()
        import os
        os.environ.pop("OWNERVILLE_USERNAME", None)
        os.environ.pop("OWNERVILLE_PASSWORD", None)
        C.save_ownerville_creds(CREDS["username"], CREDS["password"])

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _session(self, login_exc=None, rqst=None):
        def login(*a, **k):
            if login_exc:
                raise login_exc
        with mock.patch.object(K, "capture_rqst", return_value=rqst), \
                mock.patch.object(K, "login", side_effect=login) as lg:
            try:
                OV._session(object(), log=quiet)
                return lg.call_count, None
            except OV.KnocksProblem as e:
                return lg.call_count, str(e)

    def test_the_lock_screen_text_is_recognised(self):
        self.assertTrue(K.page_says_locked(_Page(
            "Account Permanently Locked\nYour account has been locked due to "
            "excessive failed login attempts.\nAdmin unlock required.")))
        self.assertTrue(K.page_says_locked(_Page("LOCKED - CONTACT SUPPORT")))
        self.assertFalse(K.page_says_locked(_Page("Password  Sign In")))

    def test_locked_stops_trying_and_says_who_to_email(self):
        n, msg = self._session(login_exc=K.AccountLocked("locked"))
        self.assertEqual(n, 1)
        self.assertIn("onboarding@ownerville.com", msg)
        n, msg = self._session(login_exc=K.AccountLocked("locked"))
        self.assertEqual(n, 0, "a held login must not be attempted again")
        self.assertIn("LOCKED", msg)
        self.assertIn("box asking for your OwnerVille password", msg)

    def test_one_failure_waits_an_hour_then_tries_once_more(self):
        n, _ = self._session(login_exc=RuntimeError("x"))
        self.assertEqual(n, 1)
        n, _ = self._session(login_exc=RuntimeError("x"))
        self.assertEqual(n, 0)
        hold = json.loads(C.OV_HOLD_PATH.read_text())
        hold["until"] = (dt.datetime.now() - dt.timedelta(minutes=1)
                         ).isoformat(timespec="seconds")
        C.OV_HOLD_PATH.write_text(json.dumps(hold))
        n, _ = self._session(login_exc=RuntimeError("x"))
        self.assertEqual(n, 1)

    def test_two_failures_on_one_password_hold_until_reentered(self):
        self._session(login_exc=RuntimeError("x"))
        hold = json.loads(C.OV_HOLD_PATH.read_text())
        hold["until"] = "2000-01-01T00:00:00"
        C.OV_HOLD_PATH.write_text(json.dumps(hold))
        self._session(login_exc=RuntimeError("x"))
        n, msg = self._session(login_exc=RuntimeError("x"))
        self.assertEqual(n, 0)
        self.assertIn("box asking for your OwnerVille password", msg)

    def test_reentering_the_same_password_clears_the_hold(self):
        self._session(login_exc=K.AccountLocked("locked"))
        C.save_ownerville_creds(CREDS["username"], CREDS["password"])
        self.assertEqual(OV.ov_hold_message(), "")

    def test_a_live_session_clears_the_hold(self):
        self._session(login_exc=RuntimeError("x"))
        n, msg = self._session(rqst="abc")
        self.assertIsNone(msg)
        self.assertFalse(C.OV_HOLD_PATH.exists())



class OvPasswordBoxTest(unittest.TestCase):
    """The fix comes to the owner: no "open Lucy Reports" (there is no such
    thing to open), a password box on their Mac instead (Megan 2026-10-12)."""

    def test_no_message_points_at_lucy_reports(self):
        import inspect
        src = inspect.getsource(OV)
        for line in src.splitlines():
            if line.strip().startswith('"') or line.strip().startswith('('):
                self.assertNotIn("open Lucy Reports", line)

    def test_the_box_exists_and_runs_the_ownerville_login(self):
        from automations.icd_alerts import autoprompt as AP
        spec = AP.SYSTEMS["ownerville_password"]
        self.assertEqual(spec["args"], ["--set-ownerville-login"])

    def test_the_knocks_failure_offers_the_box(self):
        import inspect
        from automations.icd_alerts import run as R
        src = inspect.getsource(R.cmd_knocks)
        self.assertIn('autoprompt.offer("ownerville_password"', src)

    def test_the_box_only_comes_once_trying_has_stopped(self):
        d = pathlib.Path(tempfile.mkdtemp())
        with mock.patch.object(C, "OV_HOLD_PATH", d / "h.json"), \
                mock.patch.object(C, "ownerville_creds", return_value=CREDS):
            self.assertFalse(OV.needs_password_box())
            OV._note_failure(CREDS, locked=False, log=quiet)
            self.assertFalse(OV.needs_password_box(), "one failure just waits")
            OV._note_failure(CREDS, locked=False, log=quiet)
            self.assertTrue(OV.needs_password_box())
            C.OV_HOLD_PATH.unlink()
            OV._note_failure(CREDS, locked=True, log=quiet)
            self.assertTrue(OV.needs_password_box())


if __name__ == "__main__":
    unittest.main()

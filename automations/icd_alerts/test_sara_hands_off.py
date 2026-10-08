"""SaraPlus hands-off (2026-10-08): the overnight catch-up never logs in
headless, a lost session only defers it, and a wall carries the night's
keep-alive history so we can tell idle-expiry from a hard lifetime."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import sales_closeout, sara_read


class ResumeOnlyTest(unittest.TestCase):
    def test_resume_only_raises_session_lost_instead_of_logging_in(self):
        page = mock.Mock()
        login = mock.Mock(name="_login")
        with mock.patch.object(sara_read, "_remembered_session", return_value="https://x"), \
             mock.patch.object(sara_read.S, "resume_session", return_value=""), \
             mock.patch.object(sara_read, "_forget_session"), \
             mock.patch.object(sara_read.C, "creds", return_value={"email": "e", "password": "p"}), \
             mock.patch.object(sara_read.S, "_login", login), \
             mock.patch.dict(sara_read._RESUME_ONLY, {"on": True}):
            with self.assertRaises(sara_read.SessionLost):
                sara_read._sign_in_raw(page, log=lambda *_: None)
        login.assert_not_called()

    def test_session_lost_is_not_an_account_problem(self):
        self.assertFalse(issubclass(sara_read.SessionLost, sara_read.AccountProblem))

    def test_read_day_resets_the_flag_even_when_it_raises(self):
        with mock.patch.object(sara_read, "_heal_and_login", side_effect=sara_read.SessionLost("x")), \
             mock.patch.object(sara_read, "sync_playwright", create=True) as sp:
            sp.return_value.__enter__.return_value = mock.Mock()
            try:
                sara_read.read_day(dt.date(2026, 10, 7), resume_only=True, log=lambda *_: None)
            except Exception:  # noqa: BLE001 -- only the flag matters here
                pass
        self.assertFalse(sara_read._RESUME_ONLY["on"])


class CloseoutDeferredTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "s.json"
        self.p = mock.patch.object(sales_closeout, "STATE", self.state)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_deferred_is_not_an_attempt(self):
        now = dt.datetime(2026, 10, 8, 2, 30)
        day = sales_closeout.due(now)
        self.assertIsNotNone(day)
        got = sales_closeout.maybe_run(lambda d: sales_closeout.DEFERRED, now=now,
                                       log=lambda *_: None)
        self.assertIsNone(got)
        self.assertEqual(sales_closeout.due(now), day, "still owed")
        state = json.loads(self.state.read_text()) if self.state.exists() else {}
        self.assertFalse(any(v for v in state.values() if isinstance(v, dict)
                             and v.get("attempts")), state)

    def test_deferred_code_matches_run(self):
        from automations.icd_alerts import run
        self.assertEqual(run.CATCHUP_DEFERRED, sales_closeout.DEFERRED)


class EvidenceTest(unittest.TestCase):
    def test_keepalive_log_and_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with mock.patch.object(sara_read, "KEEPALIVE_LOG_PATH", d / "k.json"), \
                 mock.patch.object(sara_read, "SESSION_SINCE_PATH", d / "since.txt"), \
                 mock.patch.object(sara_read, "SESSION_PATH", d / "sess.txt"):
                sara_read._remember_session("https://x")
                t = dt.datetime.now() + dt.timedelta(hours=2, minutes=5)
                sara_read._note_keepalive("kept", t)
                sara_read._note_keepalive("lost", t + dt.timedelta(minutes=10))
                ev = sara_read.session_evidence(now=t + dt.timedelta(minutes=10))
        self.assertIn("session age: 2h15m", ev)
        self.assertIn("kept@2h05m", ev)
        self.assertIn("lost@2h15m", ev)

    def test_evidence_never_raises_without_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with mock.patch.object(sara_read, "KEEPALIVE_LOG_PATH", d / "k.json"), \
                 mock.patch.object(sara_read, "SESSION_SINCE_PATH", d / "since.txt"), \
                 mock.patch.object(sara_read, "SESSION_PATH", d / "sess.txt"):
                self.assertIn("no log", sara_read.session_evidence())


if __name__ == "__main__":
    unittest.main()

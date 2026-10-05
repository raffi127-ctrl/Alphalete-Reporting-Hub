"""The ICD reader resumes its SaraPlus session between sweeps and only types
the password when SaraPlus turns the remembered session away (Kash 2026-09-30:
~30 logins an hour collided with his own phone)."""
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import sara_read as R
from automations.shared import saraplus as S

BASE = "https://www.saraplus.com/e/(S(abc123))/"


class _Page:
    def __init__(self, land, dashboard=True):
        self._land = land; self.url = ""; self.visited = []; self._dashboard = dashboard
    def goto(self, url, **kw):
        self.visited.append(url); self.url = self._land
    def wait_for_timeout(self, ms):
        pass
    def wait_for_selector(self, sel, **kw):
        self.waited = sel
        if not self._dashboard:
            raise TimeoutError("Timeout 15000ms exceeded.")


class ResumeSessionTest(unittest.TestCase):
    def test_a_honoured_session_is_resumed_without_a_login(self):
        page = _Page(BASE + "DealerPages/")
        self.assertEqual(S.resume_session(page, BASE, log=lambda *a: None), BASE)
        self.assertTrue(page.visited[0].endswith("/DealerPages/"))

    def test_the_login_ui_means_not_signed_in(self):
        self.assertIsNone(S.resume_session(_Page("https://ui.saraplus.com/"), BASE, log=lambda *a: None))

    def test_the_security_wall_means_not_signed_in(self):
        self.assertIsNone(S.resume_session(_Page(BASE + "Security/VerifyPasscode.aspx"), BASE, log=lambda *a: None))

    def test_no_memory_means_login(self):
        self.assertIsNone(S.resume_session(_Page(BASE + "DealerPages/"), "", log=lambda *a: None))


class SignInRawTest(unittest.TestCase):
    def _run(self, remembered, resume_returns):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "s.txt"
            if remembered:
                path.write_text(remembered)
            with mock.patch.object(R, "SESSION_PATH", path), \
                 mock.patch.object(R.C, "creds", lambda: {"email": "e", "password": "p"}), \
                 mock.patch.object(S, "resume_session", lambda page, base, log=print: resume_returns) as _, \
                 mock.patch.object(S, "_login", lambda *a, **k: "NEWBASE/") as login:
                out = R._sign_in_raw(object(), log=lambda *a: None)
                return out, (path.read_text() if path.exists() else None)

    def test_resumed_session_skips_the_password(self):
        out, kept = self._run(BASE, BASE)
        self.assertEqual(out, BASE); self.assertEqual(kept, BASE)

    def test_a_refused_session_logs_in_and_remembers_the_new_root(self):
        out, kept = self._run(BASE, None)
        self.assertEqual(out, "NEWBASE/"); self.assertEqual(kept, "NEWBASE/")

    def test_first_ever_sweep_logs_in(self):
        out, kept = self._run("", None)
        self.assertEqual(out, "NEWBASE/"); self.assertEqual(kept, "NEWBASE/")


if __name__ == "__main__":
    unittest.main()


class TheFaultSummaryKeepsItsInstruction(unittest.TestCase):
    """The passcode-wall message tells the owner what to do in its SECOND
    sentence; a 300-character cap cut it mid-word in Rashad's channel
    (2026-10-01). Every AccountProblem text must fit the relay's cap whole."""

    def test_every_account_problem_message_fits_the_cap(self):
        from automations.icd_alerts import relay as RL
        from automations.shared import saraplus as SP
        probes = []
        for cls in ("SaraPasscodeWall", "SaraPasswordChangeRequired", "SaraPasswordWall"):
            c = getattr(SP, cls, None)
            if c is not None:
                try:
                    probes.append(c("x"))
                except TypeError:
                    pass
        self.assertTrue(probes)
        for e in probes:
            msg = str(R._as_owner_problem(e))
            if msg:
                self.assertLessEqual(len(msg), RL.FAULT_SUMMARY_MAX, msg)


class ALoginPageThatNeverLoadsBecomesTheOwnersProblem(unittest.TestCase):
    """Cyrus's laptop 2026-09-29..10-01: hundreds of 30-second login timeouts
    a day with no hold. After three in a row it is an AccountProblem (hold +
    the sign-in window); a login that works clears the count."""

    class _PWTimeout(Exception):
        pass
    _PWTimeout.__name__ = "TimeoutError"

    def _run(self, fails, path):
        calls = []
        def login(*a, **k):
            calls.append(1)
            if len(calls) <= fails:
                raise self._PWTimeout("Timeout 30000ms exceeded. waiting for navigation until 'load'")
            return "BASE/"
        with mock.patch.object(R, "LOGIN_TIMEOUTS_PATH", path), \
             mock.patch.object(R, "SESSION_PATH", path.parent / "s.txt"), \
             mock.patch.object(R.C, "creds", lambda: {"email": "e", "password": "p"}), \
             mock.patch.object(S, "_login", login):
            return [self._one() for _ in range(fails + 1)]

    def _one(self):
        try:
            return R._sign_in_raw(object(), log=lambda *a: None)
        except Exception as e:  # noqa: BLE001
            return type(e).__name__

    def test_third_timeout_in_a_row_is_an_account_problem(self):
        with tempfile.TemporaryDirectory() as d:
            got = self._run(3, pathlib.Path(d) / "t.txt")
        self.assertEqual(got[:3], ["TimeoutError", "TimeoutError", "AccountProblem"])
        self.assertEqual(got[3], "BASE/")

    def test_a_working_login_clears_the_count(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "t.txt"
            got = self._run(2, path)
            self.assertEqual(got, ["TimeoutError", "TimeoutError", "BASE/"])
            self.assertFalse(path.exists())

    def test_the_message_fits_the_relay_and_names_the_window(self):
        from automations.icd_alerts import relay as RL
        msg = R.LOGIN_TIMEOUT_MESSAGE % 3
        self.assertLessEqual(len(msg), RL.FAULT_SUMMARY_MAX)
        self.assertIn("window", msg)

    def test_the_message_does_not_send_them_after_their_wifi(self):
        """The login page loads; only the submit never lands (Cyrus 9/26 on,
        while his knocks relayed fine). 'Check your internet' was wrong."""
        msg = R.LOGIN_TIMEOUT_MESSAGE % 75
        self.assertNotIn("Check that this computer's internet", msg)
        self.assertIn("password", msg)


class TheUrlIsNotProofOfASession(unittest.TestCase):
    """2026-10-02: expired sessions still landed on .../DealerPages/, were
    called resumed, and eight offices failed every report until 1pm."""

    def test_a_dead_session_that_keeps_its_url_is_not_resumed(self):
        page = _Page(BASE + "DealerPages/", dashboard=False)
        self.assertIsNone(S.resume_session(page, BASE, log=lambda *a: None))
        self.assertEqual(page.waited, S.COMBO_INPUT)

    def test_a_live_session_proves_itself_on_the_report_page(self):
        page = _Page(BASE + "DealerPages/")
        self.assertEqual(S.resume_session(page, BASE, log=lambda *a: None), BASE)
        self.assertTrue(page.visited[-1].endswith(S.HUB_PATH))

    def test_a_failed_read_forgets_the_session(self):
        import inspect
        src = inspect.getsource(R.read_day)
        i = src.index("S._run_report(page, base, day, C.SERVICE_INTERNET")
        self.assertIn("_forget_session()", src[i:i + 700])

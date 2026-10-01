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
    def __init__(self, land):
        self._land = land; self.url = ""; self.visited = []
    def goto(self, url, **kw):
        self.visited.append(url); self.url = self._land
    def wait_for_timeout(self, ms):
        pass


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

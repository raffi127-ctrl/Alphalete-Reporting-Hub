"""Overnight, the SaraPlus session is touched so it never idles out -- and a
keep-alive never logs in (Eveliz 2026-10-06: the 2am close-out's fresh login
was walled for an emailed code every morning)."""
import datetime as dt
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

from automations.icd_alerts import sara_read as R
from automations.shared import saraplus as S

BASE = "https://www.saraplus.com/e/(S(abc123))/"
NOW = dt.datetime(2026, 10, 7, 1, 30)


class _Ctx:
    pages = []
    closed = False
    def new_page(self):
        return object()
    def close(self):
        _Ctx.closed = True


class _PW:
    def __enter__(self):
        return object()
    def __exit__(self, *a):
        return False


class KeepAlive(unittest.TestCase):

    def _run(self, remembered=BASE, resume=BASE, last=None, busy=False):
        with tempfile.TemporaryDirectory() as d:
            sess = pathlib.Path(d) / "s.txt"
            kap = pathlib.Path(d) / "k.txt"
            if remembered:
                sess.write_text(remembered)
            if last:
                kap.write_text(last.isoformat())
            fake = types.ModuleType("patchright.sync_api")
            fake.sync_playwright = _PW
            logins = []
            with mock.patch.dict(sys.modules, {"patchright.sync_api": fake}), \
                 mock.patch.object(R, "SESSION_PATH", sess), \
                 mock.patch.object(R, "KEEPALIVE_PATH", kap), \
                 mock.patch.object(R, "signin_in_progress", lambda: busy), \
                 mock.patch.object(R, "_context", lambda p, h: _Ctx()), \
                 mock.patch.object(S, "resume_session",
                                   lambda page, base, log=print: resume), \
                 mock.patch.object(S, "_login",
                                   lambda *a, **k: logins.append(1)):
                did = R.keep_session_alive(log=lambda *a: None, now=NOW)
                kept = sess.read_text() if sess.exists() else None
            return did, kept, logins

    def test_a_live_session_is_kept(self):
        did, kept, logins = self._run()
        self.assertEqual(did, "kept")
        self.assertEqual(kept, BASE)
        self.assertEqual(logins, [])

    def test_an_expired_session_is_forgotten_never_logged_into(self):
        did, kept, logins = self._run(resume=None)
        self.assertEqual(did, "lost")
        self.assertIsNone(kept)
        self.assertEqual(logins, [], "a 3am login is what earns the code wall")

    def test_no_session_does_nothing(self):
        self.assertEqual(self._run(remembered="")[0], "none")

    def test_it_waits_ten_minutes_between_touches(self):
        did, *_ = self._run(last=NOW - dt.timedelta(minutes=4))
        self.assertEqual(did, "not-due")
        did, *_ = self._run(last=NOW - dt.timedelta(minutes=11))
        self.assertEqual(did, "kept")

    def test_it_stands_back_while_someone_signs_in(self):
        self.assertEqual(self._run(busy=True)[0], "busy")


if __name__ == "__main__":
    unittest.main()

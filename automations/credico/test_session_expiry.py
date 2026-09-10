"""Pins what a Credico session's expiry date means, and what we say about it.

Written after 2026-09-10, when credico_fetch failed on two consecutive Thursdays
(9/3 and 9/10) with a generic "session expired" and the incident post's standard
advice — `lucy rerun credico_fetch` — which cannot possibly work: a re-run
replays the same dead file. The token had been dead since 2026-09-03 15:16 UTC
and the saved state said so all along.

    python -m unittest automations.credico.test_session_expiry
"""
from __future__ import annotations

import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from automations.credico import session as S


def _jwt(exp_dt):
    """A token shaped like Credico's: header.payload.signature, exp in payload."""
    def b64(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{b64({'alg': 'RS256'})}.{b64({'exp': int(exp_dt.timestamp())})}.sig"


def _state(exp_dt, *, dot_expires=True, jwt=True):
    """A storage_state with the real shape: analytics cookies, auth in
    localStorage. Mirrors what `--login` writes."""
    auth = {"token_type": "bearer", "expires_in": 1209600}
    if jwt:
        auth["access_token"] = _jwt(exp_dt)
    if dot_expires:
        auth[".expires"] = exp_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    return {
        "cookies": [{"name": n, "domain": ".credico.com", "value": "x"}
                    for n in ("_ga", "_gid", "_gat", "_ga_B0ZC5F9X32")],
        "origins": [{"origin": S.BASE,
                     "localStorage": [{"name": "instanceenv", "value": '"USA"'},
                                      {"name": S.AUTH_KEY,
                                       "value": json.dumps(auth)}]}],
    }


class ExpiryReading(unittest.TestCase):
    def test_reads_dot_expires(self):
        want = datetime(2026, 9, 3, 15, 16, tzinfo=timezone.utc)
        self.assertEqual(S._state_expiry(_state(want)), want)

    def test_falls_back_to_the_jwt_when_dot_expires_is_gone(self):
        """.expires is a formatted string Credico could restyle; the JWT can't
        be reformatted away, so it is the backstop."""
        want = datetime(2026, 9, 3, 15, 16, tzinfo=timezone.utc)
        got = S._state_expiry(_state(want, dot_expires=False))
        self.assertEqual(got, want)

    def test_no_token_reads_as_unknown_not_as_valid(self):
        """A cookies-only state must never look like a live session — that is
        exactly the failure mode a cookie COUNT hides."""
        self.assertIsNone(S._state_expiry({"cookies": [{"name": "_ga"}],
                                           "origins": []}))


class WhatWeTellTheHuman(unittest.TestCase):
    def test_expired_says_the_date_and_how_long_ago(self):
        exp = datetime.now(timezone.utc) - timedelta(days=6)
        note = S._expiry_note(exp)
        self.assertIn("2026" if exp.year == 2026 else str(exp.year), note)
        self.assertIn("ago", note)

    def test_a_rerun_is_ruled_out_in_words(self):
        """The incident post offers `lucy rerun` for every failure. For this one
        it replays the same dead token, so the message has to say so — three
        re-runs were spent on it before anyone read the date."""
        self.assertIn("RE-RUN CANNOT FIX THIS", S.RELOGIN_STEPS)
        self.assertIn("--login", S.RELOGIN_STEPS)
        self.assertIn("set_credico_state", S.RELOGIN_STEPS)

    def test_it_points_at_lucy_1_where_credico_fetch_runs(self):
        self.assertIn("Lucy 1", S.RELOGIN_STEPS)

    def test_warn_window_outlasts_the_weekly_cadence(self):
        """credico_fetch is weekly. A warning window shorter than 7 days would
        first appear on the run that already failed."""
        self.assertGreater(S.WARN_DAYS, 7)


class FailsFastWithoutABrowser(unittest.TestCase):
    def _with_state(self, state):
        """Point the module at a temp state file and open a session."""
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / ".credico_storage_state.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        real, S.STATE = S.STATE, path
        self.addCleanup(lambda: setattr(S, "STATE", real))
        return S.credico_session(headless=True)

    def test_expired_state_raises_before_launching_anything(self):
        """No patchright import, no chromium, no page load — the date alone is
        enough, and this is what makes the failure legible in the log."""
        exp = datetime.now(timezone.utc) - timedelta(days=6)
        with self.assertRaises(RuntimeError) as cm:
            self._with_state(_state(exp)).__enter__()
        msg = str(cm.exception)
        self.assertIn("EXPIRED", msg)
        self.assertIn("RE-RUN CANNOT FIX THIS", msg)

    def test_session_expiry_helper_agrees_with_the_file(self):
        exp = datetime.now(timezone.utc) + timedelta(days=13)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "state.json"
        path.write_text(json.dumps(_state(exp)), encoding="utf-8")
        got, days = S.session_expiry(path)
        self.assertEqual(got.date(), exp.date())
        self.assertGreater(days, 12)

    def test_missing_state_says_how_to_make_one(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        real, S.STATE = S.STATE, Path(tmp.name) / "nope.json"
        self.addCleanup(lambda: setattr(S, "STATE", real))
        with self.assertRaises(RuntimeError) as cm:
            S.credico_session().__enter__()
        self.assertIn("--login", str(cm.exception))


class NoUnattendedLogin(unittest.TestCase):
    def test_no_password_is_read_from_anywhere(self):
        """The whole auth model: the automation never types credentials. If a
        future change wires creds.py in here, this is the tripwire."""
        src = Path(S.__file__).read_text(encoding="utf-8")
        for banned in ("creds.", "password=", "PASSWORD"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()

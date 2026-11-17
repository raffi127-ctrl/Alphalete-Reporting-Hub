"""Lucy's own Apex sign-in (apex_login) and its one-time setup (apex_2fa_setup)."""
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import apex_login as L

# RFC 6238 appendix B: the SHA1 secret is ASCII "12345678901234567890".
RFC_KEY = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class Code(unittest.TestCase):
    def test_rfc6238_vectors(self):
        # The RFC's 8-digit answers; an app shows the last 6.
        for t, want in ((59, "94287082"), (1111111109, "07081804"),
                        (1234567890, "89005924"), (2000000000, "69279037")):
            self.assertEqual(L.totp(RFC_KEY, t, digits=8), want, t)
            self.assertEqual(L.totp(RFC_KEY, t), want[-6:], t)

    def test_key_as_apex_prints_it(self):
        # Spaces and lower case, the way the configure page shows it.
        spaced = " ".join(RFC_KEY[i:i + 4] for i in range(0, 32, 4)).lower()
        self.assertEqual(L.clean_key(spaced), RFC_KEY)
        self.assertEqual(L.totp(spaced, 59), "287082")

    def test_not_a_key(self):
        for bad in ("", "hello", "1234 5678 9012 3456", "taop ccrx"):
            with self.assertRaises(ValueError):
                L.clean_key(bad)

    def test_key_read_off_the_configure_page(self):
        spaced = " ".join(RFC_KEY[i:i + 4] for i in range(0, 32, 4)).lower()
        page = ("Configure authenticator app\nTo use an authenticator app go through the "
                "following steps:\nScan the QR Code or enter this key %s into your two "
                "factor authenticator app. Spaces and casing do not matter.\nVerification Code"
                % spaced)
        self.assertEqual(L.key_from_page(page), RFC_KEY)
        with self.assertRaises(ValueError):
            L.key_from_page("Two-factor authentication\nUse Authenticator Use SMS")

    def test_fresh_code_waits_out_a_dying_one(self):
        slept = []
        clock = [89.0]                       # 1s left in its 30s window
        def now():
            return clock[0]
        def sleep(s):
            slept.append(s)
            clock[0] += s
        code = L.fresh_code(RFC_KEY, now=now, sleep=sleep)
        self.assertEqual(len(slept), 1)
        self.assertEqual(code, L.totp(RFC_KEY, clock[0]))
        self.assertEqual(int(clock[0]) // 30, 3)       # the NEXT window

    def test_fresh_code_no_wait_when_plenty_left(self):
        slept = []
        L.fresh_code(RFC_KEY, now=lambda: 61.0, sleep=slept.append)
        self.assertEqual(slept, [])


class Saved(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        for name, val in (("CREDS_PATH", d / "apex-login.json"),
                          ("STATE_PATH", d / "apex-login-state.json")):
            p = mock.patch.object(L, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(L.C, "app_dir", lambda: d)
        p.start()
        self.addCleanup(p.stop)

    def test_round_trip_and_owner_only(self):
        L.save_creds("jruiz", "pw", RFC_KEY.lower())
        self.assertEqual(L.creds(), {"username": "jruiz", "password": "pw",
                                     "totp_key": RFC_KEY})
        if os.name == "posix":
            self.assertEqual(L.CREDS_PATH.stat().st_mode & 0o777, 0o600)

    def test_nothing_saved_is_empty(self):
        self.assertEqual(L.creds(), {})

    def test_stops_after_two_failures_and_a_new_login_clears_it(self):
        L._record(False, "code box")
        self.assertFalse(L.stopped())
        L._record(False, "code box")
        self.assertTrue(L.stopped())
        L.save_creds("jruiz", "pw", RFC_KEY)
        self.assertFalse(L.stopped())

    def test_success_resets_the_count(self):
        L._record(False, "x")
        L._record(True, "x")
        L._record(False, "x")
        self.assertFalse(L.stopped())


class Wiring(unittest.TestCase):
    def test_cloudflare_wait_never_shortened(self):
        # resources/lucy-login-standard.md: the 20-30s pause IS the fix.
        self.assertGreaterEqual(L.PRE_SUBMIT_WAIT_S, 20)

    def test_pnl_signs_in_alone_only_with_saved_login_and_not_stopped(self):
        from automations.icd_alerts import pnl
        src = inspect.getsource(pnl.read_apex)
        i_creds, i_stop, i_sign = (src.index("L.creds()"), src.index("L.stopped()"),
                                   src.index("L.sign_in("))
        self.assertLess(i_creds, i_stop)
        self.assertLess(i_stop, i_sign)
        # ...and inside the locked browser: the lock goes on first.
        self.assertLess(src.index('G.install(ctx, "block")'), i_sign)

    def test_setup_window_is_off_until_eve_says(self):
        from automations.icd_alerts import pnl
        self.assertEqual(pnl.APEX_SETUP_KEYS, frozenset())

    def test_setup_saves_only_after_verify_and_owner_presses_it(self):
        from automations.icd_alerts import apex_2fa_setup as S
        src = inspect.getsource(S.run)
        self.assertLess(src.index("_verified(page)"), src.index("L.save_creds("))
        self.assertLess(src.index('G.install(ctx, "watch")'), src.index("page.goto"))
        self.assertNotIn("Verify\").click", src)
        self.assertNotIn('Verify").click', src)

    def test_proof_runs_under_the_lock(self):
        from automations.icd_alerts import apex_2fa_setup as S
        src = inspect.getsource(S.prove)
        self.assertLess(src.index('G.install(ctx, "block")'), src.index("L.sign_in("))

    def test_autoprompt_knows_the_setup(self):
        from automations.icd_alerts import autoprompt as AU
        self.assertEqual(AU.SYSTEMS["apex_2fa"]["module"],
                         "automations.icd_alerts.apex_2fa_setup")

    def test_shipped_to_eco(self):
        files = (Path(L.__file__).parent / "agent_files.txt").read_text()
        for m in ("apex_login.py", "apex_2fa_setup.py"):
            self.assertIn("automations/icd_alerts/" + m, files)


if __name__ == "__main__":
    unittest.main()

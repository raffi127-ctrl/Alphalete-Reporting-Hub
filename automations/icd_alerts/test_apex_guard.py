"""The Apex lock: Lucy reads payroll, never changes it (apex_guard)."""
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import apex_guard as G


class FakeRoute:
    def __init__(self, method, url):
        self.request = mock.Mock(method=method, url=url)
        self.did = None

    def continue_(self):
        self.did = "continue"

    def abort(self, why=None):
        self.did = "abort"


class AllowList(unittest.TestCase):
    def test_pinned_to_what_the_probe_measured(self):
        # Probe 2026-11-16 (Lucy 2): the ONLY write the read path needs.
        # Changing this list is a decision, not a refactor.
        self.assertEqual(G.ALLOWED_WRITES, {
            ("apexapi.herbjoyent.com", "/auth/token"),
            # Lucy's own sign-in (apex_login): password form + 2-step form.
            ("apex.herbjoyent.com", "/identity/account/login"),
            ("apex.herbjoyent.com", "/identity/account/loginwith2fa"),
            ("apex.herbjoyent.com", "/account/sendcode"),
            ("apex.herbjoyent.com", "/account/verifycode"),
            ("apex.herbjoyent.com", "/identity/account/sendcode"),
            ("apex.herbjoyent.com", "/identity/account/verifycode"),
        })

    def test_signin_forms_pass_but_not_the_rest_of_identity(self):
        self.assertTrue(G.allowed("POST", "https://apex.herbjoyent.com/Identity/Account/Login?ReturnUrl=%2F"))
        self.assertTrue(G.allowed("POST", "https://apex.herbjoyent.com/Identity/Account/LoginWith2fa"))
        for path in ("/Identity/Account/Register", "/Identity/Account/LoginWithRecoveryCode",
                     "/Identity/Account/ForgotPassword", "/Identity/Account/Manage/EnableAuthenticator",
                     "/Identity/Account/Manage/Disable2fa"):
            self.assertFalse(G.allowed("POST", "https://apex.herbjoyent.com" + path), path)

    def test_reads_pass(self):
        for m in ("GET", "head", "OPTIONS"):
            self.assertTrue(G.allowed(m, "https://apex.herbjoyent.com/payrolls?x=1"))

    def test_token_refresh_passes_even_with_doubled_slash(self):
        self.assertTrue(G.allowed("POST", "https://apexapi.herbjoyent.com//auth/token"))
        self.assertTrue(G.allowed("POST", "https://APEXAPI.herbjoyent.com/auth/token/"))

    def test_every_change_to_apex_is_stopped(self):
        for m in ("POST", "PUT", "PATCH", "DELETE"):
            for url in ("https://apexapi.herbjoyent.com/payrolls/123",
                        "https://apexapi.herbjoyent.com/payroll/approve",
                        "https://apex.herbjoyent.com/api/employees/9"):
                self.assertFalse(G.allowed(m, url), (m, url))

    def test_token_path_is_exact_not_a_prefix(self):
        for url in ("https://apexapi.herbjoyent.com/auth/token/revoke",
                    "https://apexapi.herbjoyent.com/auth/tokens",
                    "https://apex.herbjoyent.com/auth/token",       # other host
                    "https://evil.example/auth/token"):
            self.assertFalse(G.allowed("POST", url), url)

    def test_probe_extras_are_blocked(self):
        self.assertFalse(G.allowed("POST", "https://apex.herbjoyent.com/cdn-cgi/rum"))
        self.assertFalse(G.allowed(
            "POST", "https://o418336.ingest.sentry.io/api/1/envelope/"))

    def test_account_pages_stopped_even_for_a_get(self):
        # A GET of EnableAuthenticator wrote a key onto Carlos's account
        # (2026-11-17). Opening an account page is a change on Apex.
        for url in ("https://apex.herbjoyent.com/Identity/Account/Manage/EnableAuthenticator",
                    "https://apex.herbjoyent.com/identity/account/manage",
                    "https://apex.herbjoyent.com/Identity/Account/Manage/ResetAuthenticator",
                    "https://apex.herbjoyent.com/Manage/AddPhoneNumber",
                    "https://apexapi.herbjoyent.com/Identity/Account/Manage/x"):
            self.assertFalse(G.allowed("GET", url), url)

    def test_signin_and_payroll_pages_still_open(self):
        for url in ("https://apex.herbjoyent.com/Identity/Account/Login",
                    "https://apex.herbjoyent.com/Identity/Account/LoginWith2fa",
                    "https://apex.herbjoyent.com/payrolls",
                    "https://apex.herbjoyent.com/"):
            self.assertTrue(G.allowed("GET", url), url)

    def test_cloudflare_human_check_passes(self):
        self.assertTrue(G.allowed(
            "POST", "https://apex.herbjoyent.com/cdn-cgi/challenge-platform/h/b/flow/ov1/x"))
        self.assertTrue(G.allowed("POST", "https://challenges.cloudflare.com/cdn-cgi/x"))
        self.assertFalse(G.allowed("POST", "https://apex.herbjoyent.com/cdn-cgi/challenge"))


class Modes(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        p = mock.patch.object(G, "GUARD_FILE", Path(d) / "apex-guard.json")
        p.start()
        self.addCleanup(p.stop)

    def test_block_aborts_and_writes_down_no_query(self):
        g = G.Guard("block")
        r = FakeRoute("POST", "https://apexapi.herbjoyent.com/payrolls/1?amount=999")
        g.handle(r)
        self.assertEqual(r.did, "abort")
        ok = FakeRoute("GET", "https://apex.herbjoyent.com/payrolls")
        g.handle(ok)
        self.assertEqual(ok.did, "continue")
        g.save()
        saved = G.GUARD_FILE.read_text()
        self.assertIn("POST apexapi.herbjoyent.com/payrolls/1", saved)
        self.assertNotIn("999", saved)
        self.assertEqual(json.loads(saved)["block"],
                         {"POST apexapi.herbjoyent.com/payrolls/1": 1})

    def test_watch_lets_a_person_through_but_writes_it_down(self):
        g = G.Guard("watch")
        r = FakeRoute("POST", "https://apexapi.herbjoyent.com/auth/login")
        g.handle(r)
        self.assertEqual(r.did, "continue")
        g.save()
        self.assertIn("sign-in window sent: POST apexapi.herbjoyent.com/auth/login x1",
                      G.summary())

    def test_install_routes_everything(self):
        ctx = mock.Mock()
        g = G.install(ctx)
        ctx.route.assert_called_once_with("**/*", g.handle)
        self.assertEqual(g.mode, "block")

    def test_bad_mode_refused(self):
        with self.assertRaises(ValueError):
            G.Guard("off")


class WiredIn(unittest.TestCase):
    """The lock goes on before Apex is opened, in both browsers."""

    def test_pnl_read_installs_block_before_any_navigation(self):
        from automations.icd_alerts import pnl
        src = inspect.getsource(pnl.read_apex)
        self.assertIn('G.install(ctx, "block")', src)
        self.assertIn("G.launch_args()", src)
        self.assertLess(src.index('G.install(ctx, "block")'),
                        src.index("goto_payroll_entry"))
        # A lock that fails to go on means Apex is not opened.
        after = src[src.index('G.install(ctx, "block")'):]
        self.assertLess(after.index("return"), after.index("goto_payroll_entry"))

    def test_signin_window_watches_before_opening_apex(self):
        from automations.icd_alerts import apex_signin
        src = inspect.getsource(apex_signin.run)
        self.assertIn('G.install(ctx, "watch")', src)
        self.assertIn("G.launch_args()", src)
        self.assertLess(src.index('G.install(ctx, "watch")'),
                        src.index("page.goto"))

    def test_service_workers_off(self):
        self.assertEqual(G.launch_args(), {"service_workers": "block"})

    def test_shipped_to_eco(self):
        from automations.icd_alerts import config as C  # noqa: F401
        files = (Path(G.__file__).parent / "agent_files.txt").read_text()
        self.assertIn("automations/icd_alerts/apex_guard.py", files)


class SummaryShowsSignInFirst(unittest.TestCase):
    """11/23: hundreds of analytics posts filled the 300 characters and the
    sign-in requests Jairo's setup sent were cut off the line."""

    def test_noise_goes_last(self):
        seen = {"POST apex.herbjoyent.com/cdn-cgi/rum": 1023,
                "POST o418336.ingest.sentry.io/api/5320796/envelope": 145,
                "PUT apexapi.herbjoyent.com/services/shim-tests/http-put": 1,
                "POST apex.herbjoyent.com/identity/account/login": 1}
        with mock.patch.object(G, "load", return_value={"watch": seen}):
            line = G.summary(limit=80)
        self.assertIn("identity/account/login", line)
        self.assertNotIn("sentry", line)


class SetupDeadlinesKeepTheReason(unittest.TestCase):
    def test_end_list_is_never_rebound(self):
        from automations.icd_alerts import apex_2fa_setup as S
        src = inspect.getsource(S._run)
        self.assertNotIn("end = ", src.replace("end[0] = ", ""))



class SendCodeConfirmed(unittest.TestCase):
    def test_apex_sendcode_post_passes(self):
        # the exact request the lock stopped on Jairo's Mac 2026-11-24 11:11
        self.assertTrue(G.allowed("POST", "https://apex.herbjoyent.com/Account/SendCode"))
        self.assertTrue(G.allowed("POST", "https://apex.herbjoyent.com/Account/VerifyCode?returnUrl=%2F"))
        self.assertFalse(G.allowed("POST", "https://apex.herbjoyent.com/Account/Manage"))


if __name__ == "__main__":
    unittest.main()

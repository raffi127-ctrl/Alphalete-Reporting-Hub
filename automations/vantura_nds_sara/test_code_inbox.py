"""config.code_inbox: the passcode is read from alphaletegp's own inbox when
its app password is on the machine, else from the reporting inbox -- and the
rc login threads that choice through to verify_code (2026-10-24)."""
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.vantura_nds_sara import config as CFG


class CodeInbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / ".config" / "recruiting-report"
        self.cfg.mkdir(parents=True)
        self.p = mock.patch.object(CFG, "config_dir", lambda: self.cfg)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_no_file_means_the_reporting_inbox(self):
        self.assertIsNone(CFG.code_inbox())
        s = CFG.code_inbox_status()
        self.assertIn("reporting inbox", s)
        self.assertIn(CFG.CODE_INBOX_ACCOUNT, s)
        self.assertIn(CFG.PUSH_CODE_INBOX_CMD, s)

    def test_file_means_that_inbox_directly(self):
        (self.cfg / CFG.CODE_INBOX_KEY).write_text("abcd efgh ijkl mnop\n")
        ib = CFG.code_inbox()
        self.assertEqual(ib[0], "alphaletegp@gmail.com")
        self.assertEqual(ib[1], self.cfg / CFG.CODE_INBOX_KEY)
        self.assertIn("directly", CFG.code_inbox_status())
        # never the password
        self.assertNotIn("abcd", CFG.code_inbox_status())

    def test_the_key_is_whitelisted_for_the_push(self):
        from automations.day_orchestrator import mini_control as MC
        self.assertIn(CFG.CODE_INBOX_KEY, MC._CRED_FILES)
        self.assertEqual(MC._CRED_FILES[CFG.CODE_INBOX_KEY]().name, CFG.CODE_INBOX_KEY)


class RcLoginThreadsTheInbox(unittest.TestCase):
    def test_login_accepts_code_inbox(self):
        from automations.rc_contact_sync import sara
        self.assertIn("code_inbox", inspect.signature(sara.login).parameters)
        self.assertIn("code_inbox", inspect.signature(sara._verify_browser).parameters)

    def test_verify_browser_passes_the_inbox_to_wait_for_code(self):
        from automations.rc_contact_sync import sara
        seen = {}

        class Page:
            url = "https://x/Security/VerifyPasscode.aspx"

            def wait_for_load_state(self, *a, **k):
                pass

            def wait_for_timeout(self, *a, **k):
                pass

        def fake_wait(since, **kw):
            seen.update(kw)
            Page.url = "https://x/DealerPages/"
            return "123456"

        with mock.patch.object(sara, "_settle", lambda p: None), \
             mock.patch.object(sara, "_request_code", lambda p, log=print: True), \
             mock.patch.object(sara, "_code_field", lambda p: "box"), \
             mock.patch.object(sara, "_submit_code", lambda p, f, c: None), \
             mock.patch.object(sara.VC, "wait_for_code", fake_wait):
            sara._verify_browser(Page(), log=lambda *a: None,
                                 code_inbox=("alphaletegp@gmail.com", "/p"))
        self.assertEqual(seen.get("inbox"), ("alphaletegp@gmail.com", "/p"))

    def test_inbox_name(self):
        from automations.rc_contact_sync import sara
        self.assertEqual(sara._inbox_name(("a@b.c", "/p")), "a@b.c")
        self.assertEqual(sara._inbox_name(None), sara.VC._ing.ACCOUNT)


if __name__ == "__main__":
    unittest.main()

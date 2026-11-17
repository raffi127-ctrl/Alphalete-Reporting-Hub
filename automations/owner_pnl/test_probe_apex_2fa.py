import inspect
import unittest

from automations.owner_pnl import probe_apex_2fa as P


class Probe2fa(unittest.TestCase):
    def test_mask_hides_phones_money_emails(self):
        out = P.mask("Text to (512) 555-0199, pay $1,234.50, carlos@x.com")
        self.assertNotRegex(out, r"\d")
        self.assertNotIn("carlos@x.com", out)

    def test_secret_key_line_never_logged(self):
        out = P.mask("Scan the QR Code or enter this key taop ccrx rdna weo4 into your app.")
        self.assertNotIn("taop", out)
        self.assertNotIn("ccrx", out)

    def test_candidates_same_site_no_logout(self):
        base = "https://apex.herbjoyent.com/"
        links = [("/profile", "My Profile"), ("/payrolls", "Payroll"),
                 ("/logout", "Log out"), ("https://other.com/security", "x"),
                 ("/x", "Security settings"), ("#", "Account")]
        c = P.candidates(base, links)
        self.assertEqual(c[:2], [base + "profile", base + "x"])
        self.assertNotIn(base + "logout", c)
        self.assertNotIn(base + "payrolls", c)
        self.assertTrue(all(u.startswith(base) for u in c))

    def test_keywords(self):
        lines = P.keyword_lines("Name\nTwo-Factor Authentication\nUse an authenticator app\nSave")
        self.assertEqual(lines, ["Two-Factor Authentication", "Use an authenticator app"])

    def test_lock_goes_on_before_any_page_and_nothing_is_clicked(self):
        src = inspect.getsource(P.main)
        self.assertLess(src.index('G.install(ctx, "block")'), src.index("page.goto"))
        self.assertNotIn(".click(", src)


if __name__ == "__main__":
    unittest.main()

"""A forced password change must SAY it is a forced password change.

2026-09-12: the sales board sweep ('Sales Text Updates') failed three passes
in a row and the only thing the channel got was

    SaraError: logged in but landed somewhere unexpected:
    https://www.saraplus.com/e/(S(...))/Security/ResetPassword.aspx

which reads like SaraPlus moved a page. It had not. The login WORKED -- the
session id in that url is proof -- and SaraPlus was refusing to serve anything
else until somebody set a new password by hand. These tests pin the wording so
the next one costs a read, not a diagnosis.
"""
import unittest

from automations.shared import saraplus as sp

RESET_URL = ("https://www.saraplus.com/e/(S(ujsu4nwkbwvzfsicqn3xd00l))"
             "/Security/ResetPassword.aspx")
GOOD_URL = "https://www.saraplus.com/e/(S(abc123))/DealerPages/Default.aspx"


class _Page:
    """The smallest page that walks _login's happy path up to the url check."""

    def __init__(self, landing):
        self.url = landing

    # --- the calls _login makes, all no-ops ---
    def goto(self, *a, **k): pass
    def click(self, *a, **k): pass
    def fill(self, *a, **k): pass
    def wait_for_selector(self, *a, **k): pass
    def locator(self, *a, **k): return _Field()
    def expect_navigation(self, *a, **k): return _Nav()


class _Field:
    def type(self, *a, **k): pass


class _Nav:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class ResetPasswordTest(unittest.TestCase):
    def _fail(self, url):
        with self.assertRaises(sp.SaraError) as cm:
            sp.login(_Page(url), "somebody@example.com", "pw",
                     creds_hint="/tmp/creds.json")
        return str(cm.exception)

    def test_reset_page_is_named_as_a_password_change(self):
        msg = self._fail(RESET_URL)
        self.assertIn("PASSWORD CHANGE", msg)
        self.assertNotIn("somewhere unexpected", msg)

    def test_message_says_whose_account_and_how_to_fix_it(self):
        msg = self._fail(RESET_URL)
        self.assertIn("somebody@example.com", msg)          # which account
        self.assertIn("set_credentials", msg)               # the command
        self.assertIn("/tmp/creds.json", msg)               # the file it writes
        self.assertIn(sp.LOGIN_URL, msg)                    # where to go

    def test_message_says_a_retry_will_not_help(self):
        # The sweep runs every 5 minutes; without this the channel gets the
        # same alert forever and nobody knows it needs a human.
        self.assertIn("retry cannot", self._fail(RESET_URL))

    def test_nothing_was_read_or_written(self):
        self.assertIn("Nothing was read", self._fail(RESET_URL))

    def test_a_normal_landing_still_returns_the_dealer_root(self):
        base = sp.login(_Page(GOOD_URL), "somebody@example.com", "pw")
        self.assertEqual(base, "https://www.saraplus.com/e/(S(abc123))/")

    def test_other_unexpected_pages_keep_the_old_error(self):
        msg = self._fail("https://www.saraplus.com/e/(S(x))/Security/Oops.aspx")
        self.assertIn("somewhere unexpected", msg)


if __name__ == "__main__":
    unittest.main()

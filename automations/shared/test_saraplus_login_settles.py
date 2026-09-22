"""The login waits for the post-submit redirect before calling itself a
failure, and says what the page said when it does (Khalil, 2026-09-21)."""
import unittest

from automations.shared import saraplus as sp
from automations.icd_alerts import sara_read


class _Nav:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Field:
    @property
    def first(self): return self
    def click(self, *a, **k): pass
    def type(self, *a, **k): pass
    def press_sequentially(self, *a, **k): pass
    def get_attribute(self, *a, **k): return "https://x/login.aspx"


class _Page:
    """Lands on `urls[0]`, and every poll after the submit advances one url."""
    def __init__(self, urls, says=""):
        self._urls = list(urls); self.url = self._urls.pop(0)
        self.polls = 0; self._says = says
    def goto(self, *a, **k): pass
    def fill(self, *a, **k): pass
    def click(self, *a, **k): pass
    def wait_for_selector(self, *a, **k): pass
    def locator(self, *a, **k): return _Field()
    def expect_navigation(self): return _Nav()
    def wait_for_timeout(self, ms):
        self.polls += 1
        if self._urls: self.url = self._urls.pop(0)
    def evaluate(self, js): return self._says


LOGIN = "https://www.saraplus.com/e/(S(abc))/servicepages/login.aspx"
DEALER = "https://www.saraplus.com/e/(S(abc))/DealerPages/Default.aspx"


class LoginSettlesTest(unittest.TestCase):
    def test_a_late_redirect_is_a_success(self):
        page = _Page([LOGIN, LOGIN, LOGIN, DEALER])
        base = sp._login(page, "e", "p")
        self.assertEqual(base, "https://www.saraplus.com/e/(S(abc))/")
        self.assertEqual(page.polls, 3)

    def test_a_fast_login_does_not_wait(self):
        page = _Page([DEALER])
        sp._login(page, "e", "p")
        self.assertEqual(page.polls, 0)

    def test_a_real_bounce_still_fails_and_quotes_the_page(self):
        page = _Page([LOGIN], says="Invalid login. Please try again.")
        with self.assertRaises(sp.SaraError) as cm:
            sp._login(page, "e", "p")
        msg = str(cm.exception)
        self.assertIn("still on the login page", msg)
        self.assertIn("Invalid login", msg)
        self.assertGreaterEqual(page.polls, sp.LOGIN_SETTLE_MS // sp.LOGIN_POLL_MS)

    def test_a_bounce_with_a_page_error_tells_the_owner_to_re_enter(self):
        page = _Page([LOGIN], says="Invalid login.")
        with self.assertRaises(sp.SaraError) as cm:
            sp._login(page, "e", "p")
        self.assertIn("did not accept", str(sara_read._as_owner_problem(cm.exception)))

    def test_a_silent_bounce_does_not_blame_the_password(self):
        page = _Page([LOGIN], says="")
        with self.assertRaises(sp.SaraError) as cm:
            sp._login(page, "e", "p")
        owner = str(sara_read._as_owner_problem(cm.exception))
        self.assertNotIn("did not accept", owner)
        self.assertIn("do NOT change your password", owner)


if __name__ == "__main__":
    unittest.main()

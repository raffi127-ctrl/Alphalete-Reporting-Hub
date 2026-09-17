"""The passcode wall is a BROWSER problem, and these pin that reading.

2026-09-17, Khalil's machine. SaraPlus answered his sign-in with
`/Security/VerifyPasscode.aspx` carrying a session id -- which means the
password was accepted and SaraPlus is challenging the browser. It was read as
an expired account twice in one morning, and the code's own notes already
record two password changes that bought nothing.

The trap worth keeping closed: `_heal_and_login` answers that page by throwing
the Chrome profile away and retrying. A new profile is a new BROWSER, so the
retry earns a fresh challenge, and "the wall survived a new profile" then
reads as proof of an expired account. It is the heal feeding the wall.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.icd_alerts import config as C
from automations.icd_alerts import sara_read as R
from automations.icd_alerts import sara_signin as X

SESSION = "https://www.saraplus.com/e/(S(qvxtpep3hkijen2pmu1hwdge))"


class TheSecurityWallIsNotSuccessTest(unittest.TestCase):
    def test_the_passcode_page_is_not_signed_in(self):
        """The bug this exists to stop: a 'no password field' test calls the
        security page a success and sends somebody away from the one screen
        they had to finish."""
        self.assertFalse(X._signed_in(SESSION + "/Security/VerifyPasscode.aspx"))
        self.assertTrue(X._still_challenged(
            SESSION + "/Security/VerifyPasscode.aspx"))

    def test_the_reset_page_is_also_the_security_area(self):
        """ResetPassword.aspx lives under /Security/ too -- which is why its
        words are not evidence about the account."""
        self.assertFalse(X._signed_in(SESSION + "/Security/ResetPassword.aspx"))
        self.assertTrue(X._still_challenged(
            SESSION + "/Security/ResetPassword.aspx"))

    def test_the_hub_is_signed_in(self):
        self.assertTrue(X._signed_in(SESSION + "/DealerPages/SubmitOrders.aspx"))
        self.assertTrue(X._signed_in(SESSION + "/Reports/Anything.aspx"))

    def test_the_bare_login_is_not_signed_in(self):
        self.assertFalse(X._signed_in("https://ui.saraplus.com"))
        self.assertFalse(X._signed_in(""))


class TheSweepStandsBackWhileSomebodyTypesTest(unittest.TestCase):
    """They share one Chrome profile and Chromium will not open it twice."""

    def setUp(self):
        C.SARA_SIGNIN_LOCK.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._clear)

    def _clear(self):
        try:
            C.SARA_SIGNIN_LOCK.unlink()
        except OSError:
            pass

    def test_a_fresh_lock_holds_the_sweep_off(self):
        C.SARA_SIGNIN_LOCK.write_text(dt.datetime.now().isoformat())
        self.assertTrue(R.signin_in_progress())

    def test_a_stale_lock_is_ignored(self):
        """Noise, never silence: a crashed sign-in must not mute this office
        for the rest of the afternoon."""
        old = dt.datetime.now() - dt.timedelta(
            minutes=C.SARA_SIGNIN_LOCK_MINUTES + 5)
        C.SARA_SIGNIN_LOCK.write_text(old.isoformat())
        self.assertFalse(R.signin_in_progress())

    def test_an_unreadable_lock_is_ignored(self):
        C.SARA_SIGNIN_LOCK.write_text("not a date")
        self.assertFalse(R.signin_in_progress())

    def test_no_lock_at_all_is_ignored(self):
        self._clear()
        self.assertFalse(R.signin_in_progress())

    def test_sara_and_box_locks_are_separate_files(self):
        """One office can sell both; holding one must not mute the other."""
        self.assertNotEqual(C.SARA_SIGNIN_LOCK, C.SC_SIGNIN_LOCK)


if __name__ == "__main__":
    unittest.main()

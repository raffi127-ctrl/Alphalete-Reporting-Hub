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


class TheWindowWatchesTheLivePageTest(unittest.TestCase):
    """Francia signed in and typed the code on 2026-09-18 AND 2026-09-21, and
    the Terminal never noticed. page.url is a cached value in the sync API,
    refreshed only while a Playwright call runs -- and the loop waited with
    time.sleep, so it stayed frozen on the login address forever. Proven
    against a real browser before this was changed."""

    class _Page:
        def __init__(self, live, cached="https://ui.saraplus.com"):
            self.live, self.url = live, cached

        def evaluate(self, _js):
            return self.live

    class _Ctx:
        def __init__(self, pages):
            self.pages = pages

    def test_it_asks_the_page_not_the_cache(self):
        ctx = self._Ctx([self._Page(SESSION + "/DealerPages/SubmitOrders.aspx")])
        urls = X._live_urls(ctx)
        self.assertTrue(any(X._signed_in(u) for u in urls))

    def test_every_tab_is_checked(self):
        """A sign-in that lands in a new tab must still count."""
        ctx = self._Ctx([self._Page("https://ui.saraplus.com"),
                         self._Page(SESSION + "/DealerPages/SubmitOrders.aspx")])
        self.assertTrue(any(X._signed_in(u) for u in X._live_urls(ctx)))

    def test_a_closed_window_is_no_tabs(self):
        self.assertEqual(X._live_urls(self._Ctx([])), [])

    def test_the_loop_no_longer_sleeps_blind(self):
        import inspect
        src = inspect.getsource(X._window)
        self.assertIn("wait_for_timeout", src)
        self.assertIn("_live_urls", src)


class StandingBackSendsNothingTest(unittest.TestCase):
    """While a sign-in window is open the sweep must send NOTHING.

    It used to return an empty read, which cmd_once relayed as the day's real
    totals. Khalil's relay said 0 credit checks and 0 sales on 9/17, 9/18 and
    9/19 while his NDS order log had 23, 24 and 29 orders -- and it read as a
    broken SaraPlus read for two days, when he had never got in once.
    """

    def test_read_day_raises_instead_of_returning_an_empty_day(self):
        from unittest import mock
        with mock.patch.object(R, "signin_in_progress", return_value=True):
            with self.assertRaises(R.SignInInProgress):
                R.read_day(log=lambda *_: None)

    def test_cmd_once_sends_nothing_and_reports_nothing(self):
        import datetime as dt
        from unittest import mock
        from automations.icd_alerts import run as RUN
        att = {"office_key": "khalil-nds", "campaign": "nds"}
        with mock.patch.object(RUN.sara_read, "read_day",
                               side_effect=R.SignInInProgress("open")), \
             mock.patch.object(RUN.R, "send") as sent, \
             mock.patch.object(RUN, "_report") as reported, \
             mock.patch.object(RUN.C, "uses_saraplus", return_value=True), \
             mock.patch.object(RUN.C, "enrollments", return_value=[att]), \
             mock.patch("automations.icd_alerts.selfupdate.run") as upd:
            try:
                # DRY, and the update patched out: a non-dry cmd_once in a
                # checkout once pulled GitHub's copies over uncommitted work.
                rc = RUN.cmd_once(True, True, dt.date(2026, 9, 21))
            except Exception as e:  # noqa: BLE001
                self.fail("standing back raised out of cmd_once: %r" % e)
        sent.assert_not_called()
        reported.assert_not_called()
        self.assertEqual(rc, 0)


class SelfUpdateNeverOverwritesACheckoutTest(unittest.TestCase):
    """2026-09-21: a test ran a sweep in Megan's repo and the self-update
    copied GitHub's versions over the 29 agent files, silently reverting a fix
    that had not been committed yet. Installs are plain folders; a .git means
    it is somebody's working copy."""

    def test_a_git_checkout_is_skipped(self):
        import pathlib, tempfile
        from unittest import mock
        from automations.icd_alerts import selfupdate as SU
        root = pathlib.Path(tempfile.mkdtemp())
        (root / ".git").mkdir()
        said = []
        with mock.patch.object(SU, "due", return_value=True), \
             mock.patch.object(SU, "_app_root", return_value=root), \
             mock.patch.object(SU, "published_release",
                               side_effect=AssertionError("must not fetch")):
            self.assertFalse(SU.run(log=said.append))
        self.assertTrue(any("git checkout" in m for m in said))

    def test_this_repo_is_protected(self):
        from automations.icd_alerts import selfupdate as SU
        self.assertTrue((SU._app_root() / ".git").exists())

"""A sign-in window should open itself, but only onto a screen someone is at.

Megan, 2026-09-17: "We should make it where once someone is at the mac if we
need the PW it's auto popping up immediately on the screen for them."

The cost of the old shape, measured: Ryan 3.5 hours dark on 2026-09-16
(90 failed sweeps), Carlos over 5 (69), Khalil 115 on 2026-09-17. Every one of
those machines knew within two minutes. The delay was a person finding a DM,
opening a link, pressing Copy and pasting into Terminal.

The two ways this could make things WORSE, both guarded here:

  A WINDOW ON AN EMPTY DESK holds the Chrome profile the sweep needs, turning
  a recoverable outage into a guaranteed one. So "nobody is there" and "we
  cannot tell" both mean do nothing.

  A WINDOW EVERY TWO MINUTES is how somebody force-quits the thing trying to
  help them. Hence the cooldown.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import autoprompt as A
from automations.icd_alerts import presence as PR


class OnlyWhenSomebodyIsThereTest(unittest.TestCase):
    def test_nobody_at_the_screen_opens_nothing(self):
        with mock.patch.object(PR, "somebody_is_there", return_value=False):
            with mock.patch("subprocess.Popen") as popen:
                self.assertFalse(A.offer("servicecloud", log=lambda *_: None))
                popen.assert_not_called()

    def test_a_locked_mac_is_an_empty_desk(self):
        with mock.patch.object(PR, "console_user", return_value="ryan"), \
             mock.patch.object(PR, "screen_locked", return_value=True):
            self.assertFalse(PR.somebody_is_there())

    def test_unknown_counts_as_locked(self):
        """The cost of guessing wrong one way is a held profile; the other way
        it is one extra DM."""
        with mock.patch("subprocess.run", side_effect=OSError("no ioreg")):
            self.assertTrue(PR.screen_locked())

    def test_the_login_window_is_not_a_person(self):
        for who in ("root", "loginwindow", "_windowserver", ""):
            with mock.patch("subprocess.run") as run:
                run.return_value = mock.Mock(stdout=who)
                self.assertEqual(PR.console_user(), "")


class NotEveryTwoMinutesTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(self._clear)
        self._clear()

    def _clear(self):
        for sysname in A.SYSTEMS:
            try:
                A._stamp_path(sysname).unlink()
            except OSError:
                pass

    def test_a_fresh_offer_blocks_the_next_one(self):
        A._remember("servicecloud")
        self.assertTrue(A.recently_offered("servicecloud"))

    def test_the_cooldown_expires(self):
        old = dt.datetime.now() - dt.timedelta(minutes=A.COOLDOWN_MINUTES + 1)
        p = A._stamp_path("servicecloud")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(old.isoformat())
        self.assertFalse(A.recently_offered("servicecloud"))

    def test_an_unreadable_stamp_does_not_block_forever(self):
        p = A._stamp_path("servicecloud")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not a date")
        self.assertFalse(A.recently_offered("servicecloud"))

    def test_the_two_systems_have_separate_cooldowns(self):
        """An office can sell both; one dropping must not mute the other."""
        A._remember("servicecloud")
        self.assertTrue(A.recently_offered("servicecloud"))
        self.assertFalse(A.recently_offered("saraplus"))


class LandsOnTheRightScreenTest(unittest.TestCase):
    def test_root_wraps_the_launch_in_the_users_session(self):
        """The boot job is a LaunchDaemon with no GUI session -- unwrapped, the
        browser it starts is invisible and holds the profile anyway."""
        with mock.patch("os.geteuid", return_value=0), \
             mock.patch.object(PR, "user_id", return_value="501"):
            got = PR.in_user_session(["/py", "-m", "x"])
        self.assertEqual(got[:3], ["launchctl", "asuser", "501"])

    def test_a_normal_user_is_not_wrapped(self):
        with mock.patch("os.geteuid", return_value=501):
            self.assertEqual(PR.in_user_session(["/py"]), ["/py"])

    def test_an_unknown_system_does_nothing(self):
        self.assertFalse(A.offer("nonsense", log=lambda *_: None))


if __name__ == "__main__":
    unittest.main()

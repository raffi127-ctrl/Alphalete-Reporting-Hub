"""The stay-awake safeguards, and the lie they nearly told.

A machine that sleeps takes its office's channel with it, so "is this machine
staying awake?" is the single most useful thing an agent reports. Which makes
a WRONG yes worse than no answer at all: it retires the question.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_alerts import stay_awake as A


# Real `pmset -g assertions` output from a Mac with its screen on and no
# caffeinate anywhere. The summary block says PreventUserIdleSystemSleep 1.
POWERD_ONLY = """2026-09-15 11:27:21 -0500
Assertion status system-wide:
   BackgroundTask                 0
   UserIsActive                   1
   PreventUserIdleDisplaySleep    0
   PreventSystemSleep             0
   PreventUserIdleSystemSleep     1
Listed by owning process:
   pid 568(powerd): [0x0012] 02:27:13 PreventUserIdleSystemSleep named: \
"Powerd - Prevent sleep while display is on"
No kernel assertions.
"""

OURS = """Assertion status system-wide:
   PreventUserIdleSystemSleep     1
Listed by owning process:
   pid 9102(caffeinate): [0x0031] 04:10:00 PreventUserIdleSystemSleep named: \
"caffeinate command-line tool"
No kernel assertions.
"""


def _assertions(text):
    proc = mock.MagicMock()
    proc.stdout = text.encode()
    proc.returncode = 0
    return mock.patch.object(A, "_run", return_value=proc)


class ADisplayBeingOnIsNotASafeguard(unittest.TestCase):
    """powerd holds PreventUserIdleSystemSleep whenever the screen is lit.

    Reading the system-wide summary reported every Mac with somebody sitting
    at it as permanently awake -- and dropped to asleep the moment the display
    timed out, which is exactly the hour nobody is watching. Found on Megan's
    own Mac, where the summary said 1 and the owner was powerd.
    """

    def test_powerd_alone_does_not_count(self):
        with mock.patch.object(A.platform, "system", return_value="Darwin"), \
                _assertions(POWERD_ONLY):
            self.assertFalse(A.caffeinate_running(),
                             "a lit screen is being read as a safeguard")

    def test_our_own_caffeinate_does(self):
        with mock.patch.object(A.platform, "system", return_value="Darwin"), \
                _assertions(OURS):
            self.assertTrue(A.caffeinate_running())


class TheSettingIsReadFromTheMachine(unittest.TestCase):

    CUSTOM = """AC Power:
 sleep                0
 displaysleep         0
 disksleep            0
"""
    SLEEPY = """AC Power:
 sleep                1
 displaysleep         10
 disksleep            10
"""

    def _vals(self, text):
        proc = mock.MagicMock()
        proc.stdout = text.encode()
        with mock.patch.object(A.platform, "system", return_value="Darwin"), \
                mock.patch.object(A, "_run", return_value=proc):
            return A.pmset_values(), A.pmset_ok()

    def test_a_machine_set_to_never_sleep_reads_as_ok(self):
        vals, ok = self._vals(self.CUSTOM)
        self.assertEqual(vals["sleep"], "0")
        self.assertTrue(ok)

    def test_a_sleepy_machine_does_not(self):
        _, ok = self._vals(self.SLEEPY)
        self.assertFalse(ok)

    def test_an_unreadable_pmset_is_not_a_pass(self):
        with mock.patch.object(A.platform, "system", return_value="Darwin"), \
                mock.patch.object(A, "_run", side_effect=OSError("no pmset")):
            self.assertFalse(A.pmset_ok())


class EitherLayerIsEnoughButNeitherIsAssumed(unittest.TestCase):

    def _status(self, holder, setting):
        with mock.patch.object(A.platform, "system", return_value="Darwin"), \
                mock.patch.object(A, "caffeinate_running", return_value=holder), \
                mock.patch.object(A, "pmset_ok", return_value=setting), \
                mock.patch.object(A, "autologin_on", return_value=False):
            return A.status()

    def test_caffeinate_alone_counts(self):
        self.assertTrue(self._status(True, False)["never_sleeps"])

    def test_the_system_setting_alone_counts(self):
        self.assertTrue(self._status(False, True)["never_sleeps"])

    def test_neither_is_reported_honestly(self):
        st = self._status(False, False)
        self.assertFalse(st["never_sleeps"])

    def test_declining_the_password_does_not_fail_the_install(self):
        # apply() must return a status, not raise, when pmset is refused.
        with mock.patch.object(A.platform, "system", return_value="Darwin"), \
                mock.patch.object(A, "install_caffeinate", return_value=True), \
                mock.patch.object(A, "apply_pmset", return_value=False), \
                mock.patch.object(A, "caffeinate_running", return_value=True), \
                mock.patch.object(A, "pmset_ok", return_value=False), \
                mock.patch.object(A, "autologin_on", return_value=False):
            st = A.apply(log=lambda *_: None)
        self.assertTrue(st["never_sleeps"])
        self.assertFalse(st["setting"])


class AnOldAgentHasNotAnswered(unittest.TestCase):
    """None is not False -- the same rule the laptop check learned.

    Every office installed before this existed would otherwise relay
    never_sleeps=False and read as a machine that sleeps, burying the ones
    that really do.
    """

    def test_relay_reports_none_when_it_cannot_ask(self):
        from automations.icd_alerts import relay
        # An agent too old to have this file, a machine with no pmset, a probe
        # that times out: all of them arrive here as the call raising.
        with mock.patch.object(A, "status", side_effect=OSError("no pmset")):
            self.assertIsNone(relay._never_sleeps())

    def test_relay_reports_a_real_answer_when_it_can(self):
        from automations.icd_alerts import relay
        with mock.patch.object(A, "status",
                               return_value={"never_sleeps": True}):
            self.assertTrue(relay._never_sleeps())


class TheLaptopWeAllowIsJudgedOnBattery(unittest.TestCase):
    """`pmset -g custom` prints AC then battery. The battery block is what
    decides whether the one allowed laptop goes quiet when unplugged, so the
    last value has to win rather than the first."""

    BOTH = """Battery Power:
 sleep                15
 displaysleep         2
 disksleep            10
AC Power:
 sleep                0
 displaysleep         0
 disksleep            0
"""

    def test_the_last_block_wins(self):
        proc = mock.MagicMock()
        # AC first, battery last -- the pessimistic half must be what we keep.
        proc.stdout = ("AC Power:\n sleep 0\n displaysleep 0\n disksleep 0\n"
                       "Battery Power:\n sleep 15\n displaysleep 2\n"
                       " disksleep 10\n").encode()
        with mock.patch.object(A.platform, "system", return_value="Darwin"), \
                mock.patch.object(A, "_run", return_value=proc):
            self.assertEqual(A.pmset_values()["sleep"], "15")
            self.assertFalse(A.pmset_ok())


if __name__ == "__main__":
    unittest.main()

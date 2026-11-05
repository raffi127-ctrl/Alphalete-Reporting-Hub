"""captainship_send_owner full=yes rebuilds the whole report, still only to to=.

WHY (Eve 2026-11-05). Colten's and Jairo's 11/4 reports went out with weekly
delta totals that left Wednesday out. The corrected-copy action only knew how
to resend the knock boards (--skip-sheets --skip-tableau), which drops the very
Sales Board tables that needed the fix. full=yes keeps them.

    python -m unittest automations.day_orchestrator.test_mini_control_send_owner_full

Nothing runs for real: _run_cmd is mocked, so no build, no mail.
"""
import unittest
from unittest import mock

from automations.day_orchestrator import mini_control as mc


class SendOwnerFull(unittest.TestCase):

    def _cmd(self, args):
        with mock.patch.object(mc, "_run_cmd", return_value=(True, "ok")) as run:
            ok, _ = mc._action_captainship_send_owner(args)
        self.assertTrue(ok)
        return run.call_args[0][0]

    def test_default_stays_knocks_only(self):
        cmd = self._cmd("colten to=a@b.com")
        self.assertIn("--skip-sheets", cmd)
        self.assertIn("--skip-tableau", cmd)
        self.assertIn("knock boards", cmd[cmd.index("--note") + 1])
        # Owners filter on the subject: it never changes unless asked.
        self.assertNotIn("--subject-prefix", cmd)

    def test_full_keeps_sheets_and_tableau(self):
        cmd = self._cmd("colten to=a@b.com,c@d.com full=yes date=2026-11-05")
        self.assertNotIn("--skip-sheets", cmd)
        self.assertNotIn("--skip-tableau", cmd)
        self.assertIn("--no-wait", cmd)
        self.assertEqual(cmd[cmd.index("--to") + 1], "a@b.com,c@d.com")
        self.assertEqual(cmd[cmd.index("--date") + 1], "2026-11-05")
        self.assertNotIn("knock boards", cmd[cmd.index("--note") + 1])
        self.assertNotIn("--subject-prefix", cmd)
        self.assertTrue(cmd[cmd.index("--note") + 1].startswith("Updated"))

    def test_prefix_only_when_asked(self):
        cmd = self._cmd("colten to=a@b.com prefix=Sample")
        self.assertEqual(cmd[cmd.index("--subject-prefix") + 1], "Sample")

    def test_full_still_needs_to(self):
        ok, msg = mc._action_captainship_send_owner("colten full=yes")
        self.assertFalse(ok)
        self.assertIn("to=", msg)

    def test_full_rejects_other_values(self):
        ok, msg = mc._action_captainship_send_owner("colten to=a@b.com full=maybe")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

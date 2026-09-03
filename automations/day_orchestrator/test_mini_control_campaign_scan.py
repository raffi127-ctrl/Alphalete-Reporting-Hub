"""Arg-parsing tests for `lucy campaign_scan`.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_mini_control_campaign_scan

What these guard. The action builds a command line for
`automations.disposition_signup.campaign_scan`, and two of the flags it decides
are ones a wrong answer hides rather than announces:

  --after-hours   ON unless the caller typed `force`. The full ~90-office scan
                  holds the machine-wide ownerville session for 30-45 minutes;
                  inside the selling window that eats Raf's boards, and a
                  starved gap_alerts tick exits 0 looking healthy. If this flag
                  ever silently stopped being the default, nothing would fail
                  loudly.
  --only          The office filter is a SUBSTRING match. An unquoted
                  `campaign_scan Jay Turnage` first shipped as `--only Turnage`
                  because the last bare word overwrote the first — a surname
                  substring returns a plausible-looking answer for possibly the
                  wrong office, which is exactly the kind of result nobody
                  re-checks. Bare words are joined, not overwritten.

No scan runs here: `_run_cmd` is swapped for a recorder, so nothing touches
ownerville, the browser profile, or output/.
"""
from __future__ import annotations

import unittest

from automations.day_orchestrator import mini_control


class CampaignScanArgsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._real_run_cmd = mini_control._run_cmd
        self._real_guard = None

        def fake_run_cmd(cmd, timeout_s=None, log_name=None, env=None):
            self.calls.append({"cmd": cmd, "timeout_s": timeout_s,
                               "log_name": log_name, "env": env})
            return True, "exit 0"

        mini_control._run_cmd = fake_run_cmd
        # The chrome guard shells out; it is not what these tests are about.
        try:
            from automations.day_orchestrator import chrome_guard
            self._real_guard = chrome_guard.close_stray_chrome
            chrome_guard.close_stray_chrome = lambda *a, **k: None
        except Exception:  # noqa: BLE001 — guard absence must not fail the test
            pass

    def tearDown(self):
        mini_control._run_cmd = self._real_run_cmd
        if self._real_guard is not None:
            from automations.day_orchestrator import chrome_guard
            chrome_guard.close_stray_chrome = self._real_guard

    def _cmd(self, args=""):
        ok, res = mini_control._action_campaign_scan(args)
        self.assertTrue(ok, res)
        return self.calls[-1]["cmd"]

    def test_it_runs_the_campaign_scan_module(self):
        self.assertIn("automations.disposition_signup.campaign_scan",
                      self._cmd(""))

    def test_after_hours_is_the_default(self):
        self.assertIn("--after-hours", self._cmd(""))

    def test_force_drops_after_hours(self):
        self.assertNotIn("--after-hours", self._cmd("force"))

    def test_bare_name_becomes_only(self):
        cmd = self._cmd('"Jay Turnage"')
        self.assertIn("--only", cmd)
        self.assertEqual(cmd[cmd.index("--only") + 1], "Jay Turnage")

    def test_an_unquoted_two_word_name_is_not_truncated_to_the_surname(self):
        """The regression this file exists for."""
        cmd = self._cmd("Jay Turnage")
        self.assertEqual(cmd[cmd.index("--only") + 1], "Jay Turnage")

    def test_only_keyword_form(self):
        cmd = self._cmd('only="Carlos Hidalgo"')
        self.assertEqual(cmd[cmd.index("--only") + 1], "Carlos Hidalgo")

    def test_a_name_and_force_together(self):
        cmd = self._cmd('"Jay Turnage" force')
        self.assertNotIn("--after-hours", cmd)
        self.assertEqual(cmd[cmd.index("--only") + 1], "Jay Turnage")

    def test_limit_is_passed_through(self):
        cmd = self._cmd("limit=5")
        self.assertEqual(cmd[cmd.index("--limit") + 1], "5")

    def test_a_non_numeric_limit_is_refused_without_running(self):
        ok, res = mini_control._action_campaign_scan("limit=abc")
        self.assertFalse(ok)
        self.assertIn("must be a number", res)
        self.assertEqual(self.calls, [])

    def test_no_args_scans_everything(self):
        cmd = self._cmd("")
        self.assertNotIn("--only", cmd)
        self.assertNotIn("--limit", cmd)

    def test_timeout_outlasts_a_full_scan(self):
        """The full run is 30-45 min; a 15-min cap would kill it mid-sweep."""
        mini_control._action_campaign_scan("")
        self.assertGreaterEqual(self.calls[-1]["timeout_s"], 60 * 60)


class CampaignScanRegistrationTest(unittest.TestCase):
    def test_it_is_registered(self):
        self.assertIn("campaign_scan", mini_control.ACTIONS)

    def test_it_runs_in_the_main_lane_not_the_read_lane(self):
        """The read lane promises it never touches the shared browser profile.
        This scan takes the machine-wide ownerville session, so it belongs in
        main alongside probe_knocks — never beside a running report."""
        self.assertNotIn("campaign_scan", mini_control.READONLY_ACTIONS)
        self.assertTrue(
            mini_control._lane_owns("campaign_scan", mini_control.LANE_MAIN))
        self.assertFalse(
            mini_control._lane_owns("campaign_scan", mini_control.LANE_READ))

    def test_it_carries_no_secret(self):
        self.assertNotIn("campaign_scan", mini_control.SECRET_ACTIONS)


if __name__ == "__main__":
    unittest.main()

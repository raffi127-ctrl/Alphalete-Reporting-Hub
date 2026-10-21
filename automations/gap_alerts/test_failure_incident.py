"""The failure alarm is an incident: it can be marked, and it closes itself. Run:

    python -m unittest automations.gap_alerts.test_failure_incident

WHY (2026-10-21). The 10/20 "Rep Gap Alerts has failed 17 ticks in a row" post
was a hand-rolled chat_postMessage with no incident key, so `--working
gap_alerts` found nothing to mark and nothing ever put a ✅ on it after the
room was getting cards again. Everything Slack-facing is mocked: nothing posts.
"""
from __future__ import annotations  # Lucy machines run Python 3.9

import unittest
from unittest import mock

from . import run as ga


class FailureIncidentTest(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.patches = [
            mock.patch.object(ga, "_fails", side_effect=lambda: dict(self.state)),
            mock.patch.object(ga, "_write_fails",
                              side_effect=lambda d: self.state.update(d) or None),
            mock.patch.object(ga, "_log"),
        ]
        for p in self.patches:
            p.start()
        from automations.shared import incident_thread as inc
        self.open_ = mock.patch.object(inc, "open_or_followup",
                                       return_value={"ts": "1.2", "new": True}).start()
        self.close_ = mock.patch.object(inc, "resolve_if_open",
                                        return_value=True).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_streak_opens_an_incident_under_the_report_key(self):
        self.state["streak"] = ga.FAIL_STREAK - 1
        ga._record_failure("ownerville session expired", dry_run=False)
        self.open_.assert_called_once()
        kw = self.open_.call_args.kwargs
        self.assertEqual(kw["key"], "standalone-gap_alerts")
        self.assertEqual(kw["channel"], ga.CORRECTIONS_CHANNEL)
        self.assertIn("failed %d ticks in a row" % ga.FAIL_STREAK, kw["title"])

    def test_below_the_streak_posts_nothing(self):
        ga._record_failure("one blip", dry_run=False)
        self.open_.assert_not_called()

    def test_dry_run_posts_nothing(self):
        self.state["streak"] = ga.FAIL_STREAK + 5
        ga._record_failure("boom", dry_run=True)
        self.open_.assert_not_called()

    def test_clean_tick_closes_it(self):
        self.state["streak"] = 17
        ga._clear_failures()
        self.close_.assert_called_once()
        self.assertEqual(self.close_.call_args.args[0], "standalone-gap_alerts")
        self.assertFalse(self.close_.call_args.kwargs["dry_run"])
        self.assertEqual(self.state["streak"], 0)

    def test_clean_dry_run_does_not_close_for_real(self):
        ga._clear_failures(dry_run=True)
        self.assertTrue(self.close_.call_args.kwargs["dry_run"])


if __name__ == "__main__":
    unittest.main()

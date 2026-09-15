"""The two-week zero rule's card is a HAND-RUN handle — it must be exempt from
the "didn't run today" guess.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.machine_digest.test_zero_streak_handle_not_watched

WHAT THIS GUARDS (2026-09-15). #claudecorrections-and-requests got "*Two-week
zero rule — quien sale del board* — didn't run today on the mini · usually
starts ~8:00" at 12:02 on Tue 9/15, then the "needs one of you" escalation.
Nothing was broken: since 2026-09-01 the rule runs INSIDE each board's Tuesday
rollover (`zero_streak.after_rollover`), and the card went `on_scheduler:false`
so nothing on a clock fires `org_board_zero_streak` any more. Its only Activity
rows were hand reruns on Tuesdays — enough for `_historical_expected` to invent
a "Tuesday ~8:00" schedule.

Same cure and same trap as test_override_gate_not_watched: `hand_run_only` is
honoured ONLY while `cadence.weekdays` is empty, and this entry still carried
the retired `weekdays: [1]`.

Exempts the DIDN'T-RUN guess only: a hand-run that FAILS still alerts.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.day_orchestrator import registry
from automations.machine_digest import run as md

HANDLE = "org_board_zero_streak"
# The Tuesday the false alarm went out.
A_TUESDAY = dt.date(2026, 9, 15)


class TheRealScheduleConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cfg = registry.load_config()
        cls.raw = cls.cfg.raw.get("reports", {}).get(HANDLE, {})

    def test_the_handle_is_declared_hand_run_only(self):
        self.assertTrue(self.raw.get("hand_run_only"),
                        "%s lost its hand_run_only declaration" % HANDLE)

    def test_its_weekdays_are_empty_or_the_flag_does_nothing(self):
        self.assertEqual([], (self.raw.get("cadence") or {}).get("weekdays"),
                         "cadence.weekdays must stay [] or hand_run_only is ignored")

    def test_a_hand_rerun_still_resolves(self):
        self.assertIsNotNone(registry.resolve_report(self.cfg, HANDLE))

    def test_exempt_from_the_didnt_run_guess_but_still_watched_for_failures(self):
        skip = (md._orchestrator_ids(self.cfg, A_TUESDAY)
                | md._oneshot_utility_ids(self.cfg)
                | md._retired_ids() | md._not_armed_ids(self.cfg))
        offday = (md._offday_standalone_ids(self.cfg, A_TUESDAY)
                  | md._handrun_only_ids(self.cfg)
                  | md._event_logged_ids(self.cfg))
        self.assertIn(HANDLE, offday)      # no more "didn't run today"
        self.assertNotIn(HANDLE, skip)     # a failed hand-run still pages


if __name__ == "__main__":
    unittest.main()

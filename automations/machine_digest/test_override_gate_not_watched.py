"""The Override Bulletin's review-gate HANDLE must be exempt from the
"didn't run today" guess — it is a manual lever, not a schedule.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.machine_digest.test_override_gate_not_watched

WHAT THIS GUARDS (2026-09-04). #claudecorrections-and-requests got "*Override
Bulletin — review gate (post / refresh / check)* — didn't run today on the mini
· usually starts ~10:00" at ~12:05 on Fri 9/4, and 25 minutes later the "needs
one of you, re-running will not fix it" escalation. Nothing was broken. The
scheduled Friday path (deploy/override_bulletin_send_fri.sh) had fired all ten
of its passes, built the WE 8.30.26 page, uploaded the PDF, posted the review
link at 09:10 and published `override-bulletin` success — and was sitting in its
normal Friday state, waiting for Eve's ✅.

The alert was about the OTHER id. `override_gate.py` publishes under the card id
`override_bulletin`; nothing ever writes an Activity row under
`override_bulletin_gate` on a clock. Its only rows are people hand-driving a
Friday that went wrong — Thu 8/14, Fri 8/21 (x4), Fri 8/28 (x3) — and two
same-weekday Fridays inside the 3-week window is all `_historical_expected`
needs to invent "Friday ~10:00 report". The first Friday nobody had to drive it
by hand, it paged.

The cure is the declaration `hand_run_only`, which is honoured ONLY while
`cadence.weekdays` is empty (see `_handrun_only_ids`) — so the PAIR is the
declaration, and restoring `weekdays: [4]` silently un-does it while leaving the
flag sitting there looking like it works. That is the regression this pins.

Exempts the DIDN'T-RUN guess only: a hand-run of the gate that FAILS, runs
partial or hangs still alerts, which is why this asserts `offday` and not
`skip`.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.day_orchestrator import registry
from automations.machine_digest import run as md

GATE = "override_bulletin_gate"
# The Friday the false alarm went out.
A_FRIDAY = dt.date(2026, 9, 4)


class TheRealScheduleConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cfg = registry.load_config()
        cls.raw = cls.cfg.raw.get("reports", {}).get(GATE, {})

    def test_the_gate_handle_is_declared_hand_run_only(self):
        self.assertTrue(self.raw.get("hand_run_only"),
                        "%s lost its hand_run_only declaration" % GATE)

    def test_its_weekdays_are_empty_or_the_flag_does_nothing(self):
        # _handrun_only_ids ignores the flag on anything the orchestrator could
        # fire, so a non-empty list here is the same as having no flag at all.
        self.assertEqual([], (self.raw.get("cadence") or {}).get("weekdays"),
                         "cadence.weekdays must stay [] or hand_run_only is ignored")

    def test_the_watcher_actually_exempts_it_on_a_friday(self):
        self.assertIn(GATE, md._handrun_only_ids(self.cfg))

    def test_exempt_from_the_didnt_run_guess_but_still_watched_for_failures(self):
        skip = (md._orchestrator_ids(self.cfg, A_FRIDAY)
                | md._oneshot_utility_ids(self.cfg)
                | md._retired_ids() | md._not_armed_ids(self.cfg))
        offday = (md._offday_standalone_ids(self.cfg, A_FRIDAY)
                  | md._handrun_only_ids(self.cfg)
                  | md._event_logged_ids(self.cfg))
        self.assertIn(GATE, offday)      # no more "didn't run today"
        self.assertNotIn(GATE, skip)     # a failed hand-run still pages


if __name__ == "__main__":
    unittest.main()

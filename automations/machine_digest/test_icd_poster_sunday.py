"""The ICD poster ticks all Sunday and writes no Activity row. That is not a miss.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.machine_digest.test_icd_poster_sunday

WHAT THIS GUARDS (2026-09-27). At ~11:10 on Sun 9/27 the corrections channel got
`standalone-icd-alerts-poster` — "ICD Credit-Check Alerts — didn't run today on
the mini · usually starts ~9:00" — with a paste block telling the next reader to
go check the LaunchAgent on that machine. Nothing was wrong. The agent had
ticked every minute since 08:00, exit 0, log 681 KB by 11:37, and every office
in it read "outside field hours (Sun 11:37 their time)".

WHY the watcher thought otherwise. The wrapper publishes to Hub Activity only on
a tick that actually DID something — posted a credit-check line, warned an
office had gone quiet, or failed. On Sunday none of those can happen:
`icd_alerts.offices.in_field_hours` is False on Sunday for every office and
`post.warn_quiet` returns immediately on Sunday. So Sunday writes no rows, and
`_historical_expected` — which has nothing but the Activity log to go on for an
on_scheduler:false report — read the absence as a miss. What taught it that
Sunday was a run day was the PREVIOUS Sunday, 9/20, which happened to publish
exactly two rows at 09:48. [[reference_event_logged_false_miss]]

This is the same bug as icd_start_dates on Sun 9/20, and the same fix:
`standalone_weekdays` pins the truth instead of letting the log be the schedule.

THE THREE THINGS THIS PINS:
  1. The declaration reaches the id the ACTIVITY LOG uses. The registry knew
     only `install_icd_alerts_poster_agent` — an INSTALLER, which _SKIP_RE bars
     from ever having a card, and whose slug is `install-icd-alerts-poster-
     agent`. A flag parked there fans out to nothing and silently does nothing.
     The report needed an entry of its own (`icd_alerts_poster`), the same way
     sara_down has one next to install_sara_down_agent.
  2. Mon–Sat stays WATCHED. Mon–Sat this report writes 90–280 rows a day, so
     the didn't-run guess is real coverage there — which is why this is
     `standalone_weekdays` and not `logs_on_event_only` (that flag would buy
     the Sunday quiet at the price of never noticing a dead agent at all).
  3. `offday`, not `skip` — a Sunday tick that FAILS, runs partial or hangs
     still alerts, because the wrapper does run on Sunday on purpose: the
     Sunday exit came out on 2026-09-13 so a Sunday sign-up or fault is still
     announced.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.day_orchestrator import registry as _reg
from automations.machine_digest import run as md

# The id Hub Activity rows actually carry (hub_publish._HUB_CARD maps the
# wrapper's `icd_alerts_poster` onto the card id). Pinning the hyphenated
# spelling is the point: the underscored one alone would have "passed" while
# the channel kept paging.
CARD_ID = "icd-alerts-poster"
REG_ID = "icd_alerts_poster"


class IcdPosterSundayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = _reg.load_config()

    def _offday(self, iso):
        return md._offday_standalone_ids(self.cfg, dt.date.fromisoformat(iso))

    def test_the_report_has_a_registry_entry_of_its_own(self):
        # Not the installer's. A flag on install_icd_alerts_poster_agent fans
        # out to `install-icd-alerts-poster-agent` and nothing else.
        rep = self.cfg.raw["reports"].get(REG_ID)
        self.assertIsNotNone(rep, "icd_alerts_poster lost its registry entry")
        self.assertFalse(rep["on_scheduler"], "must stay out of the 4am batch")
        self.assertEqual(rep["standalone_weekdays"], [0, 1, 2, 3, 4, 5])

    def test_sunday_is_exempt_under_the_activity_log_id(self):
        ids = self._offday("2026-09-27")          # the Sunday that paged
        self.assertIn(CARD_ID, ids)
        self.assertIn(REG_ID, ids)

    def test_every_other_day_stays_watched(self):
        # Mon 9/21 … Sat 9/26 — a dead agent on a selling day must still page.
        for iso in ("2026-09-21", "2026-09-22", "2026-09-23",
                    "2026-09-24", "2026-09-25", "2026-09-26"):
            with self.subTest(day=iso):
                self.assertNotIn(CARD_ID, self._offday(iso))

    def test_the_exemption_is_offday_only_never_skip(self):
        # `skip` would swallow a real FAILED/INCOMPLETE/STUCK on a Sunday tick.
        skip = (md._orchestrator_ids(self.cfg, dt.date(2026, 9, 27))
                | md._oneshot_utility_ids(self.cfg) | md._retired_ids()
                | md._not_armed_ids(self.cfg) | md._paused_ids())
        self.assertNotIn(CARD_ID, skip)
        self.assertNotIn(REG_ID, skip)

    def test_the_card_points_at_the_box_that_actually_runs_it(self):
        # The alert's paste block says "check its LaunchAgent on that machine";
        # the card is where a reader looks up which machine that is. It said
        # Lucy 3 for five days after the 2026-09-22 move to Lucy 1.
        from automations import hub_cards
        card = next(c for c in hub_cards.AUTOMATED_REPORTS if c["id"] == CARD_ID)
        self.assertEqual(card["run_machine"], "Lucy 1")
        self.assertEqual(card["assignees"], ["Lucy 1"])


if __name__ == "__main__":
    unittest.main()

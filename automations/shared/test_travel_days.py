"""Pins the 10/15-16 trip rule (Eve 2026-10-13).

Her words: "que se envíen solos, a no ser que presenten alguna falla masiva o
sean reportes cuya falla afecte a cómo se vea el reporte al día siguiente; si es
una falla que al otro día se ve corregida, podemos pasarla por alto".

  * daily gate, one upstream failure        -> SENDS (tomorrow's board redoes it)
  * daily gate, half or more upstream broken -> HOLDS (massive)
  * own deliverable incomplete               -> HOLDS (that IS the report)
  * weekly gate (strict=True)                -> HOLDS on any failure, as always
  * any other Thursday                       -> needs the checkmark again

Run:  python -m unittest automations.shared.test_travel_days
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.shared import weekend_release as wr
from automations.shared.test_weekend_release import BAD, GOOD, OWN, Base

THU = dt.date(2026, 10, 15)
FRI = dt.date(2026, 10, 16)
OWN_ID = "captainship_drafts_review"


class TravelDays(Base):
    def run_day(self, reports, day=THU, verify=GOOD, strict=False, alerts=()):
        self.clean(reports, day=day, verify=verify, alerts=alerts)
        return wr.auto_release([OWN_ID], day, own_ids=OWN, verify=verify,
                               strict=strict)

    def test_both_days_are_no_review_days(self):
        for d in (THU, FRI):
            self.assertTrue(wr.is_travel_day(d))
            self.assertTrue(wr.is_auto_send_day(d))

    def test_one_upstream_failure_is_overlooked_and_named(self):
        ok, why = self.run_day({
            OWN_ID: {"status": "DONE"},
            "captainship_knocks": {"status": "FAILED"},
            "captainship_board_topoff": {"status": "DONE"},
            "captainship_cancel_rate": {"status": "DONE"},
        })
        self.assertTrue(ok, why)
        self.assertIn("se pasa por alto captainship_knocks", why)

    def test_a_fired_alert_upstream_is_overlooked_too(self):
        ok, why = self.run_day({
            OWN_ID: {"status": "DONE"},
            "captainship_knocks": {"status": "DONE"},
            "captainship_board_topoff": {"status": "DONE"},
        }, alerts=["captainship_knocks"], day=FRI)
        self.assertTrue(ok, why)

    def test_upstream_that_never_arrived_is_overlooked(self):
        ok, why = self.run_day({
            OWN_ID: {"status": "DONE"},
            "captainship_knocks": {"status": "MISSED_NOT_READY"},
            "captainship_board_topoff": {"status": "DONE"},
            "captainship_cancel_rate": {"status": "DONE"},
        })
        self.assertTrue(ok, why)

    def test_massive_failure_holds(self):
        ok, why = self.run_day({
            OWN_ID: {"status": "DONE"},
            "captainship_knocks": {"status": "FAILED"},
            "captainship_board_topoff": {"status": "FAILED"},
            "captainship_cancel_rate": {"status": "DONE"},
        })
        self.assertFalse(ok)
        self.assertIn("fallo la corrida", why)

    def test_incomplete_deliverable_still_holds(self):
        ok, why = self.run_day({OWN_ID: {"status": "DONE"},
                                "captainship_knocks": {"status": "DONE"}},
                               verify=BAD)
        self.assertFalse(ok)
        self.assertIn("borradores", why)

    def test_own_leg_failure_still_holds(self):
        ok, why = self.clean({OWN_ID: {"status": "FAILED"},
                              "captainship_knocks": {"status": "DONE"}},
                             day=THU, verify=None)
        self.assertFalse(ok)

    def test_weekly_strict_gate_holds_on_one_failure(self):
        ok, why = self.run_day({
            OWN_ID: {"status": "DONE"},
            "captainship_knocks": {"status": "FAILED"},
            "captainship_board_topoff": {"status": "DONE"},
            "captainship_cancel_rate": {"status": "DONE"},
        }, strict=True)
        self.assertFalse(ok)

    def test_blocking_reports_drops_overlooked_upstream(self):
        """Captainship scopes holds per captain through blocking_reports."""
        self.clean({OWN_ID: {"status": "DONE"},
                    "captainship_knocks": {"status": "FAILED"},
                    "captainship_board_topoff": {"status": "DONE"},
                    "captainship_cancel_rate": {"status": "DONE"}}, day=THU)
        self.assertEqual(wr.blocking_reports([OWN_ID], THU, own_ids=OWN), [])
        self.assertEqual(wr.blocking_reports([OWN_ID], THU, own_ids=OWN,
                                             strict=True),
                         ["captainship_knocks"])

    def test_a_normal_weekday_is_unchanged(self):
        other = THU + dt.timedelta(days=7)
        self.assertFalse(wr.is_auto_send_day(other))
        self.clean({OWN_ID: {"status": "DONE"},
                    "captainship_knocks": {"status": "FAILED"},
                    "captainship_board_topoff": {"status": "DONE"},
                    "captainship_cancel_rate": {"status": "DONE"}}, day=other)
        self.assertEqual(wr.blocking_reports([OWN_ID], other, own_ids=OWN),
                         ["captainship_knocks"])

    def test_the_thread_names_the_trip(self):
        self.assertIn("viaje", wr.auto_who(THU))
        self.assertIn("viaje", wr.day_label(FRI))


if __name__ == "__main__":
    unittest.main()

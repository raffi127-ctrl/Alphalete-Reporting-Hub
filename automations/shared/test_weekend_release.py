"""Pins WHAT stops a weekend auto-send (Eve 2026-08-21).

Her rule, verbatim: "esos tres reportes se tienen que enviar solos, a no ser que
presenten una falla en la corrida directamente (por ej que algun reporte de los
captainship drafts no se haya completado o no se vea en el correo)".

So there are exactly three reasons to hold, and everything else must send:

  1. a REAL failure anywhere in the chain (FAILED / INCOMPLETE / a fired alert)
  2. UPSTREAM content that never arrived - a metric module short of DONE is a
     section missing from the email
  3. the DELIVERABLE itself incomplete, which each gate answers for itself
     through `verify` (captainship: the .eml previews)

And the case that made this change: MISSED_NOT_READY / PENDING on the report's
OWN leg is NOT a failure. On Sat 2026-08-15 `captainship_drafts` read
MISSED_NOT_READY with every preview built (the 07:15 post agent builds them when
the morning chain has not), and the send was held over bookkeeping while the
finished reports sat on disk.

Run:  python -m automations.shared.test_weekend_release
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.shared import weekend_release as wr

SAT = dt.date(2026, 8, 15)          # a real Saturday
MON = dt.date(2026, 8, 17)
OWN = ["captainship_drafts_review", "captainship_drafts"]


def GOOD():
    return True, "los borradores estan completos"


def BAD():
    return False, "faltan 3 de 13 borradores"


class Base(unittest.TestCase):
    def setUp(self):
        self._state = wr._state
        self._closure = wr.dependency_closure
        self._due = wr._scheduled_today

    def tearDown(self):
        wr._state = self._state
        wr.dependency_closure = self._closure
        wr._scheduled_today = self._due

    def clean(self, reports, *, alerts=(), verify=GOOD, day=SAT, due=None,
              chain=None):
        wr._state = lambda today: {"reports": reports,
                                   "failure_alerts_sent": list(alerts)}
        wr.dependency_closure = lambda ids: list(chain or reports)
        wr._scheduled_today = lambda today: set(
            due if due is not None else reports)
        return wr.day_is_clean(["captainship_drafts_review"], day,
                               own_ids=OWN, verify=verify)


class HoldsOnARealFailure(Base):
    def test_failed_upstream_holds(self):
        """Sat 2026-08-15 as it really happened: cancel_rate FAILED."""
        ok, why = self.clean({
            "captainship_cancel_rate": {"status": "FAILED"},
            "captainship_drafts": {"status": "MISSED_NOT_READY"},
            "captainship_drafts_review": {"status": "MISSED_NOT_READY"},
        })
        self.assertFalse(ok)
        self.assertIn("captainship_cancel_rate", why)

    def test_incomplete_is_a_failure_too(self):
        """exit 0 with blanks IS 'no se ve en el correo'."""
        ok, why = self.clean({
            "captainship_cancel_rate": {"status": "INCOMPLETE"},
            "captainship_drafts": {"status": "DONE"},
            "captainship_drafts_review": {"status": "DONE"},
        })
        self.assertFalse(ok)
        self.assertIn("INCOMPLETE", why)

    def test_a_fired_alert_holds(self):
        ok, why = self.clean({
            "captainship_cancel_rate": {"status": "DONE"},
            "captainship_drafts": {"status": "DONE"},
            "captainship_drafts_review": {"status": "DONE"},
        }, alerts=["captainship_cancel_rate"])
        self.assertFalse(ok)
        self.assertIn("alerta", why)


class HoldsOnMissingContent(Base):
    def test_upstream_that_never_arrived_holds(self):
        """Not a failure, but the email is missing that section."""
        ok, why = self.clean({
            "captainship_cancel_rate": {"status": "MISSED_NOT_READY"},
            "captainship_drafts": {"status": "DONE"},
            "captainship_drafts_review": {"status": "DONE"},
        })
        self.assertFalse(ok)
        self.assertIn("falta contenido", why)

    def test_upstream_due_but_unrecorded_holds(self):
        """It was on today's list and the state never mentions it."""
        ok, why = self.clean({
            "captainship_drafts": {"status": "DONE"},
            "captainship_drafts_review": {"status": "DONE"},
        }, chain=["captainship_cancel_rate", "captainship_drafts",
                 "captainship_drafts_review"],
           due=["captainship_cancel_rate"])
        self.assertFalse(ok)
        self.assertIn("captainship_cancel_rate", why)

    def test_upstream_not_due_today_does_not_dirty_the_day(self):
        """all_campaigns_board does not run daily; its absence is not dirt."""
        ok, _ = self.clean({
            "captainship_drafts": {"status": "DONE"},
            "captainship_drafts_review": {"status": "DONE"},
        }, due=[])
        self.assertTrue(ok)

    def test_skipped_upstream_is_fine(self):
        ok, _ = self.clean({
            "all_campaigns_board": {"status": "SKIPPED"},
            "captainship_drafts": {"status": "DONE"},
            "captainship_drafts_review": {"status": "DONE"},
        })
        self.assertTrue(ok)


class TheOwnLegIsJudgedByTheDeliverable(Base):
    def test_missed_on_the_own_leg_no_longer_holds(self):
        """THE FIX. Bookkeeping said 'never ran'; the previews were all there."""
        ok, why = self.clean({
            "captainship_cancel_rate": {"status": "DONE"},
            "captainship_drafts": {"status": "MISSED_NOT_READY"},
            "captainship_drafts_review": {"status": "PENDING"},
        })
        self.assertTrue(ok, why)

    def test_an_incomplete_deliverable_still_holds(self):
        ok, why = self.clean({
            "captainship_cancel_rate": {"status": "DONE"},
            "captainship_drafts": {"status": "MISSED_NOT_READY"},
            "captainship_drafts_review": {"status": "PENDING"},
        }, verify=BAD)
        self.assertFalse(ok)
        self.assertIn("borradores", why)

    def test_a_failure_on_the_own_leg_still_holds(self):
        """`verify` relaxes 'never ran', never 'ran and broke'."""
        ok, why = self.clean({
            "captainship_cancel_rate": {"status": "DONE"},
            "captainship_drafts": {"status": "FAILED"},
            "captainship_drafts_review": {"status": "PENDING"},
        })
        self.assertFalse(ok)
        self.assertIn("FAILED", why)

    def test_without_verify_the_own_leg_still_needs_done(self):
        """A gate that cannot inspect its deliverable does not get relaxed."""
        wr._state = lambda today: {
            "reports": {"captainship_drafts": {"status": "MISSED_NOT_READY"},
                        "captainship_drafts_review": {"status": "PENDING"}},
            "failure_alerts_sent": []}
        wr.dependency_closure = lambda ids: ["captainship_drafts",
                                             "captainship_drafts_review"]
        wr._scheduled_today = lambda today: set()
        ok, why = wr.day_is_clean(["captainship_drafts_review"], SAT,
                                  own_ids=OWN)
        self.assertFalse(ok)
        self.assertIn("DONE", why)


class FailsClosedWithoutState(Base):
    def test_no_day_state_holds(self):
        wr._state = lambda today: None
        ok, why = wr.day_is_clean(["captainship_drafts_review"], SAT,
                                  own_ids=OWN, verify=GOOD)
        self.assertFalse(ok)
        self.assertIn("no hay estado", why)


class OnlyOnWeekends(Base):
    def test_a_weekday_never_auto_releases(self):
        wr._state = lambda today: {"reports": {}, "failure_alerts_sent": []}
        ok, why = wr.auto_release(["captainship_drafts_review"], MON,
                                  own_ids=OWN, verify=GOOD)
        self.assertFalse(ok)
        self.assertIn("monday", why.lower())

    def test_no_auto_flag_wins(self):
        ok, why = wr.auto_release(["captainship_drafts_review"], SAT,
                                  enabled=False, own_ids=OWN, verify=GOOD)
        self.assertFalse(ok)
        self.assertIn("--no-auto", why)


class NamesWhatBlocksTheDay(Base):
    """`blocking_reports` = los MISMOS motivos, pero como lista de ids.

    Es lo que lee el envio parcial (Eve 2026-08-22) para preguntar a que
    destinatarios toca cada falla en vez de frenar el dia entero."""

    def ids(self, reports, *, alerts=(), day=SAT, due=None, chain=None):
        wr._state = lambda today: {"reports": reports,
                                   "failure_alerts_sent": list(alerts)}
        wr.dependency_closure = lambda i: list(chain or reports)
        wr._scheduled_today = lambda today: set(
            due if due is not None else reports)
        return wr.blocking_reports(["captainship_drafts_review"], day,
                                   own_ids=OWN)

    def test_the_real_saturday(self):
        """8/22: owners_metrics_churn INCOMPLETE, todo lo demas DONE."""
        self.assertEqual(self.ids({
            "owners_metrics_churn": {"status": "INCOMPLETE"},
            "captainship_cancel_rate": {"status": "DONE"},
            "captainship_drafts": {"status": "DONE"},
            "captainship_drafts_review": {"status": "DONE"},
        }), ["owners_metrics_churn"])

    def test_a_clean_day_blocks_nothing(self):
        self.assertEqual(self.ids({
            "owners_metrics_churn": {"status": "DONE"},
            "captainship_drafts": {"status": "DONE"},
            "captainship_drafts_review": {"status": "DONE"},
        }), [])

    def test_own_leg_is_not_a_blocker(self):
        """MISSED_NOT_READY en la pierna propia no es falla — lo dice el
        entregable (`verify`), no la contabilidad."""
        self.assertEqual(self.ids({
            "captainship_drafts": {"status": "MISSED_NOT_READY"},
            "captainship_drafts_review": {"status": "PENDING"},
        }), [])

    def test_an_id_that_falls_twice_is_listed_once(self):
        self.assertEqual(self.ids({
            "captainship_cancel_rate": {"status": "FAILED"},
            "captainship_drafts_review": {"status": "DONE"},
        }, alerts=["captainship_cancel_rate"]), ["captainship_cancel_rate"])

    def test_no_day_state_cannot_be_scoped(self):
        wr._state = lambda today: None
        self.assertIsNone(wr.blocking_reports(["captainship_drafts_review"],
                                              SAT, own_ids=OWN))


if __name__ == "__main__":
    unittest.main(verbosity=2)

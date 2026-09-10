"""Tests for the noon backstop's OUT-OF-BAND ADOPTION pre-pass
(`run._adopt_out_of_band`).

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_backstop_adoption

WHAT THESE GUARD (2026-09-10, dd_special_accumulate). Credico's bearer token had
expired, so credico_fetch failed at 4am and dd_populate sat all morning
"waiting on credico_fetch". Somebody re-ran dd_populate by hand at 09:09 and it
filled the whole week column — but `lucy rerun` never writes day_state, so the
dependency gate went on reading the 4am state.

At noon `_apply_backstop` did two things in ONE loop: it adopted dd_populate
DONE (Hub Activity had the manual run) and it retired dd_special_accumulate
MISSED_NOT_READY for "waiting on dd_populate". The adoption came too late to be
worth anything to the dependent: the four adoption cells were never filled by
the report, and #claudecorrections announced a report that "didn't run today"
naming a dependency that was, by then, done.

The fix is order, not evidence: adopt the out-of-band runs FIRST, let
`_recheck_gated` give whatever they free its last real turn, and only then
retire what is still stuck. These tests pin that the pre-pass adopts exactly
what the backstop's own branch would have adopted (same evidence, same guard
order), leaves the dependent non-terminal so it can still run, and stays a
complete no-op on an ordinary day.
"""
from __future__ import annotations

import unittest

from automations.day_orchestrator import run as R
from automations.day_orchestrator import state


class BackstopAdoptionTest(unittest.TestCase):

    def setUp(self):
        self._real_outside = R._ran_outside_the_flow
        self._real_session = R.readiness.session_status
        # The backstop asks for the ownerville session; nothing here cares.
        R.readiness.session_status = lambda stale_after: (True, 0.0, "warm")

    def tearDown(self):
        R._ran_outside_the_flow = self._real_outside
        R.readiness.session_status = self._real_session

    # ---- helpers ----

    def _day(self, rows):
        """rows: {report_id: (status, waiting_on)} — plus optional kwargs set
        directly on the ReportState by _flag()."""
        ds = state.DayState(date="2026-09-10")
        for rid, (status, waiting_on) in rows.items():
            ds.reports[rid] = state.ReportState(
                report_id=rid, status=status, waiting_on=waiting_on,
                last_reason=f"waiting on {waiting_on}" if waiting_on else "")
        return ds

    def _ran_outside(self, *report_ids):
        ids = set(report_ids)
        R._ran_outside_the_flow = lambda rid: rid in ids

    # ---- the 2026-09-10 incident, replayed ----

    def test_hand_rerun_blocker_is_adopted_before_anything_is_retired(self):
        ds = self._day({"dd_populate": (state.PENDING, "credico_fetch"),
                        "dd_special_accumulate": (state.PENDING, "dd_populate")})
        self._ran_outside("dd_populate")

        self.assertTrue(R._adopt_out_of_band(ds))
        self.assertEqual(ds.reports["dd_populate"].status, state.DONE)
        # The dependent is untouched and still NON-TERMINAL, which is the whole
        # point: the re-check that runs next can still give it its turn.
        self.assertFalse(ds.reports["dd_special_accumulate"].is_terminal())

    def test_backstop_alone_loses_the_dependent(self):
        """What used to happen — kept as the counter-example the fix exists for."""
        ds = self._day({"dd_populate": (state.PENDING, "credico_fetch"),
                        "dd_special_accumulate": (state.PENDING, "dd_populate")})
        self._ran_outside("dd_populate")

        R._apply_backstop(ds, 20)
        self.assertEqual(ds.reports["dd_populate"].status, state.DONE)
        self.assertEqual(ds.reports["dd_special_accumulate"].status,
                         state.MISSED_NOT_READY)

    def test_adopted_report_survives_the_backstop_that_follows(self):
        """Pre-pass then backstop: the adoption is not re-worded or undone."""
        ds = self._day({"dd_populate": (state.PENDING, "credico_fetch")})
        self._ran_outside("dd_populate")

        R._adopt_out_of_band(ds)
        R._apply_backstop(ds, 20)
        self.assertEqual(ds.reports["dd_populate"].status, state.DONE)
        self.assertIn("outside the 4am flow",
                      ds.reports["dd_populate"].last_reason)

    # ---- it must be a no-op on an ordinary day ----

    def test_nothing_ran_outside_the_flow_changes_nothing(self):
        ds = self._day({"a": (state.PENDING, "box"),
                        "b": (state.STILL_TRYING, "extract not refreshed")})
        self._ran_outside()

        self.assertFalse(R._adopt_out_of_band(ds))
        self.assertEqual(ds.reports["a"].status, state.PENDING)
        self.assertEqual(ds.reports["b"].status, state.STILL_TRYING)

    def test_terminal_reports_are_never_adopted(self):
        """A FAILED report is _reverify_terminal's business, and only on a clean
        manifest — a Hub row alone must not overturn a failure."""
        ds = self._day({"credico_fetch": (state.FAILED, None)})
        self._ran_outside("credico_fetch")

        self.assertFalse(R._adopt_out_of_band(ds))
        self.assertEqual(ds.reports["credico_fetch"].status, state.FAILED)

    def test_a_broken_hub_lookup_cannot_invent_a_done(self):
        def boom(rid):
            raise RuntimeError("hub unreachable")
        R._ran_outside_the_flow = boom
        ds = self._day({"a": (state.PENDING, "box")})

        with self.assertRaises(RuntimeError):
            R._adopt_out_of_band(ds)
        # …which is why the real _ran_outside_the_flow swallows everything:
        R._ran_outside_the_flow = self._real_outside
        self.assertFalse(R._adopt_out_of_band(self._day({"a": (state.PENDING, "b")})))

    # ---- the guard order must match _apply_backstop's, case for case ----

    def test_never_launched_duplicate_is_left_to_the_backstop(self):
        ds = self._day({"a": (state.PENDING, R.DUPLICATE_WAITING_ON)})
        self._ran_outside("a")

        self.assertFalse(R._adopt_out_of_band(ds))
        R._apply_backstop(ds, 20)
        self.assertEqual(ds.reports["a"].status, state.MISSED_NOT_READY)
        self.assertIn("never launched", ds.reports["a"].last_reason)

    def test_dead_ownerville_session_is_left_to_the_backstop(self):
        ds = self._day({"a": (state.STILL_TRYING, "ownerville session is stale")})
        self._ran_outside("a")

        self.assertFalse(R._adopt_out_of_band(ds))
        R._apply_backstop(ds, 20)
        self.assertEqual(ds.reports["a"].status, state.BLOCKED_SESSION)

    def test_nothing_to_do_is_left_to_the_backstop(self):
        ds = self._day({"sci_campaigns": (state.STILL_TRYING, "no email yet")})
        ds.reports["sci_campaigns"].nothing_to_do = True
        self._ran_outside("sci_campaigns")

        self.assertFalse(R._adopt_out_of_band(ds))
        R._apply_backstop(ds, 20)
        self.assertEqual(ds.reports["sci_campaigns"].status, state.SKIPPED)


if __name__ == "__main__":
    unittest.main()

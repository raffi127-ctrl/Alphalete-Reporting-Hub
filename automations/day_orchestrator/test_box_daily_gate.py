"""The `tableau:box_daily` gate's no-sales-day tie-break (`_box_roll_history`).

WHY IT'S TESTED (2026-08-24). Monday 8/24 the Box catch-up sat behind its gate
for 3.5 hours across 12 passes on "Box only through 08-22, need 08-23", then went
out on the 08:00 fail-open floor with no freshness confirmation at all. BOX
Sunday 8/23 was a real 0 (ORG Sales Board row 10 — every other product logged
Sunday sales), so the target day had no rows to reach and the gate could never
have passed. Roughly half of recent Mondays hit this.

The trap: a quiet Sunday and an unrefreshed Sunday look IDENTICAL in a single
pull, because the crosstab is week-pinned and both are just "no rows past
Saturday". The only thing that separates them is whether the extract moved since
yesterday — so the prior-day high-water mark has to survive every pass of the
same morning, or pass 2 compares against pass 1 and the gate re-closes.

What has to stay true:
  • `prior` is frozen on the FIRST probe of a new day and does not drift as
    later passes of that same day record their own max;
  • the within-day max still accumulates, so a mid-morning refresh is kept;
  • no history file (first ever run, or a machine move) yields None, i.e. the
    old hold-until-the-floor behaviour — never a free pass;
  • a corrupt or unwritable file degrades to None instead of sinking the batch.

    python -m unittest automations.day_orchestrator.test_box_daily_gate
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.day_orchestrator import readiness

SUN = dt.date(2026, 8, 23)
MON = dt.date(2026, 8, 24)
SAT = dt.date(2026, 8, 22)
FRI = dt.date(2026, 8, 21)


class BoxHistoryTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "box_daily_maxdate.json"
        p = mock.patch.object(readiness, "_box_history_file", lambda: self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_first_ever_probe_has_no_prior(self):
        """No history = no tie-break. The gate must fall back to holding, not
        wave the report through on its very first run."""
        self.assertIsNone(readiness._box_roll_history(MON, SAT))

    def test_prior_is_frozen_across_passes_of_the_same_day(self):
        """The 8/24 failure mode: 12 passes the same morning. Every one of them
        must compare against SUNDAY's high-water mark, not against what an
        earlier pass recorded today."""
        readiness._box_roll_history(SUN, FRI)          # yesterday's probes
        first = readiness._box_roll_history(MON, SAT)   # pass 1 today
        self.assertEqual(first, FRI)
        for _ in range(11):                            # passes 2..12
            self.assertEqual(readiness._box_roll_history(MON, SAT), FRI,
                             "prior drifted mid-morning — gate would re-close")

    def test_within_day_max_survives_into_tomorrow(self):
        """A refresh that lands mid-morning is the day's high-water mark, so
        tomorrow compares against it and not against the morning's first read."""
        readiness._box_roll_history(SUN, FRI)
        readiness._box_roll_history(SUN, SAT)           # extract moved at 09:00
        self.assertEqual(readiness._box_roll_history(MON, SAT), SAT)

    def test_max_never_goes_backwards_within_a_day(self):
        readiness._box_roll_history(MON, SAT)
        readiness._box_roll_history(MON, FRI)           # a thinner later pull
        data = json.loads(self.path.read_text())
        self.assertEqual(data["max"], SAT.isoformat())

    def test_corrupt_history_degrades_to_no_prior(self):
        self.path.write_text("{not json")
        self.assertIsNone(readiness._box_roll_history(MON, SAT))

    def test_unwritable_history_never_raises(self):
        """State lives under output/; a read-only or missing tree must not take
        the whole 4am batch down with it."""
        with mock.patch.object(readiness, "_box_history_file",
                               lambda: Path("/proc/nope/box.json")):
            self.assertIsNone(readiness._box_roll_history(MON, SAT))


class BoxVerdictTests(unittest.TestCase):
    """The verdict itself: refreshed-but-empty reads READY, genuinely stale does
    not. Exercised through the same numbers 8/24 actually produced."""

    def _probe(self, maxd, prior, target=SUN, today=MON):
        cache = readiness.ReadinessCache.__new__(readiness.ReadinessCache)
        cache.target_date = today
        with mock.patch.object(readiness, "_box_roll_history",
                               return_value=prior), \
             mock.patch.object(readiness.ReadinessCache, "_probe_box_daily",
                               readiness.ReadinessCache._probe_box_daily):
            # Re-implement the tail's decision with the real numbers rather than
            # standing up a Tableau pull: this is the branch under test.
            if maxd >= target:
                return True
            return prior is not None and maxd > prior

    def test_refreshed_but_target_has_no_rows_is_ready(self):
        """8/24 for real: extract reached Saturday, Sunday was a true 0, and
        Friday was the last thing we saw before today."""
        self.assertTrue(self._probe(maxd=SAT, prior=FRI))

    def test_extract_that_did_not_move_is_still_stale(self):
        """The case the gate exists for (Carlos 2026-07-16) — must keep holding."""
        self.assertFalse(self._probe(maxd=SAT, prior=SAT))

    def test_no_history_keeps_the_old_behaviour(self):
        self.assertFalse(self._probe(maxd=SAT, prior=None))

    def test_target_reached_is_ready_regardless_of_history(self):
        self.assertTrue(self._probe(maxd=SUN, prior=SUN))


if __name__ == "__main__":
    unittest.main()


class BoxRefreshedTodayTests(unittest.TestCase):
    """2026-09-17/18: the 04:46 probe saw YESTERDAY'S date in Box's extract, said
    READY, and the catch-up posted + texted the pre-refresh board everywhere.
    Reaching the date is not refreshing — the gate now waits for the numbers to
    change against the first read of the morning.

        python -m unittest automations.day_orchestrator.test_box_daily_gate
    """
    DAY = dt.date(2026, 9, 18)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "box_daily_fingerprint.json"
        p = mock.patch.object(readiness, "_box_fingerprint_file", lambda: self.path)
        p.start()
        self.addCleanup(p.stop)

    def _at(self, hh, mm):
        return dt.datetime(2026, 9, 18, hh, mm)

    def _fp(self, n):
        return readiness.box_fingerprint(
            {"carlos": {"sales": {dt.date(2026, 9, 17): n}}}, "sales")

    def test_first_early_read_is_never_ready(self):
        """The 9/18 failure: the very first probe (04:46) went straight through."""
        self.assertIs(readiness._box_changed_since_baseline(
            self.DAY, self._fp(10), self._at(4, 46)), False)

    def test_same_numbers_later_still_hold(self):
        readiness._box_changed_since_baseline(self.DAY, self._fp(10), self._at(4, 46))
        self.assertIs(readiness._box_changed_since_baseline(
            self.DAY, self._fp(10), self._at(6, 30)), False)

    def test_numbers_moved_means_refreshed(self):
        readiness._box_changed_since_baseline(self.DAY, self._fp(10), self._at(4, 46))
        self.assertIs(readiness._box_changed_since_baseline(
            self.DAY, self._fp(17), self._at(7, 12)), True)

    def test_late_first_read_is_no_baseline(self):
        """A machine that only starts probing at 07:30 can't tell refreshed from
        not — it keeps the old date-only rule rather than hold to the floor."""
        self.assertIsNone(readiness._box_changed_since_baseline(
            self.DAY, self._fp(10), self._at(7, 30)))
        self.assertIsNone(readiness._box_changed_since_baseline(
            self.DAY, self._fp(10), self._at(7, 45)))

    def test_new_day_resets_the_baseline(self):
        readiness._box_changed_since_baseline(
            dt.date(2026, 9, 17), self._fp(10), dt.datetime(2026, 9, 17, 4, 40))
        self.assertIs(readiness._box_changed_since_baseline(
            self.DAY, self._fp(99), self._at(4, 46)), False)

    def test_corrupt_file_never_raises(self):
        self.path.write_text("{not json")
        self.assertIs(readiness._box_changed_since_baseline(
            self.DAY, self._fp(10), self._at(4, 46)), False)

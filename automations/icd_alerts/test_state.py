"""Offline tests for the sweep's send/don't-send logic. No network, no browser.

These pin the two rules that decide whether an owner gets a useful alert or 30
duplicate ones: the first sweep of a day is silent, and counts only ever rise.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from automations.icd_alerts import config as C
from automations.icd_alerts import state as St

DAY = dt.date(2026, 9, 10)


class StateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = C.STATE_PATH
        self._orig_app = C.APP_DIR
        C.APP_DIR = Path(self._tmp.name)
        C.STATE_PATH = Path(self._tmp.name) / "state.json"

    def tearDown(self):
        C.STATE_PATH = self._orig_state
        C.APP_DIR = self._orig_app
        self._tmp.cleanup()

    def test_first_sweep_of_a_day_is_baseline(self):
        """An owner opening the laptop at 3pm must not get the whole morning
        announced as if it just happened."""
        data = {}
        self.assertTrue(St.is_baseline(data, DAY))
        data = St.remember(data, DAY, {"ANA GRIFFIN": 6, "IAN RODRIGUEZ": 3})
        self.assertFalse(St.is_baseline(data, DAY))

    def test_only_increases_are_reported(self):
        data = St.remember({}, DAY, {"ANA GRIFFIN": 6})
        self.assertEqual(St.deltas(data, DAY, {"ANA GRIFFIN": 6}), {})
        self.assertEqual(St.deltas(data, DAY, {"ANA GRIFFIN": 8}),
                         {"ANA GRIFFIN": 2})

    def test_a_short_grid_never_re_announces(self):
        """A half-rendered pass reads LOW. Taking it at face value would let the
        next good pass 'gain' the same credit checks again and ping twice."""
        data = St.remember({}, DAY, {"ANA GRIFFIN": 6})
        data = St.remember(data, DAY, {"ANA GRIFFIN": 2})     # bad pass
        self.assertEqual(data[DAY.isoformat()]["ANA GRIFFIN"], 6)
        self.assertEqual(St.deltas(data, DAY, {"ANA GRIFFIN": 6}), {})

    def test_a_new_rep_appearing_counts_as_a_gain(self):
        data = St.remember({}, DAY, {"ANA GRIFFIN": 6})
        self.assertEqual(St.deltas(data, DAY, {"ANA GRIFFIN": 6,
                                               "NOEMI ONTIVEROS": 3}),
                         {"NOEMI ONTIVEROS": 3})

    def test_old_days_are_pruned(self):
        data = St.remember({}, DAY - dt.timedelta(days=30), {"OLD REP": 1})
        data = St.remember(data, DAY, {"ANA GRIFFIN": 1})
        self.assertNotIn((DAY - dt.timedelta(days=30)).isoformat(), data)
        self.assertIn(DAY.isoformat(), data)

    def test_corrupt_state_file_does_not_stop_alerts(self):
        C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        C.STATE_PATH.write_text("{not json")
        self.assertEqual(St.load(), {})

    def test_roundtrip_through_disk(self):
        St.save(St.remember({}, DAY, {"ANA GRIFFIN": 6}))
        self.assertEqual(St.load()[DAY.isoformat()]["ANA GRIFFIN"], 6)


class LineTests(unittest.TestCase):
    def test_line_matches_the_live_ao_wording(self):
        from automations.icd_alerts.run import _alert_lines
        lines = _alert_lines({"ANA GRIFFIN": 1}, {"ANA GRIFFIN": 6})
        self.assertEqual(
            lines[0], ":mag: Ana Griffin just ran 1 credit check (6 today).")

    def test_plural(self):
        from automations.icd_alerts.run import _alert_lines
        lines = _alert_lines({"IAN RODRIGUEZ": 2}, {"IAN RODRIGUEZ": 3})
        self.assertEqual(
            lines[0], ":mag: Ian Rodriguez just ran 2 credit checks (3 today).")


if __name__ == "__main__":
    unittest.main()

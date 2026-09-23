"""RAISE THE CAP FOR TODAY — and only for today.

2026-09-23: Eve queued ~90 `rerun ad_photo_threads` rows (ten offices x eight
dates). The day's ordinary traffic had already spent most of the 100-run
runaway cap, so the last 19 parked with "daily cap reached — waiting for a
human or for the date to roll". A backfill somebody decided to run is not a
runaway, so the cap needs a lever — but a lever that stays pulled is just a
higher cap, and nobody ever remembers to put it back.

Hence: dated, raise-only, ceilinged, and exempt from the cap it raises.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.day_orchestrator import mini_control as M


class TheOverrideIsDated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "autorun_cap.json"
        patch = mock.patch.object(M, "_CAP_OVERRIDE_PATH", self.path)
        patch.start()
        self.addCleanup(patch.stop)

    def _write(self, day, cap):
        self.path.write_text(json.dumps({"day": day, "cap": cap}))

    def test_no_file_is_the_standing_cap(self):
        self.assertEqual(M._daily_cap(), M.DAILY_AUTORUN_CAP)

    def test_todays_override_applies(self):
        self._write(dt.date.today().isoformat(), 150)
        self.assertEqual(M._daily_cap(), 150)

    def test_yesterdays_override_does_not(self):
        """The whole difference between 'raise it for today' and 'raise it':
        tomorrow the guard is back at 100 with nobody having to remember."""
        self._write((dt.date.today() - dt.timedelta(days=1)).isoformat(), 900)
        self.assertEqual(M._daily_cap(), M.DAILY_AUTORUN_CAP)

    def test_an_unreadable_file_is_the_standing_cap_not_no_cap(self):
        """Failing open is how a loop runs all night."""
        self.path.write_text("{ not json")
        self.assertEqual(M._daily_cap(), M.DAILY_AUTORUN_CAP)

    def test_an_override_can_never_lower_the_cap(self):
        """A row that could lower it could silence the queue; the way to do
        less is to cancel rows."""
        self._write(dt.date.today().isoformat(), 5)
        self.assertEqual(M._daily_cap(), M.DAILY_AUTORUN_CAP)

    def test_it_is_ceilinged(self):
        self._write(dt.date.today().isoformat(), 10 ** 6)
        self.assertEqual(M._daily_cap(), M.MAX_AUTORUN_CAP)


class TheAction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(M, "_CAP_OVERRIDE_PATH",
                                  Path(self.tmp.name) / "autorun_cap.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_raises_todays_cap(self):
        ok, said = M._action_set_autorun_cap("150")
        self.assertTrue(ok, said)
        self.assertEqual(M._daily_cap(), 150)

    def test_it_is_exempt_from_the_cap_it_raises(self):
        """Otherwise it is a lock with the key inside: the cap is always
        already reached when you need this."""
        self.assertIn("set_autorun_cap", M.PLUMBING_ACTIONS)
        self.assertIn("set_autorun_cap", M.ACTIONS)

    def test_a_typo_is_refused_rather_than_run(self):
        for bad in ("", "abc", str(M.MAX_AUTORUN_CAP + 1)):
            ok, _ = M._action_set_autorun_cap(bad)
            self.assertFalse(ok, bad)

    def test_it_does_not_burn_the_budget_itself(self):
        rows = [{"Action": "set_autorun_cap", "Status": "done",
                 "Queued At": dt.datetime.now().astimezone().isoformat()}]
        self.assertEqual(M._autoruns_today(rows), 0)


if __name__ == "__main__":
    unittest.main()

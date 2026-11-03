"""One office computer, several offices (Raf's three, Megan 2026-11-03).
No browser, no relay: state lives in a temp dir, the stop check is faked."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import resume_push as RP

RAF = {"office_key": "raf", "push_resumes": True}
KHALIL = {"office_key": "khalil-nds", "push_resumes": True}
NOW = dt.datetime(2026, 11, 4, 10, 0)


class MultiOffice(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(RP, "STATE_PATH", d / "s.json"),
                        mock.patch.object(RP, "_past_stop",
                                          lambda now, office=None: False),
                        mock.patch.object(RP, "push_record", lambda: RAF)]
        for p in self.patches:
            p.start()
        RP._CURRENT_OFFICE = None

    def tearDown(self):
        for p in self.patches:
            p.stop()
        RP._CURRENT_OFFICE = None

    def started(self, **mins_ago):
        RP._save_state({"by_office": {
            o: {"last_start": (NOW - dt.timedelta(minutes=m)).isoformat()}
            for o, m in mins_ago.items()}})

    def test_raf_has_three_offices_and_is_live(self):
        self.assertEqual(RP.office_ids(RAF), ("11280", "23965", "24065"))
        self.assertTrue(RP.armed(RAF), "live from his own MacBook since 2026-11-03")
        self.assertEqual(RP.office_ids(KHALIL), ("11901",))

    def test_never_run_goes_first_then_longest_waiting(self):
        self.assertEqual(RP.pick_office(NOW, RAF), "11280")
        self.started(**{"11280": 2})
        self.assertEqual(RP.pick_office(NOW, RAF), "23965")
        self.started(**{"11280": 20, "23965": 30, "24065": 16})
        self.assertEqual(RP.pick_office(NOW, RAF), "23965")

    def test_nobody_due_inside_fifteen_minutes(self):
        self.started(**{"11280": 1, "23965": 5, "24065": 14})
        self.assertIsNone(RP.pick_office(NOW, RAF))

    def test_an_office_past_its_stop_is_skipped(self):
        with mock.patch.object(RP, "_past_stop",
                               lambda now, office=None: office == "11280"):
            self.assertEqual(RP.pick_office(NOW, RAF), "23965")

    def test_listed_follows_the_pick(self):
        self.assertEqual(RP._listed(RAF), ("11280", "live"))
        RP._CURRENT_OFFICE = "24065"
        self.assertEqual(RP._listed(RAF), ("24065", "live"))
        ok, _ = RP._pin_office("24065", RAF)
        self.assertTrue(ok)
        ok, why = RP._pin_office("11280", RAF)   # banner must match the pick
        self.assertFalse(ok)

    def test_stats_rows_split_per_office(self):
        self.assertEqual(RP.stats_key(RAF, "23965"), "raf-23965")
        self.assertEqual(RP.stats_key(KHALIL, "11901"), "khalil-nds")

    def test_single_office_machines_unchanged(self):
        with mock.patch.object(RP, "push_record", lambda: KHALIL):
            RP._save_state({"last_start": (NOW - dt.timedelta(minutes=5)).isoformat()})
            self.assertIsNone(RP.pick_office(NOW, KHALIL))
            RP._save_state({"last_start": (NOW - dt.timedelta(minutes=16)).isoformat()})
            self.assertEqual(RP.pick_office(NOW, KHALIL), "11901")
            self.assertEqual(RP._listed(KHALIL), ("11901", "live"))


if __name__ == "__main__":
    unittest.main()

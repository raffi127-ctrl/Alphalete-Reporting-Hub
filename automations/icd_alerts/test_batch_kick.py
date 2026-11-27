"""One-time dry test run shipped as batch_kick.json (Megan 2026-11-27)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import resume_push as RP

RAF = {"office_key": "raf", "push_resumes": True}


class TestKick(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.kick = d / "k.json"
        self.kick.write_text(json.dumps({"id": "t1", "office_key": "raf", "office": "24065"}))
        self.started = []
        self.p = [mock.patch.object(RP, "KICK_PATH", self.kick),
                  mock.patch.object(RP, "STATE_PATH", d / "s.json"),
                  mock.patch.object(RP, "LOG_PATH", d / "l.log"),
                  mock.patch.object(RP, "_lock_held", lambda *a: False),
                  mock.patch.object(RP, "push_record", lambda: RAF),
                  mock.patch.object(RP.subprocess, "Popen",
                                    lambda argv, **k: self.started.append(argv))]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_runs_once_per_id_and_is_dry(self):
        self.assertTrue(RP._maybe_test_kick(log=lambda *_: None))
        self.assertFalse(RP._maybe_test_kick(log=lambda *_: None))
        self.assertEqual(len(self.started), 1)
        self.assertIn("--test-office", self.started[0])
        self.assertNotIn("--live", self.started[0])

    def test_other_offices_ignore_it(self):
        with mock.patch.object(RP, "push_record", lambda: {"office_key": "carlos"}):
            self.assertFalse(RP._maybe_test_kick(log=lambda *_: None))
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()

"""The scheduled tick hands the knocks read to a detached child so a slow
OwnerVille read never holds the next SaraPlus read (Colten 2026-11-06)."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import run as R


class KnocksLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock = Path(self.tmp.name) / "knocks-running.json"
        self.p = mock.patch.object(R, "KNOCKS_LOCK", self.lock); self.p.start()

    def tearDown(self):
        self.p.stop(); self.tmp.cleanup()

    def test_no_lock_means_free(self):
        self.assertFalse(R._knocks_lock_live())

    def test_fresh_lock_is_live_and_stale_lock_is_not(self):
        self.lock.write_text(json.dumps({"pid": 1, "started": time.time() - 30}))
        self.assertTrue(R._knocks_lock_live())
        self.lock.write_text(json.dumps({"pid": 1, "started": time.time() - R.KNOCKS_LOCK_STALE_S - 1}))
        self.assertFalse(R._knocks_lock_live())

    def test_second_tick_does_not_start_a_second_read(self):
        self.lock.write_text(json.dumps({"pid": 1, "started": time.time()}))
        with mock.patch("subprocess.Popen") as popen:
            rc = R.knocks_in_background(True, R.dt.date(2026, 11, 6), log=lambda m: None)
        self.assertEqual(rc, 0)
        popen.assert_not_called()

    def test_tick_starts_the_child_and_writes_the_lock(self):
        fake = mock.Mock(pid=4242)
        with mock.patch("subprocess.Popen", return_value=fake) as popen, \
                mock.patch.object(R.C, "APP_DIR", Path(self.tmp.name)), \
                mock.patch.object(R.C, "app_dir", lambda: Path(self.tmp.name)):
            rc = R.knocks_in_background(True, R.dt.date(2026, 11, 6), log=lambda m: None)
        self.assertEqual(rc, 0)
        args = popen.call_args[0][0]
        self.assertIn("--knocks", args); self.assertIn("2026-11-06", args)
        self.assertEqual(json.loads(self.lock.read_text())["pid"], 4242)
        R._release_knocks_lock()
        self.assertFalse(self.lock.exists())


if __name__ == "__main__":
    unittest.main()

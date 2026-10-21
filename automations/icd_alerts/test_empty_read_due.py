"""The empty-grid evidence goes out once an hour, and again at once when the
agent's release changes (the new release may say more)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import run as R


class EmptyReadDue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stamp = Path(self.tmp.name) / "stamp.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def test_hourly_then_again_on_a_new_release(self):
        with mock.patch.object(R, "_EMPTY_READ_STAMP", self.stamp), \
                mock.patch.object(R, "_applied_release", return_value="2026.10.21.7"):
            self.assertTrue(R._empty_read_due())
            self.assertFalse(R._empty_read_due())      # same hour, same release
        with mock.patch.object(R, "_EMPTY_READ_STAMP", self.stamp), \
                mock.patch.object(R, "_applied_release", return_value="2026.10.21.8"):
            self.assertTrue(R._empty_read_due())       # new release: now
            self.assertFalse(R._empty_read_due())

    def test_old_stamp_format_still_reads(self):
        self.stamp.write_text(dt.datetime.now().isoformat(timespec="seconds"))
        with mock.patch.object(R, "_EMPTY_READ_STAMP", self.stamp), \
                mock.patch.object(R, "_applied_release", return_value="x"):
            self.assertTrue(R._empty_read_due())       # release differs from ""


if __name__ == "__main__":
    unittest.main()

"""A paused key stays on their disk but the sweep never touches it."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import config as C


class PausedKeysTest(unittest.TestCase):
    def setUp(self):
        self.path = pathlib.Path(tempfile.mkdtemp()) / "install.json"
        self.path.write_text(json.dumps([
            {"office_key": "jamis", "campaign": "b2b_att"},
            {"office_key": "jamis10", "campaign": "b2b_box"}]))
        self.p = mock.patch.object(C, "INSTALL_PATH", self.path)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_jamis_box_is_skipped_att_is_not(self):
        self.assertEqual([r["office_key"] for r in C.active_enrollments()],
                         ["jamis"])
        self.assertFalse(C.uses_servicecloud())

    def test_pausing_never_rewrites_their_install_file(self):
        C.active_enrollments()
        self.assertEqual(len(C.enrollments()), 2)

    def test_box_sweep_does_not_sign_in(self):
        from automations.icd_alerts import run as R
        with mock.patch.object(R.box_read, "read_day",
                               side_effect=AssertionError("signed in")):
            self.assertEqual(R.cmd_box(True, True, None), 0)


if __name__ == "__main__":
    unittest.main()

"""sp_order_log leaves proof of delivery only when both artifacts landed in
the control sheet from a live SaraPlus pull.

    python -m unittest automations.sp_order_log.test_manifest

Everything that touches SaraPlus, Sheets or disk is stubbed, and
write_manifest is mocked: a real clean manifest closes the report's incident
thread in Slack, and a test must never speak in the channel.
"""
import unittest
from pathlib import Path
from unittest import mock

from automations.sp_order_log import run
from automations.shared import run_manifest


class MainRecordsDelivery(unittest.TestCase):
    def _main(self, argv, pushes=(True, True), from_file=False):
        p = [
            mock.patch.object(run, "pull_csv", return_value=(b"x", None)),
            mock.patch.object(run, "track_lines", return_value=([], {})),
            mock.patch.object(run, "shape_lines", return_value=[{"a": 1}] * 3),
            mock.patch.object(run, "build_xlsx", return_value=Path("a.xlsx")),
            mock.patch.object(run, "build_overview_png", return_value=Path("a.png")),
            mock.patch.object(run, "build_revenue_png", return_value=Path("r.png")),
            mock.patch.object(run, "_push", side_effect=list(pushes)),
            mock.patch.object(run, "OUT_DIR", mock.MagicMock()),
            mock.patch.object(Path, "read_bytes", return_value=b"x"),
            mock.patch.object(run_manifest, "write_manifest"),
        ]
        ms = [x.start() for x in p]
        self.addCleanup(mock.patch.stopall)
        with mock.patch("builtins.print"):
            rc = run.main(argv)
        return rc, ms[-1]

    def test_live_pull_and_push_records(self):
        rc, wm = self._main(["--push"])
        self.assertEqual(rc, 0)
        wm.assert_called_once()
        self.assertEqual(wm.call_args.args[0], "sp_order_log")

    def test_no_push_records_nothing(self):
        rc, wm = self._main([])
        self.assertEqual(rc, 0)
        wm.assert_not_called()

    def test_lost_upload_records_nothing(self):
        rc, wm = self._main(["--push"], pushes=(True, False))
        wm.assert_not_called()

    def test_from_file_records_nothing(self):
        rc, wm = self._main(["--push", "--from-file", "x.csv"])
        wm.assert_not_called()


class Push(unittest.TestCase):
    def test_push_reports_upload_outcome(self):
        from automations.rc_contact_sync import status_probe
        with mock.patch.object(status_probe, "_upload_bytes",
                               return_value=False), \
                mock.patch.object(Path, "read_bytes", return_value=b"x"):
            self.assertFalse(run._push(Path("a"), "T"))
        with mock.patch.object(status_probe, "_upload_bytes",
                               return_value=True), \
                mock.patch.object(Path, "read_bytes", return_value=b"x"):
            self.assertTrue(run._push(Path("a"), "T"))


if __name__ == "__main__":
    unittest.main()

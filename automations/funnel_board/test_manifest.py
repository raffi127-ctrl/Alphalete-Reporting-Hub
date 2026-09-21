"""The Funnel Board leaves proof of delivery only on a real write.

    python -m unittest automations.funnel_board.test_manifest

write_manifest is mocked: a real clean manifest closes the report's incident
thread in Slack, and a test must never speak in the channel.
"""
import unittest
from unittest import mock

from automations.funnel_board import run
from automations.shared import run_manifest


class RecordDelivery(unittest.TestCase):
    def test_real_write_records_manifest(self):
        with mock.patch.object(run_manifest, "write_manifest") as wm, \
                mock.patch.object(run, "log"):
            run.record_delivery("14 office(s) refreshed", real=True)
        wm.assert_called_once()
        self.assertEqual(wm.call_args.args[0], "funnel_board")
        self.assertFalse(wm.call_args.kwargs.get("failed"))

    def test_not_real_writes_nothing(self):
        with mock.patch.object(run_manifest, "write_manifest") as wm, \
                mock.patch.object(run, "log"):
            run.record_delivery("dry run", real=False)
        wm.assert_not_called()

    def test_writer_error_never_raises(self):
        with mock.patch.object(run_manifest, "write_manifest",
                               side_effect=OSError("disk")), \
                mock.patch.object(run, "log") as lg:
            run.record_delivery("x", real=True)
        self.assertIn("couldn't write", lg.call_args.args[0])

    def test_report_id_matches_schedule_config(self):
        import json
        from pathlib import Path
        cfg = json.loads((Path(run.__file__).resolve().parents[1]
                          / "day_orchestrator" / "schedule_config.json")
                         .read_text(encoding="utf-8"))
        self.assertIn(run.REPORT_ID, cfg.get("reports", cfg))


if __name__ == "__main__":
    unittest.main()

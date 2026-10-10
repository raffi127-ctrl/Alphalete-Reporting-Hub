"""A registry row whose enrolled reports are all Box keys is NOT an AT&T metrics
office: it must not join OFFICES/ORDER, or `--all --post` posts it a blank
'B2B Metrics' thread (Ryan McSpadden, 2026-10-10)."""
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.b2b_metrics import offices as bo


class BoxOnlyOfficeTest(unittest.TestCase):
    def _reload_with(self, rows):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        p = Path(d.name) / "onboarded.json"; p.write_text(json.dumps(rows))
        with mock.patch.object(bo, "_ONBOARDED_FILE", p):
            before = set(bo.OFFICES)
            bo._merge_onboarded()
            added = set(bo.OFFICES) - before
            for k in added:
                bo.OFFICES.pop(k, None)
        return added

    def test_box_only_row_is_skipped(self):
        added = self._reload_with([{"key": "zz_box", "owner": "Z", "channel_id": "C1",
                                    "channel_name": "r", "sheet_id": "S",
                                    "enrolled_reports": ["b2b_order_log_box", "b2b_box_accepted"]}])
        self.assertNotIn("zz_box", added)

    def test_att_row_still_joins(self):
        added = self._reload_with([{"key": "zz_att", "owner": "Z", "channel_id": "C1",
                                    "channel_name": "r", "sheet_id": "S",
                                    "enrolled_reports": ["b2b_sales", "b2b_order_log_box"]}])
        self.assertIn("zz_att", added)

    def test_row_with_no_enrolment_still_joins(self):
        added = self._reload_with([{"key": "zz_plain", "owner": "Z", "channel_id": "C1",
                                    "channel_name": "r", "sheet_id": "S"}])
        self.assertIn("zz_plain", added)

    def test_ryan_is_not_in_order(self):
        self.assertNotIn("ryan", bo.ORDER)


if __name__ == "__main__":
    unittest.main()

"""per_office hands each enrolled office its OWN workbook (2026-10-09): run.py
reads TPV memory from --sheet-id and defaults to Carlos's board otherwise."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.box_order_log import per_office
from automations.b2b_metrics import offices as bo


class SheetIdTest(unittest.TestCase):
    def _rows(self, rows):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = Path(d.name) / "onboarded.json"
        p.write_text(json.dumps(rows))
        return p

    def test_box_office_carries_its_sheet(self):
        p = self._rows([{"key": "ryan", "owner": "Ryan M", "owner_office": "RYAN M [x]",
                         "channel_id": "C1", "channel_name": "room",
                         "sheet_id": "SHEET-RYAN",
                         "enrolled_reports": ["b2b_order_log_box"]}])
        with mock.patch.object(bo, "_ONBOARDED_FILE", p):
            offs = per_office.box_offices()
        self.assertEqual(offs[0]["sheet_id"], "SHEET-RYAN")
        self.assertEqual(offs[0]["owner"], "Ryan M")
        self.assertEqual(offs[0]["sections"], ["order_log", "pending"])

    def test_run_all_passes_sheet_id_only_when_present(self):
        calls = []
        offs = [{"key": "a", "owner": "A Owner", "owner_office": "A [x]", "channel_id": "C1",
                 "channel_name": "r", "sections": ["order_log", "tier_bonus", "pending"],
                 "sheet_id": "S-A"},
                {"key": "b", "owner_office": "B [y]", "channel_id": "C2",
                 "channel_name": "r2", "sections": ["order_log", "pending"],
                 "sheet_id": ""}]
        fake = mock.Mock(returncode=0)
        with mock.patch.object(per_office, "box_offices", return_value=offs), \
             mock.patch.object(per_office, "_ensure_team_export", return_value=Path("/tmp/x.csv")), \
             mock.patch.object(per_office.subprocess, "run", side_effect=lambda cmd: (calls.append(cmd), fake)[1]):
            rc = per_office.run_all(post=False, verbose=False)
        self.assertEqual(rc, 0)
        self.assertIn("--sheet-id", calls[0]); self.assertIn("S-A", calls[0])
        self.assertIn("--sheet", calls[0])
        self.assertNotIn("--sheet-id", calls[1]); self.assertNotIn("--sheet", calls[1])
        self.assertIn("--tier-owner", calls[0]); self.assertIn("A Owner", calls[0])
        self.assertNotIn("--tier-owner", calls[1])


if __name__ == "__main__":
    unittest.main()

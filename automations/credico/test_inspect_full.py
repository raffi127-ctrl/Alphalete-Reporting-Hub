"""--inspect-full dumps EVERY per-line row of the matching Commissions files,
not the 40-row peek `--inspect` takes, and skips the sheet with customer names.

    python -m unittest automations.credico.test_inspect_full
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openpyxl

from automations.credico import report as R


def _workbook(path: Path, detail_rows: int):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CommissionSummary"
    ws.append(["Commission Summary: Nov 8 - Nov 14 2026"])
    d = wb.create_sheet("CommissionDetail")
    d.append(["Commission Details"])
    d.append(["OfficeID", "OfficeName", "CommissionWeek", "CampaignID", "CampaignName", "CommissionGroup",
              "CommissionItem", "PayType", "ActionType", "TransAmt", "Detail", "AgentName", "BadgeNum", "SaleWeek"])
    for i in range(detail_rows):
        d.append([2506, "High Value Acquisitions, Inc.", "837: Nov 8 - Nov 14 2026", 40, "Verizon Wireless",
                  "Commissions", "ISOFee", "Full", "Payment", 190, "", "Ahumada Ruiz, Brandy", "ahumabr",
                  "835: Oct 25 - Oct 31 2026"])
    b = wb.create_sheet("BonusApps")
    b.append(["CustomerFirstName", "CustomerLastName"])
    b.append(["ROSEMARY", "A"])
    s = wb.create_sheet("StatusChanges")
    s.append(["AgentName", "Status"])
    s.append(["Ahumada Ruiz, Brandy", "Chargeback"])
    wb.save(path)


class InspectFullTest(unittest.TestCase):
    def test_every_detail_row_no_customer_names(self):
        td = Path(tempfile.mkdtemp())
        _workbook(td / "2026-11-14_2026-11-14-High-Value-Commissions.xlsx", 120)
        _workbook(td / "2026-11-14_2026-11-14-Phoenix-Acquisition-Commissions.xlsx", 3)
        saved_out, saved_dump = R.OUT, R._dump_to_sheet
        got = {}
        R.OUT, R._dump_to_sheet = td, lambda rows: got.setdefault("rows", rows)
        try:
            rows = R.inspect_full("High-Value", verbose=False)
        finally:
            R.OUT, R._dump_to_sheet = saved_out, saved_dump
        self.assertIs(got["rows"], rows)
        files = {r[0] for r in rows[1:]}
        self.assertEqual(files, {"2026-11-14_2026-11-14-High-Value-Commissions.xlsx"})
        detail = [r for r in rows if r[1].startswith("CommissionDetail r")
                  and r[1][len("CommissionDetail r"):].isdigit()]
        self.assertEqual(len(detail), 122)                  # banner + header + 120 lines, not 40
        self.assertIn(["2026-11-14_2026-11-14-High-Value-Commissions.xlsx", "CommissionDetail rows", "122"], rows)
        self.assertTrue(any(r[1].startswith("StatusChanges r") for r in rows))
        self.assertNotIn("ROSEMARY", repr(rows))            # BonusApps is skipped

    def test_cli_prefers_full_over_peek(self):
        import argparse
        saved_full, saved_peek = R.inspect_full, R.inspect
        calls = []
        R.inspect_full = lambda needle: calls.append(("full", needle))
        R.inspect = lambda: calls.append(("peek",))
        try:
            R.main(["--inspect", "--inspect-full", "High-Value"])
            R.main(["--inspect", "--inspect-full"])
        finally:
            R.inspect_full, R.inspect = saved_full, saved_peek
        self.assertEqual(calls, [("full", "High-Value"), ("full", "High-Value")])


if __name__ == "__main__":
    unittest.main()

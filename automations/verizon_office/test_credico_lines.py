import datetime as dt
import tempfile
import unittest
from pathlib import Path

import openpyxl

from automations.rc_contact_sync import verizon as V
from automations.verizon_office import credico_lines as L

HDR = ["OfficeID", "OfficeName", "CommissionWeek", "CampaignID", "CampaignName", "CommissionGroup",
       "CommissionItem", "PayType", "ActionType", "TransAmt", "Detail", "AgentName", "BadgeNum", "SaleWeek",
       "PaidWeek", "AppID", "ExternalID", "SignedDate", "AccountNum", "CustomerName", "AppItemNum",
       "ExternalLineID", "ProductCategory", "ProductCode", "ProductName", "UnitPrice", "Volume", "ApprDate",
       "CanDate", "ClientStatus", "ARCStatus", "StatusReason"]


def _row(item, group, amt, cweek, ext, cust, acct, line, signed, appr="", can="", cstatus="Active", rep="Chacon, Diego"):
    return [2506, "High Value Acquisitions, Inc.", cweek, 40, "Verizon Wireless", group, item, "Full", "Payment", amt, "",
            rep, "chacdi", "834: Oct 18 - Oct 24 2026", "", 1, ext, signed, acct, cust, 1, line, "Wireless Line",
            "Wireless Line - NEW", "", 190, 1, appr, can, cstatus, "Paid", ""]


def _book(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CommissionSummary"
    d = wb.create_sheet("DetailAndStatus")
    d.append(["Combined CommissionDetail and StatusChanges"])
    d.append(HDR)
    for r in rows:
        d.append(r)
    wb.save(path)


class CredicoLinesTest(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        D = dt.datetime
        _book(self.td / "2026-11-07_2026-11-07-High-Value-Commissions.xlsx", [
            _row("ISOFee", "Commissions", 190, "836: Nov 1 - Nov 7 2026", "Q971801_281403555", "JAMES C", "627689644", "9722519486-LINE", D(2026, 10, 20), appr=D(2026, 10, 22)),
            _row("Kicker Incentive", "Bonuses", 60, "836: Nov 1 - Nov 7 2026", "Q971801_281403555", "JAMES C", "627689644", "9722519486-LINE", D(2026, 10, 20)),
            _row("", "", 0, "", "Q971801_281403555", "JAMES C", "627689644", "2145550100-LINE", D(2026, 10, 20), cstatus="Submitted"),
            _row("", "", 0, "", "Q971801_441417649", "ANA R", "427689027", "4695550199-LINE", D(2026, 10, 19), can=D(2026, 10, 24), cstatus="Cancelled"),
            _row("", "", 0, "", "Q971801_000000001", "NO NUMBER", "1", "*1309-LINE", D(2026, 10, 19)),
        ])
        _book(self.td / "2026-11-14_2026-11-14-High-Value-Commissions.xlsx", [
            _row("ISOFee", "Commissions", 190, "837: Nov 8 - Nov 14 2026", "Q971801_281403555", "JAMES C", "627689644", "2145550100-LINE", D(2026, 10, 20), appr=D(2026, 11, 2), cstatus="Active"),
        ])
        _book(self.td / "2026-11-14_2026-11-14-Phoenix-Acquisition-Commissions.xlsx", [
            _row("ISOFee", "Commissions", 190, "837", "Q1_9", "OTHER OFFICE", "9", "8325550000-LINE", D(2026, 10, 20)),
        ])

    def test_rows_merged_by_order_and_number(self):
        rows = L.build(self.td, today=dt.date(2026, 11, 15), log=lambda *a: None)
        by = {(r[L._COL["Order #"]], r[L._COL["Phone"]]): r for r in rows}
        self.assertEqual(set(by), {("281403555", "9722519486"), ("281403555", "2145550100"), ("441417649", "4695550199")})
        a = by[("281403555", "9722519486")]
        self.assertEqual((a[L._COL["Customer"]], a[L._COL["Rep"]], a[L._COL["Line"]]), ("James C", "Diego Chacon", "9486"))
        self.assertEqual((a[L._COL["Paid Week"]], a[L._COL["Paid $"]], a[L._COL["Kicker $"]]), ("836: Nov 1 - Nov 7 2026", "190", "60"))
        b = by[("281403555", "2145550100")]
        self.assertEqual((b[L._COL["Client Status"]], b[L._COL["Paid Week"]]), ("Active", "837: Nov 8 - Nov 14 2026"))  # newest file wins
        self.assertEqual(by[("441417649", "4695550199")][L._COL["Cancel Date"]], "10/24/2026")
        self.assertNotIn("OTHER OFFICE", repr(rows))                 # Phoenix file never read

    def test_contacts_one_per_live_line_with_vz_tag(self):
        rows = L.build(self.td, today=dt.date(2026, 11, 15), log=lambda *a: None)
        tab = [dict(zip(L.HEADERS, r)) for r in rows]
        specs = V.contacts_for(tab)
        names = sorted((s["first"], s["last"], s["phone"]) for s in specs)
        self.assertEqual(names, [("James", "C (VZ)", "2145550100"), ("James", "C - Line 2 (VZ)", "9722519486")])
        self.assertTrue(all(s["company"] == "Verizon" for s in specs))
        self.assertIn("Rep Name: Diego Chacon", specs[0]["notes"])
        self.assertTrue(all("4695550199" != s["phone"] for s in specs))   # cancelled line: no contact


if __name__ == "__main__":
    unittest.main()

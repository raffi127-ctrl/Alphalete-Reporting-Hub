"""nds_churn math over a synthetic NDS-SN export (long-format, Carlos's
owner + a stranger's row)."""
import csv
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.nds_churn import comp
from automations.nds_churn import compute as C

TODAY = dt.date(2026, 11, 9)
HEADER = ["Owner & Office", "Rep", "Customer Name", "sp.Order Date (copy)",
          "sp.SPM Number", "spe.Account BAN", "Product Type (Broken Out)",
          "DTR Status (enriched)", "DTR Status Date",
          "Activatoin Date (order log)", "spe.Name", "spe.TN", "spe.TN Type",
          "Package", "Ported From", "Disconnect Reason (Consolidated)",
          "Measure Names", "Measure Values"]


def _row(rep, cust, od, spm, ban, prod, status, sdate, posted, spe, tn,
         tntype, pkg, ported, reason, owner="CARLOS HIDALGO\nAlphalete"):
    return [owner, rep, cust, od, spm, ban, prod, status, sdate, posted, spe,
            tn, tntype, pkg, ported, reason, "Unit Count", "1"]


ROWS = [
    _row("Nick Smedra", "HENRY W", "10/20/2026", "DSI1", "BAN1", "WIRELESS",
         "Posted", "", "10/25/2026", "SPE1", "111", "port", "iPhone 18", "Verizon", ""),
    _row("Nick Smedra", "HENRY W", "10/20/2026", "DSI1", "BAN1", "WIRELESS",
         "Disconnected", "11/3/2026", "10/25/2026", "SPE2", "222", "port",
         "BYOD Unlimited", "Verizon", "Non-Pay"),
    _row("Andrew Park", "MARIA G", "10/28/2026", "DSI2", "BAN2", "AIR",
         "Posted", "", "11/1/2026", "SPE3", "", "", "Internet Air", "", ""),
    _row("Andrew Park", "OLD O", "9/1/2026", "DSI3", "BAN3", "WIRELESS",
         "Disconnected", "9/20/2026", "9/5/2026", "SPE4", "444", "port",
         "iPhone", "T-Mobile", "Buyer's Remorse"),
    _row("Andrew Park", "PEND P", "11/5/2026", "DSI4", "BAN4", "WIRELESS",
         "Shipped", "", "", "SPE5", "555", "new", "iPhone", "", ""),
    _row("Someone Else", "NOT MINE", "11/1/2026", "DSI9", "BAN9", "WIRELESS",
         "Disconnected", "11/5/2026", "11/2/2026", "SPE9", "999", "port",
         "BYOD", "AT&T", "Non-Pay", owner="KHALIL MANSOUR\nOffice"),
]
# a second measure row for SPE1 -- must collapse away
ROWS.append(list(ROWS[0]))
ROWS[-1][16], ROWS[-1][17] = "Revenue", "213"


class Compute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = Path(tempfile.mkdtemp())
        cls.csv = d / "nds_orderlog.csv"
        with open(cls.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["noise", "line"])
            w.writerow(HEADER)
            w.writerows(ROWS)
        cls.header, cls.ix, cls.lines = C.load_owner_lines(cls.csv, log=lambda *_: None)

    def test_load_filters_owner_and_collapses_measures(self):
        self.assertEqual(len(self.lines), 5)
        self.assertEqual(self.ix["reason"], 15)
        self.assertEqual(self.header[self.ix["status"]], "DTR Status (enriched)")
        self.assertEqual(self.header[self.ix["status_date"]], "DTR Status Date")

    def test_churn_summary(self):
        s = C.churn_summary(self.lines, TODAY)
        self.assertEqual(s["base"], {"Wireless": 2, "Air": 1, "Internet": 0})
        self.assertEqual(s["disc"], {"Wireless": 1, "Air": 0, "Internet": 0})
        self.assertEqual(s["split"]["byod"], {"base": 1, "disc": 1})
        self.assertEqual(s["split"]["non_byod"], {"base": 1, "disc": 0})

    def test_helper_block_shape_and_reason(self):
        rows = C.helper_block(self.lines, TODAY)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(len(r), 16)
        self.assertEqual(r[4], "HENRY W")
        self.assertEqual(r[9], "Non-Pay")            # was CRU/IRU
        self.assertEqual(r[8], "11/3/2026")          # real disconnect date
        self.assertEqual(r[1], "11/24/2026")         # posted 10/25 + 30
        self.assertEqual(r[10], "2 (2W)")
        self.assertEqual(r[11], "BYOD")
        self.assertIsNone(r[3]); self.assertIsNone(r[13])

    def test_activation_rates(self):
        office, reps = C.activation_rates(self.lines, TODAY)
        self.assertEqual(office["0-30"]["sold"], 4)
        self.assertEqual(office["0-30"]["activated"], 3)
        self.assertEqual(office["31-60"]["sold"], 0)
        self.assertIsNone(office["31-60"]["rate"])
        self.assertEqual(reps["Nick Smedra"]["0-30"]["rate"], 1.0)

    def test_tiers_and_status(self):
        self.assertEqual(comp.tier_for(2.2, comp.NONBYOD_0_30), 4)
        self.assertEqual(comp.tier_for(2.21, comp.NONBYOD_0_30), 3)
        self.assertEqual(comp.tier_for(7.51, comp.NONBYOD_0_30), 1)
        self.assertEqual(comp.tier_for(5.5, comp.BYOD_0_30), 4)
        self.assertIsNone(comp.tier_for(None, comp.BYOD_0_30))
        self.assertEqual(comp.payout("3-3", False), (213, 193))
        self.assertEqual(comp.payout("3-3", True), (188, 168))
        self.assertEqual(comp.payout("4-4", False), (233, 213))
        ts = C.tier_status(C.churn_summary(self.lines, TODAY), TODAY)
        self.assertEqual(ts["products"]["byod"]["tier"], 1)       # 1/1 = 100%
        self.assertEqual(ts["products"]["non_byod"]["tier"], 4)   # 0/1
        line = C.status_line(ts)
        self.assertIn("Tier 3-3 ($213 OOF / $193 INFP", line)
        self.assertIn("BYOD 1/1 = 100.0% (Tier 1 band)", line)
        self.assertIn("≤19 port activations", line)

    def test_rep_dnq(self):
        self.assertIsNone(comp.rep_dnq(8.0, 10, 50.0, 10))   # under the floors
        self.assertTrue(comp.rep_dnq(7.1, 20, None, 0))
        self.assertTrue(comp.rep_dnq(None, 0, 59.9, 20))
        self.assertIsNone(comp.rep_dnq(7.0, 25, 60.0, 25))


if __name__ == "__main__":
    unittest.main()

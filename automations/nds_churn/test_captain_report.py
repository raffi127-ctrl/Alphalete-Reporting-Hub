"""captain_report math over a synthetic NDS-SN export: Zaid's owner, a
stranger's row, BYOD / Air / tablet lines that must stay out, and lines in
the 0-30 and 90 Day buckets."""
import csv
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.nds_churn import captain_report as CR
from automations.nds_churn import compute as C

TODAY = dt.date(2026, 11, 17)
HEADER = ["Owner & Office", "Rep", "Customer Name", "sp.Order Date (copy)",
          "sp.SPM Number", "spe.Account BAN", "Product Type (Broken Out)",
          "DTR Status (enriched)", "DTR Status Date",
          "Activatoin Date (order log)", "spe.Name", "spe.TN", "spe.TN Type",
          "Package", "Ported From", "Disconnect Reason (Consolidated)",
          "Measure Names", "Measure Values"]
ZAID = "ZAID ARABYAT\r [aces acquisitions, inc.]"


def _d(days_ago):
    d = TODAY - dt.timedelta(days=days_ago)
    return f"{d.month}/{d.day}/{d.year}"


def _row(rep, cust, od, spm, ban, prod, status, sdate, posted, spe, tn,
         tntype, pkg, ported="Verizon", reason="", owner=ZAID):
    return [owner, rep, cust, od, spm, ban, prod, status, sdate, posted, spe,
            tn, tntype, pkg, ported, reason, "Unit Count", "1"]


ROWS = [
    # 0-30 bucket: 3 non-BYOD port phones (1 disconnected), 1 BYOD port (disconnected)
    _row("Rep A", "CUST 1", _d(20), "DSI1", "BAN1", "WIRELESS", "Posted", "", _d(10),
         "SPE1", "111", "port", "iPhone 18 - 256GB - Black"),
    _row("Rep A", "CUST 2", _d(25), "DSI2", "BAN2", "WIRELESS", "Disconnected", _d(2), _d(15),
         "SPE2", "222", "port", "iPhone 18 - 256GB - Black", reason="Non-Pay"),
    _row("Rep B", "CUST 3", _d(22), "DSI3", "BAN3", "WIRELESS", "Posted", "", _d(12),
         "SPE3", "333", "port", "Galaxy S26 - 128GB - Blue"),
    _row("Rep B", "CUST 4", _d(22), "DSI4", "BAN4", "WIRELESS", "Disconnected", _d(3), _d(12),
         "SPE4", "444", "port", "BYOD Unlimited"),
    # 0-30: an Air line and a ported tablet -- never on the report
    _row("Rep B", "CUST 5", _d(20), "DSI5", "BAN5", "AIR", "Posted", "", _d(9),
         "SPE5", "", "", "Internet Air"),
    _row("Rep B", "CUST 6", _d(20), "DSI6", "BAN6", "WIRELESS", "Disconnected", _d(1), _d(9),
         "SPE6", "666", "port", "iPad 11 - 128GB - Blue"),
    # 90 Day bucket (posted 91-120 days ago): 4 non-BYOD ports, 1 disconnected
    _row("Rep A", "OLD 1", _d(110), "DSI7", "BAN7", "WIRELESS", "Posted", "", _d(100),
         "SPE7", "777", "port", "iPhone 17 - 128GB - White"),
    _row("Rep A", "OLD 2", _d(112), "DSI8", "BAN8", "WIRELESS", "Disconnected", _d(40), _d(105),
         "SPE8", "888", "port", "iPhone 17 - 128GB - White", reason="Non-Pay"),
    _row("Rep B", "OLD 3", _d(100), "DSI9", "BAN9", "WIRELESS", "Posted", "", _d(95),
         "SPE9", "999", "port", "Galaxy S25 - 128GB - Black"),
    _row("Rep B", "OLD 4", _d(130), "DSI10", "BAN10", "WIRELESS", "Posted", "", _d(120),
         "SPE10", "1010", "port", "Galaxy S25 - 128GB - Black"),
    # 90 Day bucket, disconnected 95 days AFTER activating: in the base, NOT a
    # 90 Day disconnect (Smart Circle's within-90-days count)
    _row("Rep B", "OLD 5", _d(110), "DSI14", "BAN14", "WIRELESS", "Disconnected", _d(5), _d(100),
         "SPE14", "1414", "port", "Galaxy S25 - 128GB - Black", reason="Non-Pay"),
    # 61-90 (the 60 Day bucket) -- counted there, not in 90
    _row("Rep B", "MID 1", _d(80), "DSI11", "BAN11", "WIRELESS", "Disconnected", _d(10), _d(70),
         "SPE11", "1111", "port", "Galaxy S25 - 128GB - Black"),
    # pending non-BYOD sale in the window
    _row("Rep A", "PEND 1", _d(5), "DSI12", "BAN12", "WIRELESS", "Shipped", "", "",
         "SPE12", "1212", "port", "iPhone 18 - 256GB - Black"),
    # a stranger's line
    _row("Someone", "NOT OURS", _d(10), "DSI13", "BAN13", "WIRELESS", "Disconnected", _d(1), _d(5),
         "SPE13", "1313", "port", "iPhone 18 - 256GB - Black", owner="KHALIL MANSOUR [x]"),
]


class CaptainReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "export.csv"
        with open(cls.path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(ROWS)
        _, _, cls.lines = C.load_owner_lines(cls.path, log=lambda *a: None,
                                             owner_tokens=CR.OWNERS["zaid"]["tokens"])
        cls.rep = CR.build(cls.lines, TODAY)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_owner_slice(self):
        self.assertEqual(len(self.lines), len(ROWS) - 1)

    def test_box_non_byod_only(self):
        b = self.rep["box"]
        self.assertEqual((b["0-30"]["act"], b["0-30"]["disc"]), (3, 1))
        self.assertEqual((b["90"]["act"], b["90"]["disc"]), (5, 1))
        self.assertEqual((b["60"]["act"], b["60"]["disc"]), (1, 1))
        self.assertAlmostEqual(b["0-30"]["pct"], 100 / 3, places=3)

    def test_all_port_includes_byod(self):
        a = self.rep["all_port"]["0-30"]
        self.assertEqual((a["act"], a["disc"]), (4, 2))

    def test_reps_and_order(self):
        reps = self.rep["reps"]
        self.assertEqual(reps["Rep A"]["0-30"]["disc"], 1)
        self.assertEqual(reps["Rep A"]["90"]["disc"], 1)
        self.assertEqual(reps["Rep B"]["0-30"]["disc"], 0)   # the BYOD + tablet stay out
        self.assertEqual(reps["Rep B"]["90"]["disc"], 0)     # OLD 5 dropped after day 90
        self.assertEqual(CR.rep_order(reps)[0], "Rep A")

    def test_rate_and_pending(self):
        r = self.rep["office_rate"]["0-30"]
        self.assertEqual((r["activated"], r["sold"]), (3, 4))   # 3 posted + 1 shipped non-BYOD
        self.assertEqual(self.rep["pending"], 1)

    def test_tables(self):
        t30 = self.rep["tables"]["0-30"]
        self.assertEqual([g["customer"] for g in t30], ["CUST 2"])
        self.assertEqual(t30[0]["leaves"], TODAY - dt.timedelta(days=15) + dt.timedelta(days=31))
        self.assertEqual(t30[0]["pct_after"], 0.0)
        t90 = self.rep["tables"]["90"]
        self.assertEqual([g["customer"] for g in t90], ["OLD 2"])   # not OLD 5
        self.assertEqual(t90[0]["days_left"], 121 - 105)

    def test_html_renders(self):
        h = CR.render_html(CR.OWNERS["zaid"], self.rep, TODAY, "✓ test")
        self.assertIn("Zaid Arabyat", h)
        self.assertIn("CUST 2", h)
        self.assertNotIn("CUST 4", h)      # BYOD
        self.assertNotIn("CUST 5", h)      # Air
        self.assertIn("OLD 2", h)

    def test_compare_against_view(self):
        view = {"0-30": {"disc": 2, "base": 4}, "90": {"disc": 1, "base": 5}}
        ok, txt = CR.compare(view, self.rep)
        self.assertTrue(ok)
        self.assertIn("view 2/4 vs ours 2/4 ✓", txt)
        self.assertIn("90 Day view 1/5 vs ours 1/5 ✓", txt)
        ok2, txt2 = CR.compare({"0-30": {"disc": 3, "base": 4}, "90": None}, self.rep)
        self.assertFalse(ok2)
        self.assertIn("view has no rows", txt2)

    def test_captain_band(self):
        self.assertEqual(CR._band("0-30", 2.9), CR.GREEN)
        self.assertEqual(CR._band("0-30", 5.0), CR.RED)
        self.assertEqual(CR._band("90", 10.0), CR.YELLOW)
        self.assertEqual(CR._band("90", 13.9), CR.RED)


if __name__ == "__main__":
    unittest.main()

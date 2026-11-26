"""Pure tests: crosstab parse, captain match, % math, sheet plan."""
import datetime as dt
import unittest

from automations.captainship_penetration import core, fill

HEAD = "\t".join(["Office Lead Penetration (Fixed)", "Account_Owner_Name__c",
                  "Account Captain Email", "ICD Workable Fiber Lead Count (copy)",
                  "Fiber Sales (Fixed) (copy)", "Customer Zip"])
ROWS = [
    ("Grand Total", "Total", "Total", "Total", "Total", "Total"),
    ("1.0%", "Rafael Hidalgo", "Raffi127@gmail.com", "300,000", "3,000", "1"),
    ("1.0%", "Rafael Hidalgo", "Raffi127@gmail.com", "300,000", "3,000", "2"),
    ("2.3%", "Kash Rai", "raffi127@gmail.com", "155,214", "3,536", "3"),
    ("0.5%", "Trang Canavan", "Raffi127@gmail.com", "100,000", "500", "4"),
    ("1.1%", "Wayne Rude", "wayne.rude@gmail.com", "10,000", "110", "5"),
    ("1.2%", "Bill Fischer", "wayne.rude@gmail.com", "10,000", "120", "6"),
    ("0.0%", "No Leads", "wayne.rude@gmail.com", "0", "0", "7"),
    ("1.0%", "Loose Owner", "", "10", "1", "8"),
]
TEXT = "\n".join([HEAD] + ["\t".join(r) for r in ROWS])


class Core(unittest.TestCase):
    def setUp(self):
        self.o = core.parse_owners(TEXT)

    def test_one_entry_per_owner_total_skipped(self):
        self.assertEqual(len(self.o), 7)
        self.assertNotIn("Total", self.o)
        self.assertEqual(self.o["Kash Rai"]["leads"], 155214)

    def test_nickname_email_found_by_own_office_case_folded(self):
        d = core.captainship("rafael", self.o)
        self.assertEqual(d["email"], "Raffi127@gmail.com")
        self.assertEqual(sorted(d["owners"]), ["Kash Rai", "Trang Canavan"])
        self.assertNotIn("Rafael Hidalgo", d["owners"])

    def test_pct_two_decimals_and_weighted_avg(self):
        d = core.captainship("rafael", self.o)
        self.assertEqual(d["owners"]["Kash Rai"], "2.28%")
        self.assertEqual(d["owners"]["Trang Canavan"], "0.50%")
        self.assertEqual(d["avg"], f"{4036 / 255214 * 100:.2f}%")

    def test_no_leads_is_blank_not_zero(self):
        d = core.captainship("wayne", self.o)
        self.assertEqual(d["owners"]["No Leads"], "")
        self.assertEqual(d["avg"], "1.20%")   # Wayne himself left out

    def test_unknown_captain_raises(self):
        with self.assertRaises(ValueError):
            core.captainship("chan", self.o)


class Sheet(unittest.TestCase):
    COL_A = ["Wayne Rude - Captainship Penetration", "PENETRATION RATE (ONGOING)",
             "Captainship Avg", "Owner", "Bill Fischer", "Gone Owner"]

    def test_find_box_by_label(self):
        b = fill.find_boxes_in(self.COL_A)["penetration"]
        self.assertEqual((b["header_row"], b["office_avg_row"],
                          b["rep_header_row"]), (2, 3, 4))
        self.assertEqual(b["rep_rows"], {"bill fischer": 5, "gone owner": 6})

    def test_plan_new_tab_today_and_new_day(self):
        b = fill.find_boxes_in(self.COL_A)["penetration"]
        owners = {"Bill Fischer": "1.20%", "New Owner": "0.90%"}
        day = dt.date(2026, 11, 27)
        empty = [[c] for c in self.COL_A]
        self.assertFalse(fill.plan(empty, b, day, owners)["insert_col"])
        same = [list(r) for r in empty]; same[1] = [self.COL_A[1], "Fri 11/27/26"]
        self.assertFalse(fill.plan(same, b, day, owners)["insert_col"])
        old = [list(r) for r in empty]; old[1] = [self.COL_A[1], "Thu 11/26/26"]
        p = fill.plan(old, b, day, owners)
        self.assertTrue(p["insert_col"])
        self.assertEqual(p["new_owners"], ["New Owner"])

    def test_owner_who_left_is_blanked(self):
        b = fill.find_boxes_in(self.COL_A)["penetration"]
        cells = fill.cells_for("T", b, dt.date(2026, 11, 27),
                               {"avg": "1.20%", "owners": {"Bill Fischer": "1.20%"}})
        by = {c["range"]: c["values"][0][0] for c in cells}
        self.assertEqual(by["'T'!B5"], "1.20%")
        self.assertEqual(by["'T'!B6"], "")
        self.assertEqual(by["'T'!B2"], "2026-11-27")


class Drafts(unittest.TestCase):
    def test_box_held_until_rollout(self):
        from automations.captainship_drafts import config
        for k in ("rafael", "wayne"):
            c = config.BY_KEY[k]
            self.assertNotIn("penetration", [b.slot for b in c.boxes_shown()])
            self.assertIn("penetration", [b.slot for b in c.boxes])


if __name__ == "__main__":
    unittest.main()

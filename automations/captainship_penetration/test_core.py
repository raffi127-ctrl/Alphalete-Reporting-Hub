"""Pure tests: crosstab parse, captain match, % math, sheet plan."""
import datetime as dt
import unittest

from automations.captainship_penetration import core, fill

HEAD = "\t".join(["Office Lead Penetration (Fixed)", "Account_Owner_Name__c",
                  "Account Captain Email", "Customer Zip", "Lead Count",
                  "Total Sales"])
ROWS = [
    ("Grand Total", "Total", "Total", "Total", "999", "9"),
    ("1.0%", "Rafael Hidalgo", "Raffi127@gmail.com", "1", "1,000", "10"),
    ("1.0%", "Rafael Hidalgo", "Raffi127@gmail.com", "2", "1,000", "10"),
    ("2.3%", "Kash Rai", "raffi127@gmail.com", "3", "1,000", "20"),
    ("2.3%", "Kash Rai", "raffi127@gmail.com", "4", "1,000", "25"),
    ("0.5%", "Trang Canavan", "Raffi127@gmail.com", "5", "2,000", "10"),
    ("1.1%", "Wayne Rude", "wayne.rude@gmail.com", "6", "100", "1"),
    ("1.2%", "Bill Fischer", "wayne.rude@gmail.com", "7", "100", "1"),
    ("", "No Pct", "wayne.rude@gmail.com", "8", "0", "0"),
    ("1.0%", "Loose Owner", "", "9", "10", "1"),
]
TEXT = "\n".join([HEAD] + ["\t".join(r) for r in ROWS])


class Core(unittest.TestCase):
    def setUp(self):
        self.o = core.parse_owners(TEXT)

    def test_one_entry_per_owner_zips_summed(self):
        self.assertEqual(len(self.o), 7)
        self.assertNotIn("Total", self.o)
        self.assertEqual(self.o["Kash Rai"]["zip_sales"], 45)
        self.assertEqual(self.o["Kash Rai"]["zip_leads"], 2000)

    def test_owner_pct_is_tableaus_own_number(self):
        d = core.captainship("rafael", self.o)
        self.assertEqual(d["owners"], {"Kash Rai": "2.3%", "Trang Canavan": "0.5%"})

    def test_nickname_email_found_by_own_office_case_folded(self):
        d = core.captainship("rafael", self.o)
        self.assertEqual(d["email"], "Raffi127@gmail.com")
        self.assertNotIn("Rafael Hidalgo", d["owners"])

    def test_avg_is_weighted_zip_total_without_captain(self):
        d = core.captainship("rafael", self.o)
        self.assertEqual(d["avg"], "1.38%")          # (45+10) / (2000+2000)

    def test_missing_pct_is_blank(self):
        d = core.captainship("wayne", self.o)
        self.assertEqual(d["owners"]["No Pct"], "")
        self.assertEqual(d["avg"], "1.00%")          # Wayne himself left out

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


class Style(unittest.TestCase):
    def test_style_uses_captain_color_and_borders(self):
        b = fill.find_boxes_in(Sheet.COL_A)["penetration"]
        reqs = fill.style_requests(7, b, 8, "#E69138")
        kinds = [next(iter(r)) for r in reqs]
        self.assertIn("mergeCells", kinds)
        self.assertIn("updateBorders", kinds)
        title = next(r for r in reqs if "repeatCell" in r)["repeatCell"]
        bg = title["cell"]["userEnteredFormat"]["backgroundColor"]
        self.assertAlmostEqual(bg["red"], 0xE6 / 255)
        border = next(r for r in reqs if "updateBorders" in r)["updateBorders"]
        self.assertEqual(border["range"]["endRowIndex"], 6)   # last owner row

    def test_every_captain_has_a_color(self):
        from automations.captainship_penetration import core
        for k in core.CAPTAIN_OWNER:
            self.assertTrue(fill.captain_color(k).startswith("#"))


class Sort(unittest.TestCase):
    def test_sorts_owner_rows_only_by_today_desc(self):
        b = fill.find_boxes_in(Sheet.COL_A)["penetration"]
        r = fill.sort_request(7, b, 9)["sortRange"]
        self.assertEqual((r["range"]["startRowIndex"], r["range"]["endRowIndex"]),
                         (4, 6))            # rows 5-6: owners, not avg/header
        self.assertEqual(r["sortSpecs"], [{"dimensionIndex": 1,
                                           "sortOrder": "DESCENDING"}])

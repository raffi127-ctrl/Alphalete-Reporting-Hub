import unittest

from automations.lumen_owners import metrics30 as M

GRID = [
    ["ICD Owner [Office] (Nest)", "Fiber Internet Sales (30-Day)",
     "Fiber Internet Activation (30-Day)", "Activation % (30-Day)",
     "Fiber Internet Cancels (30-Day)", "Cancel % (30-Day)"],
    ["NIGEL MARSHALL [VP Executives, Inc.] (Nest)", "532", "363", "68.2%", "97", "18.2%"],
    ["DAVID PANCOAST [Pancoast LLC]", "40", "20", "0.5", "4", "0.1"],
    ["Grand Total", "572", "383", "67%", "101", "18%"],
]


class Metrics30Test(unittest.TestCase):
    def test_columns_by_header_words(self):
        self.assertEqual(M.column_map(GRID[0]), {
            "sales": 1, "act": 2, "act_pct": 3, "cancels": 4, "cancel_pct": 5})

    def test_rows_by_owner_total_dropped(self):
        got = M.by_owner(GRID)
        self.assertEqual(set(got), {"nigel marshall", "david pancoast"})
        self.assertEqual(got["nigel marshall"]["cancel_pct"], "18.2%")

    def test_table_percent_both_shapes_and_dashes_for_missing(self):
        owners = [{"owner": "Nigel Marshall"}, {"owner": "David Pancoast"},
                  {"owner": "Myles Neal"}]
        s = M.table_html(owners, M.by_owner(GRID))
        self.assertIn("68%", s)
        self.assertIn("50%", s)
        self.assertIn("10%", s)
        self.assertIn("last 30 days", s)
        self.assertIn("Myles Neal</td><td", s)
        self.assertIn("&ndash;", s)

    def test_no_view_no_table(self):
        self.assertEqual(M.table_html([{"owner": "X"}], {}), "")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from automations.new_internet_churn import tiers as T


def _csv(d, name, header, rows):
    p = Path(d) / name
    lines = ["\t".join(header)] + ["\t".join(r) for r in rows]
    p.write_text("\n".join(lines), encoding="utf-16")
    return p


class ParseTest(unittest.TestCase):
    def test_finds_column_whatever_the_month_and_position(self):
        with tempfile.TemporaryDirectory() as d:
            p = _csv(d, "a.csv", ["Ranking", "ICD Owner Name", "November Churn Tier"],
                     [["1", "WAYNE RUDE", "Tier 4"], ["", "Grand Total", ""],
                      ["2", "NEW  OWNER", "n/a"]])
            self.assertEqual(T.parse_crosstab(p), ("November", {"WAYNE RUDE": "Tier 4"}))

    def test_no_tier_column_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = _csv(d, "a.csv", ["ICD Owner Name", "Rep Count"], [["A B", "3"]])
            with self.assertRaises(RuntimeError):
                T.parse_crosstab(p)


class MergeTest(unittest.TestCase):
    def test_this_week_wins_and_last_week_fills_gaps(self):
        m, t = T.merge_pulls([("November", {"A": "Tier 1"}),
                              ("November", {"A": "Tier 6", "B": "Tier 2"})])
        self.assertEqual((m, t), ("November", {"A": "Tier 1", "B": "Tier 2"}))

    def test_old_month_never_fills_a_gap(self):
        m, t = T.merge_pulls([("November", {"A": "Tier 1"}),
                              ("October", {"B": "Tier 2"})])
        self.assertEqual((m, t), ("November", {"A": "Tier 1"}))

    def test_january_is_newer_than_december(self):
        m, t = T.merge_pulls([("December", {"B": "Tier 2"}), ("January", {"A": "Tier 1"})])
        self.assertEqual((m, t), ("January", {"A": "Tier 1"}))


class ColumnTest(unittest.TestCase):
    ROWS = [["CHURN TIERS", "Tier 1", "Tier 2", "Tier 3", "Tier 4", "Tier 5", "Tier 6"],
            ["30+ Day Churn Tiers", "6%+", "5%-6%", "4%-5%", "3%-4%", "2%-3%", "0%-2%"],
            ["Impact to ICD", "-$40", "-$25", "-$20", "$0", "$10", "$30"]]

    def test_impact_by_label(self):
        self.assertEqual(T.impact_from_sheet(self.ROWS)["Tier 3"], "-$20")
        self.assertEqual(T.impact_from_sheet(self.ROWS[:2]), {})

    def test_owner_lookup_and_alias(self):
        col = T.TierColumn("November", {"JOE LOGAN": "Tier 4"},
                           T.impact_from_sheet(self.ROWS),
                           lambda n: ["Joe Logan"] if n == "Joseph Logan" else [])
        self.assertEqual(col.header, "Nov Tier")
        self.assertEqual(col.for_owner("Joseph Logan"), ("Tier 4", "$0"))
        self.assertEqual(col.for_owner("Nobody Here"), ("", ""))


if __name__ == "__main__":
    unittest.main()

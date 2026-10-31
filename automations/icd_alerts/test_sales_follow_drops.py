"""The text follows SaraPlus down after two low reads (Eveliz, 2026-10-31)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.icd_alerts import post as P

DAY = dt.date(2026, 10, 31)


def nl(n):
    return {"Int": 0, "Int Up": 0, "DTV": 0, "NL": n}


class ShownSales(unittest.TestCase):
    def test_two_low_reads_lower_the_text(self):
        # The real case: texted Gian-Carlo 3 / Zachary 2, SaraPlus now 2 / 1.
        high = {"GIAN-CARLO HERNANDEZ": nl(3), "ZACHARY LUGONES": nl(2),
                "ALEEN ALMESMAR": nl(5)}
        now = {"GIAN-CARLO HERNANDEZ": nl(2), "ZACHARY LUGONES": nl(1),
               "ALEEN ALMESMAR": nl(5)}
        out = P.shown_sales(high, now, dict(now))
        self.assertEqual(out["GIAN-CARLO HERNANDEZ"]["NL"], 2)
        self.assertEqual(out["ZACHARY LUGONES"]["NL"], 1)
        self.assertEqual(out["ALEEN ALMESMAR"]["NL"], 5)

    def test_one_low_read_is_ignored(self):
        high = {"A": nl(3)}
        out = P.shown_sales(high, {"A": nl(1)}, {"A": nl(3)})
        self.assertEqual(out["A"]["NL"], 3)

    def test_rep_missing_from_both_reads_goes_to_zero(self):
        out = P.shown_sales({"A": nl(1), "B": nl(2)}, {"B": nl(2)}, {"B": nl(2)})
        self.assertEqual(out["A"]["NL"], 0)

    def test_empty_read_or_no_previous_changes_nothing(self):
        high = {"A": nl(3)}
        self.assertEqual(P.shown_sales(high, {}, {"A": nl(1)}), high)
        self.assertEqual(P.shown_sales(high, {"A": nl(1)}, None), high)

    def test_never_above_the_high_water(self):
        out = P.shown_sales({"A": nl(2)}, {"A": nl(4)}, {"A": nl(4)})
        self.assertEqual(out["A"]["NL"], 2)


class PrevRead(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "prev.json"

    def test_window_moves_only_on_a_new_read(self):
        f = lambda at, s: P.prev_read("eveliz", DAY, at, s, path=self.path)
        self.assertIsNone(f("12:00", {"A": nl(3)}))
        self.assertIsNone(f("12:00", {"A": nl(3)}))       # same read again
        self.assertEqual(f("12:02", {"A": nl(2)}), {"A": nl(3)})
        self.assertEqual(f("12:02", {"A": nl(2)}), {"A": nl(3)})
        self.assertEqual(f("12:04", {"A": nl(2)}), {"A": nl(2)})

    def test_dry_run_does_not_save(self):
        P.prev_read("eveliz", DAY, "12:00", {"A": nl(3)}, save=False,
                    path=self.path)
        self.assertFalse(self.path.exists())

    def test_announced_high_water_is_untouched(self):
        # decide_sales still keeps max(): a dip and recovery re-announce nothing.
        high = {"A": nl(3)}
        sold, merged, _ = P.decide_sales({"A": nl(3)}, {"A": nl(3)}, "att")
        self.assertEqual(sold, [])
        self.assertEqual(merged["A"]["NL"], 3)


if __name__ == "__main__":
    unittest.main()

"""python -m unittest automations.dd_no_captain.test_run"""
import datetime as dt
import unittest

from automations.dd_no_captain import run

HDR = ["Account.Name", "cl.ICD Owner Name", "REP.Name", "cl.DD Week",
       "cl.Description", "Total $ to ICD"]


def _row(owner, rep, week, desc, amt):
    return ["Alphalete Marketing", owner, rep, week, desc, amt]


# Raf's DD BY REP for cl.DD Week 10/10/2026, shrunk to the rows that matter:
# Grand Total to ICD $115,093.50, Captain Bonus $21,039.50.
ROWS = [
    HDR,
    _row("Rafael Hidalgo", "Null", "10/10/2026", "Captain Bonus", "$21,039.50"),
    _row("Rafael Hidalgo", "Null", "10/10/2026", "DIRECTV STREAM - Ultimate - Low", "$215.00"),
    _row("Rafael Hidalgo", "Aaron De La Torre", "10/10/2026", "WIRELESS - Port Line", "$93,839.00"),
    _row("Rafael Hidalgo", "", "Total", "", "$115,093.50"),          # subtotal: not counted
    _row("Rafael Hidalgo", "Null", "10/3/2026", "Captain's Bonus 10.3.26", "$9,000.00"),
    _row("Rafael Hidalgo", "Null", "10/3/2026", "WIRELESS - Port Line", "$50,000.00"),
    _row("Carlos Hidalgo [x]", "Null", "10/10/2026", "Captain Bonus", "$5,000.00"),
]


class SplitDD(unittest.TestCase):
    def test_video_numbers(self):
        wk, total, cap = run.split_dd(ROWS, "Rafael Hidalgo")
        self.assertEqual(wk, dt.date(2026, 10, 10))
        self.assertEqual(total, 115093.50)
        self.assertEqual(cap, 21039.50)
        self.assertEqual(round(total - cap, 2), 94054.00)

    def test_other_owner_kept_apart(self):
        self.assertEqual(run.split_dd(ROWS, "Carlos Hidalgo")[1:], (5000.0, 5000.0))

    def test_unknown_owner(self):
        self.assertIsNone(run.split_dd(ROWS, "Nobody"))

    def test_text(self):
        body = run.build_text("Rafael Hidalgo", dt.date(2026, 10, 10), 115093.50, 21039.50)
        self.assertIn("DD for week ending 10/10", body)
        self.assertIn("Total DD: $115,093.50", body)
        self.assertIn("-$21,039.50", body)
        self.assertIn("DD without captainship: $94,054.00", body)

    def test_is_current(self):
        wk = dt.date(2026, 10, 10)
        self.assertTrue(run.is_current(wk, dt.date(2026, 10, 14)))    # Wed after
        self.assertTrue(run.is_current(wk, dt.date(2026, 10, 15)))    # Thu after
        self.assertFalse(run.is_current(dt.date(2026, 10, 3), dt.date(2026, 10, 14)))


if __name__ == "__main__":
    unittest.main()

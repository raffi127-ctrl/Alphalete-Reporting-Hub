import datetime as dt
import unittest

from automations.applicant_tracker.find_ad import _like_hit, _norm, _on_day


class ListRows(unittest.TestCase):
    def test_like_finds_a_piece_of_the_name(self):
        full = _norm("Jeremiah Saintillien")
        self.assertTrue(_like_hit(full, [_norm("saintil")]))
        self.assertFalse(_like_hit(full, [_norm("sneed")]))
        self.assertFalse(_like_hit(full, []))

    def test_on_day_reads_the_report_stamp(self):
        day = dt.date(2026, 10, 27)
        self.assertTrue(_on_day("10/27/2026 4:00 PM", day))
        self.assertFalse(_on_day("10/28/2026 4:00 PM", day))
        self.assertFalse(_on_day("", day))
        self.assertFalse(_on_day("not a date", day))


if __name__ == "__main__":
    unittest.main()

"""Raf's two relay keys read as one office (2026-11-03): Lucy 1's sweep sends
him as rafael_hidalgo, his own MacBook as raf. Every reader keys on the old
name, so the reader folds the new key in and lets the machine's day win."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_sales_board import relay_read as RR

D1, D2 = dt.date(2026, 11, 2), dt.date(2026, 11, 3)


def _row(office, day, sales):
    import json
    return {RR.COL_OFFICE: office, RR.COL_DAY: day.isoformat(),
            RR.COL_SALES: json.dumps(sales)}


class TwoKeysOneOffice(unittest.TestCase):
    def test_machine_day_wins_and_old_days_survive(self):
        rows = [_row("rafael_hidalgo", D1, {"A": {"Int": 1}}),
                _row("rafael_hidalgo", D2, {"A": {"Int": 26}}),
                _row("raf", D2, {"A": {"Int": 25}})]
        with mock.patch.object(RR, "_rows", return_value=rows), \
             mock.patch.object(RR, "_day", side_effect=lambda v: dt.date.fromisoformat(v)):
            out = RR.read_all()
        self.assertNotIn("raf", out)
        self.assertEqual(out["rafael_hidalgo"][D1]["A"]["Int"], 1)
        self.assertEqual(out["rafael_hidalgo"][D2]["A"]["Int"], 25)

    def test_machine_only_still_reads_under_the_old_key(self):
        rows = [_row("raf", D2, {"A": {"Int": 3}})]
        with mock.patch.object(RR, "_rows", return_value=rows), \
             mock.patch.object(RR, "_day", side_effect=lambda v: dt.date.fromisoformat(v)):
            out = RR.read_all()
        self.assertEqual(out["rafael_hidalgo"][D2]["A"]["Int"], 3)


if __name__ == "__main__":
    unittest.main()

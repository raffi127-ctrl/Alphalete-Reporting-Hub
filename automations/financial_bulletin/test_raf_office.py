"""Raf's own office on the bulletin (Rafael 2026-11-12): Double Entry weeks
(Saturday book ends) land on the tab's Sunday column 8 days later, and
Operating % comes out in points whichever scale the source used."""
import datetime as dt
import unittest
from unittest import mock

from automations.financial_bulletin import run as R


def _office(metrics):
    return [{"office": "ALPHALETE MARKETING, INC. (RAFAEL HIDALGO-TX)",
             "owner": "RAFAEL HIDALGO", "state": "TX", "metrics": metrics}]


class OwnOfficeSeries(unittest.TestCase):
    def test_book_week_moves_to_the_sunday_column(self):
        got = R.own_office_series(_office({
            "TOTAL FUNDS AVAILABLE": {dt.date(2026, 11, 7): 1000.0},
            "OWNERS PAYROLL": {dt.date(2026, 11, 7): 500.0},
        }))
        self.assertEqual(got["Total Funds Available"], {dt.date(2026, 11, 15): 1000.0})
        self.assertEqual(got["Owners Payroll"], {dt.date(2026, 11, 15): 500.0})
        self.assertNotIn("Owners Withdrawal", got)

    def test_operating_pct_in_points_and_zero_is_blank(self):
        got = R.own_office_series(_office({"OPERATING PERCENTAGE %": {
            dt.date(2026, 10, 31): 0.523, dt.date(2026, 11, 7): 0}}))
        self.assertAlmostEqual(got["Operating %"][dt.date(2026, 11, 8)], 52.3)
        self.assertNotIn(dt.date(2026, 11, 15), got["Operating %"])

    def test_reuses_the_financial_pull_without_signing_in(self):
        from automations.financial_report import web_source
        pulled = {R.RAF_OFFICE_KEY: _office(
            {"TOTAL FUNDS AVAILABLE": {dt.date(2026, 11, 7): 7.0}})}
        with mock.patch.object(web_source, "LAST_OFFICES", pulled), \
                mock.patch.object(web_source, "fetch_office_history") as hist:
            got = R.read_raf_office()
        hist.assert_not_called()
        self.assertEqual(got["Total Funds Available"], {dt.date(2026, 11, 15): 7.0})

    def test_unreachable_double_entry_drops_only_his_row(self):
        from automations.financial_report import web_source
        with mock.patch.object(web_source, "LAST_OFFICES", None), \
                mock.patch.object(web_source, "fetch_office_history",
                                  side_effect=RuntimeError("no OTP")):
            self.assertEqual(R.read_raf_office(), {})


if __name__ == "__main__":
    unittest.main()

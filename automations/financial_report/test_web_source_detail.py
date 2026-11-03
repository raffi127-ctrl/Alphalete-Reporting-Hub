"""The Financial Report fills what the org summary misses (Joseph Logan)."""
import datetime as dt
import unittest

from automations.financial_report import web_source as w

W1, W2 = dt.date(2026, 10, 3), dt.date(2026, 10, 10)


def _report():
    return {
        "ranges": [{"label": "Week 1", "end_date": "2026-10-03"},
                   {"label": "Week 2", "end_date": "2026-10-10"},
                   {"label": "Monthly Total"}],
        "sections": [
            {"label": "REGULAR EXPENSES", "items": [
                {"label": "Payroll Expenses:Owner Payroll",
                 "transactions": ["500.00", "600.00", "1100.00"]},
                {"label": "Shareholder Distributions",
                 "transactions": ["1693.49", "924.38", "2617.87"]},
                {"label": "Payroll Expenses:Employer Payroll Tax",
                 "transactions": ["1.00", "2.00", "3.00"]}]},
            {"label": "LOAN BALANCES - MONEY OUT", "items": [
                {"label": "Shareholder Distributions",
                 "transactions": ["34939.21", "35863.59", "70802.80"]}]},
        ]}


class DetailLines(unittest.TestCase):
    def test_reads_weeks_not_the_monthly_total(self):
        got = w._detail_lines(_report())
        self.assertEqual(got["OWNERS PAYROLL"], {W1: 500.0, W2: 600.0})

    def test_running_balance_is_not_the_withdrawal(self):
        got = w._detail_lines(_report())
        self.assertEqual(got["OWNERS WITHDRAWAL"], {W1: 1693.49, W2: 924.38})


class ApplyDetail(unittest.TestCase):
    def test_all_zero_summary_takes_the_report(self):
        m = {"OWNERS PAYROLL": {W1: 0.0, W2: 0.0}}
        w._apply_detail(m, w._detail_lines(_report()))
        self.assertEqual(m["OWNERS PAYROLL"], {W1: 500.0, W2: 600.0})

    def test_summary_with_a_number_is_left_alone(self):
        m = {"OWNERS PAYROLL": {W1: 0.0, W2: 1500.0}}
        self.assertEqual(w._needs_detail(m), [])
        w._apply_detail(m, w._detail_lines(_report()))
        self.assertEqual(m["OWNERS PAYROLL"], {W1: 0.0, W2: 1500.0})

    def test_week_outside_the_window_is_not_added(self):
        m = {"OWNERS PAYROLL": {W1: 0.0}}
        w._apply_detail(m, w._detail_lines(_report()))
        self.assertEqual(m["OWNERS PAYROLL"], {W1: 500.0})

    def test_real_zero_stays_zero(self):
        m = {"OWNERS PAYROLL": {W1: 0.0}}
        w._apply_detail(m, {})
        self.assertEqual(m["OWNERS PAYROLL"], {W1: 0.0})


if __name__ == "__main__":
    unittest.main()

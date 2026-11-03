"""The Financial Report fills what the org summary misses (Joseph Logan)."""
import datetime as dt
import unittest
from unittest import mock

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


# Joseph's real charges for the week ending 10/3.
_ADS = [{"transaction_name": "Jobs2Me", "amount": "12.75"},
        {"transaction_name": None, "amount": "-107.02"},
        {"transaction_name": "Jobs2Me", "amount": "137.00"},
        {"transaction_name": "Indeed", "amount": "501.82"},
        {"transaction_name": "Indeed", "amount": "500.57"},
        {"transaction_name": "Indeed", "amount": "170.87"},
        {"transaction_name": "Indeed", "amount": "57.89"},
        {"transaction_name": "Indeed", "amount": "281.60"}]
_RECRUITER = [{"transaction_name": "Aptel", "amount": "20.00"},
              {"transaction_name": "Arcadia Consulting", "amount": "235.00"},
              {"transaction_name": None, "amount": "750.00"}]


class Payees(unittest.TestCase):
    def test_only_recruiting_lines_in_expenses_are_opened(self):
        report = {"sections": [
            {"label": "REGULAR EXPENSES", "items": [
                {"code": "725A", "label": "Recruiting Costs:Recruiter"},
                {"code": "725B", "label": "Recruiting Costs:Advertising and Promotion"},
                {"code": "600", "label": "Office Supplies"},
                {"code": "1", "label": "INDEED"}]},
            {"label": "OTHER", "items": [
                {"code": "9", "label": "Recruiting Costs:Elsewhere"}]}]}
        self.assertEqual(w._recruiting_accounts(report), ["725A", "725B"])

    def test_totals_leave_out_jobs2me_and_unnamed_lines(self):
        self.assertEqual(w._payee_totals(_ADS), {"INDEED": 1512.75})
        self.assertEqual(w._payee_totals(_RECRUITER),
                         {"APTEL": 20.0, "ARCADIA CONSULTING": 235.0})

    def test_fetch_asks_for_each_saturday_week_and_every_page(self):
        urls = []

        def fake_get(page, url, token, company_id=None):
            urls.append(url)
            self.assertEqual(company_id, 10000392)
            if "725A" in url:
                return {"items": _RECRUITER}
            more = url.endswith("page=1")
            return {"items": _ADS[:2] if more else _ADS[2:],
                    "pagination": {"has_more_pages": more}}

        with mock.patch.object(w, "_get", fake_get):
            got = w._fetch_payees(None, "t", 10000392, ["725A", "725B"], [W1])
        self.assertEqual(got[W1], {"APTEL": 20.0, "ARCADIA CONSULTING": 235.0,
                                   "INDEED": 1512.75})
        self.assertEqual(len(urls), 3)
        self.assertIn("start_at=2026-09-27&end_at=2026-10-03", urls[0])

    def test_fills_what_the_summary_lacks(self):
        m = {}
        w._apply_payees(m, {W1: {"INDEED": 1512.75}, W2: {}})
        self.assertEqual(m, {"INDEED": {W1: 1512.75}})

    def test_summary_number_is_not_replaced(self):
        m = {"INDEED": {W1: 0.0, W2: 900.0}}
        w._apply_payees(m, {W1: {"INDEED": 1512.75}})
        self.assertEqual(m["INDEED"], {W1: 0.0, W2: 900.0})


if __name__ == "__main__":
    unittest.main()

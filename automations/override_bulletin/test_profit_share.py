"""Raf's Profit Share email -> Special Override amount + week (Maud 2026-11-09)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.override_bulletin import profit_share as PS


def _book(path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "Journal"
    ws = wb.create_sheet("Summary")
    ws.append([None, None, "Program", "YTD", "P13-2026", "P12-2026", "P11-2026", "P10-2026"])
    ws.append([None, None, "RES-ATT-SN", 26354.37, None, None, None, 26354.37])
    ws.append([None, None, "Raf Hidalgo's Profit Share", 26354.37, 0, 0, 0, 26354.37])
    ws.append([None, None, "M&C Reserve @ 8%", -2108.35, 0, 0, 0, -2108.35])
    ws.append([None, None, "Profit Sharing net of M&C Reserve", 24246.0186, 0, 0, 0, 24246.0186])
    wb.save(path)


class ProfitShareTest(unittest.TestCase):
    def test_reads_net_for_the_period_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Raf Hidalgo Profit Sharing Report P10 2026 Final.xlsx"
            _book(p)
            self.assertEqual(PS.parse_xlsx(p),
                             {"P10-2026": {"net": 24246.02, "gross": 26354.37}})

    def test_posted_date_from_body(self):
        body = "This will be posted to your security account by EOD November 9, 2026."
        self.assertEqual(PS.posted_date(body, None), dt.date(2026, 11, 9))
        self.assertEqual(PS.posted_date("no sentence", dt.date(2026, 11, 3)),
                         dt.date(2026, 11, 3))

    def test_week_is_the_sunday_closing_it(self):
        self.assertEqual(PS.week_label(dt.date(2026, 11, 9)), "11.15.26")
        self.assertEqual(PS.week_label(dt.date(2026, 11, 15)), "11.15.26")
        self.assertEqual(PS.week_label(dt.date(2026, 12, 28)), "1.3.27")

    def test_by_week_sums_two_periods_same_week(self):
        es = [{"week": "11.15.26", "net": 10.0}, {"week": "11.15.26", "net": 5.5},
              {"week": None, "net": 99.0}]
        self.assertEqual(PS.by_week(es), {"11.15.26": 15.5})


if __name__ == "__main__":
    unittest.main()

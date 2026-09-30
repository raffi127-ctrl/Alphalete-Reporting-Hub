"""NDS_BOARD_SPEC reads a two-week crosstab ('Thisweekandlast') and must keep
ONLY the reporting week's WIRELESS rows — the same numbers WIRELESSONLY gave the
board (proven 0 diffs, 2026-09-30). Weekday names alone would fold last
Monday onto this Monday."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.org_sales_board import section_pull as sp

CSV = "\n".join([
    "\t".join(["", "", ""] + ["9/27/2026"] * 8 + ["10/4/2026"] * 3 + ["Grand Total"]),
    "\t".join(["Owner & Office ", "Rep Name", "Product Type (Broken Out)",
               "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
               "Saturday", "Sunday", "Total", "Monday", "Tuesday", "Total", "Total"]),
    "\t".join(["Grand Total", "Total", "Total"] + ["99"] * 12),
    "\t".join(['"JAIRO RUIZ\r[profits management, inc.]"', "Total", "Total"] + ["50"] * 12),
    "\t".join(['"JAIRO RUIZ\r[profits management, inc.]"', "Rep A", "WIRELESS",
               "10", "11", "", "", "", "", "", "21", "7", "3", "10", "31"]),
    "\t".join(['"JAIRO RUIZ\r[profits management, inc.]"', "Rep A", "AIR",
               "1", "1", "", "", "", "", "", "2", "4", "", "4", "6"]),
    "\t".join(['"JAIRO RUIZ\r[profits management, inc.]"', "Rep B", "WIRELESS",
               "5", "", "", "", "", "", "2", "7", "1", "", "1", "8"]),
])


class NdsWeekRow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "twl.csv"
        self.path.write_text(CSV, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _parse(self, today):
        out = sp.parse_byday(sp.NDS_BOARD_SPEC, self.path, today)
        return out["jairo ruiz"]["Wireless"]

    def test_midweek_reads_only_this_week_wireless(self):
        days = self._parse(dt.date(2026, 9, 30))            # Wednesday
        self.assertEqual(days, {dt.date(2026, 9, 28): 8, dt.date(2026, 9, 29): 3})

    def test_monday_reads_the_closing_week(self):
        days = self._parse(dt.date(2026, 9, 28))            # Monday → WE 9/27
        self.assertEqual(days, {dt.date(2026, 9, 21): 15, dt.date(2026, 9, 22): 11,
                                dt.date(2026, 9, 27): 2})

    def test_not_week_pinned(self):
        # its week filter is 'Sales Week' (relative); the pin field blanks it
        self.assertFalse(sp.NDS_BOARD_SPEC.week_pin)


if __name__ == "__main__":
    unittest.main()

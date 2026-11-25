"""Crosstab -> direct-.csv shape (2026-11-25: the bare ORDERLOG.csv went to
another worksheet, so _fetch_csv serves bare-ORDERLOG urls from the crosstab).

    python -m unittest automations.att_order_log.test_crosstab_to_csv
"""
import csv
import io
import unittest

from automations.att_order_log import run as R

HDR = ["Owner & Office", "Rep", "Customer Name", "sp.Order Date (copy)",
       "spe.Name", "Product Type (Broken Out)",
       "Unit Count", "Total Volume", "Total Activations",
       "Sales (All) (non pmts) (60-120)"]


def _parse(body):
    return list(csv.reader(io.StringIO(body.decode("utf-8"))))


class CrosstabToCsv(unittest.TestCase):
    def test_backfills_row_headers_and_unpivots_measures(self):
        grid = [HDR,
                ["CARLOS HIDALGO\n [x]", "Ana", "ACME", "11/23/2026",
                 "SPE-1", "WIRELESS", "1", "1", "0", "0"],
                ["", "", "", "", "SPE-2", "AIR/AWB", "1", "1", "1", "0"],
                ["", "Bo", "ZED", "11/24/2026", "SPE-3", "WIRELESS",
                 "1", "1,000", "0", "0"]]
        rows = _parse(R._crosstab_to_long_csv(grid))
        hdr = rows[0]
        self.assertEqual(hdr[-2:], ["Measure Names", "Measure Values"])
        self.assertNotIn("Unit Count", hdr)
        self.assertEqual(len(rows) - 1, 3 * 4)            # 3 lines x 4 measures
        spe2 = [r for r in rows[1:] if r[hdr.index("spe.Name")] == "SPE-2"]
        self.assertEqual({r[hdr.index("Rep")] for r in spe2}, {"Ana"})
        self.assertEqual({r[hdr.index("Customer Name")] for r in spe2}, {"ACME"})
        spe3 = [r for r in rows[1:] if r[hdr.index("spe.Name")] == "SPE-3"]
        self.assertEqual({r[0] for r in spe3}, {"CARLOS HIDALGO\n [x]"})
        self.assertIn(["Total Volume", "1000"],
                      [r[-2:] for r in spe3])
        # emitted in the direct export's exact spelling (double space), which
        # sheet.MEASURES keys on — whatever spacing the crosstab header used
        from automations.att_order_log import sheet
        self.assertEqual({r[-2] for r in rows[1:]}, set(sheet.MEASURES))

    def test_bare_cr_in_owner_round_trips_through_load_rows(self):
        """11/25: an owner cell with a bare \\r (no comma to force quoting) went
        out unquoted, split every row, and load_rows counted each sale 4x."""
        import os
        import tempfile

        from automations.att_order_log import clean
        grid = [HDR,
                ["ALEXANDER GODOY\r [jvc joint ventures inc]", "Kayla", "MIKE",
                 "11/25/2026", "SPE-1", "WIRELESS", "1", "1", "0", "0"],
                ["", "", "", "", "SPE-2", "WIRELESS", "1", "1", "0", "0"],
                ["ADRIANA A\r\n [ace, inc.]", "Abi", "DONNA", "11/25/2026",
                 "SPE-3", "WIRELESS", "1", "1", "0", "0"]]
        fd, p = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            with open(p, "wb") as f:
                f.write(R._crosstab_to_long_csv(grid))
            lines = clean.load_rows(p)
        finally:
            os.remove(p)
        self.assertEqual(len(lines), 3)
        self.assertEqual({l["spe.Name"] for l in lines}, {"SPE-1", "SPE-2", "SPE-3"})
        self.assertEqual(lines[1]["Owner & Office"],
                         "ALEXANDER GODOY\n [jvc joint ventures inc]")

    def test_empty_window_keeps_the_callers_empty_wording(self):
        with self.assertRaises(RuntimeError) as cm:
            R._crosstab_to_long_csv([HDR])
        self.assertIn("status=200", str(cm.exception))
        self.assertRegex(str(cm.exception),
                         r"order-log export failed: status=(\d+) bytes=(\d+)")

    def test_only_bare_orderlog_csv_is_rerouted(self):
        bare = ("https://us-east-1.online.tableau.com/t/sci/views/ATTTRACKER-B2B/"
                "ORDERLOG.csv?:refresh=yes&Start%20Date=2026-11-01&End%20Date=2026-11-07")
        self.assertTrue(R._is_bare_orderlog_csv(bare))
        self.assertEqual(R._window_from_url(bare)[1].isoformat(), "2026-11-07")
        self.assertFalse(R._is_bare_orderlog_csv(
            "https://x/t/sci/views/ATTTRACKER-B2B/ORDERLOG/abc/ALLREPS.csv?:refresh=yes"))
        self.assertFalse(R._is_bare_orderlog_csv("u"))


if __name__ == "__main__":
    unittest.main()

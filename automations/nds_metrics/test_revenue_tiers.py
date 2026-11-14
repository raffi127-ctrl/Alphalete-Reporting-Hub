"""Revenue Board tier-bonus potential columns (Carlos 2026-11-14).

  python -m unittest automations.nds_metrics.test_revenue_tiers
"""
import datetime as dt
import unittest
from unittest import mock

from automations.nds_metrics import run as R

BANDS = [(4, 30.0), (5, 50.0), (7, 75.0), (9, 110.0)]


class Cells(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(R.tier_band_labels(BANDS), ["4 ORDERS", "5–6 ORDERS", "7–8 ORDERS", "9+ ORDERS"])

    def test_roseanna_4_orders_13_lines(self):
        c = R.tier_cells(4, 13, BANDS)
        self.assertEqual([x["text"] for x in c],
                         ["13", "✓ $390 now", "+1 → $700", "+3 → $1,200", "+5 → $1,980"])
        self.assertEqual([x["cls"] for x in c], ["ct", "now", "one", "far", "far"])

    def test_zero_and_max(self):
        self.assertEqual([x["text"] for x in R.tier_cells(0, 0, BANDS)],
                         ["0", "+4 → $120", "+5 → $250", "+7 → $525", "+9 → $990"])
        c = R.tier_cells(9, 20, BANDS)
        self.assertEqual([x["text"] for x in c], ["20", "✓", "✓", "✓", "✓ $2,200 now"])


class Counting(unittest.TestCase):
    HDR = ["Rep", "sp.Order Date (copy)", "Ported From", "spe.TN Type", "Package", "sp.SPM Number", "DTR Status"]

    def _row(self, rep, od, tn="port", spm="DSI1", ported="T-MOBILE", pkg="AT&T Extra 2.0", st="Shipped"):
        return [rep, od, ported if tn == "port" else "", tn, pkg, spm, st]

    def test_orders_lines_and_double_days(self):
        cols = R.Cols(self.HDR)
        rows = [self._row("Ana", "11/9/2026", spm="DSI1"),           # Mon: 1 order, 3 port lines
                self._row("Ana", "11/9/2026", spm="DSI1"),
                self._row("Ana", "11/9/2026", spm="DSI1"),
                self._row("Ana", "11/10/2026", spm="DSI2"),          # Tue: double-tier day -> counts twice
                self._row("Ana", "11/11/2026", tn="new", spm="DSI3"),   # new line only: not an order, not a port line
                self._row("Ana", "11/8/2026", spm="DSI4"),           # Sunday 11/8 is in the tier week
                self._row("Ana", "11/7/2026", spm="DSI0"),           # last tier week: out
                self._row("Ana", "11/12/2026", spm="DSI1", st="Canceled"),   # cancelled port line: order counts, line does not
                self._row("Ben", "11/12/2026", tn="upgrade", spm="DSI5")]  # upgrade-only: no order
        ix = {h: i for i, h in enumerate(self.HDR)}
        with mock.patch.object(R, "sow_rates", lambda: {"rep_tier": {"bands": BANDS, "double_days": ["2026-11-10"]}}), \
             mock.patch("automations.nds_metrics.double_tier.days", lambda seed, log=print: set(seed)):
            headers, cells, counts = R.revenue_tier_columns(cols, rows, dt.date(2026, 11, 9), ix["sp.Order Date (copy)"],
                                                    ix["Rep"], ix["Ported From"], ix["spe.TN Type"],
                                                    ix["sp.SPM Number"], log=lambda *_a, **_k: None)
        self.assertEqual(len(headers), 5)
        self.assertEqual(counts["Ana"], (4, 5))                 # DSI1 + DSI2x2 + DSI4 = 4 orders; 5 live port lines
        self.assertEqual(cells["Ana"][0]["text"], "5")
        self.assertEqual(cells["Ana"][1]["text"], "✓ $150 now")
        self.assertNotIn("Ben", cells)

    def test_flag_default_on_and_texted(self):
        self.assertTrue(R.FLAGS["tier_columns"])            # shipped 11/14 after Carlos's OK
        self.assertIn("revenue_board", R.TEXT_SECTIONS)


if __name__ == "__main__":
    unittest.main()

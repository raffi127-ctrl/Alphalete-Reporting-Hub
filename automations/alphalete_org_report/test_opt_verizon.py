"""opt_verizon — the Verizon OPT rows mirror NDS's, from Credico's files."""
import datetime as dt
import glob
import unittest
from pathlib import Path

from automations.alphalete_org_report import opt_verizon as V

INV = Path("output/_verizon_inventory")


class Mirror(unittest.TestCase):
    def test_every_row_label_is_an_nds_label(self):
        from automations.alphalete_org_report import opt_nds
        src = Path(opt_nds.__file__).read_text()
        for label, _src, _k in V.ROWS:
            self.assertIn('"%s"' % label, src, label)

    def test_credico_saturday_lands_on_the_next_sunday(self):
        self.assertEqual(V.sheet_week(dt.date(2026, 10, 31)), dt.date(2026, 11, 1))

    def test_missing_overview_value_is_blank_not_zero(self):
        vals = V.values_for({"Scoring HC": None, "Valid Lines": 99})
        self.assertIsNone(vals["Active Selling Heads"])
        self.assertEqual(vals["AIR"], "na")


@unittest.skipUnless(glob.glob(str(INV / "raw/Quality Scorecard*SCI-WO*.pdf")), "no local Quality Scorecard")
class RealFiles(unittest.TestCase):
    def test_quality_4wk_cancel_for_nico(self):
        q = V.quality_cancel(Path(glob.glob(str(INV / "raw/Quality Scorecard*SCI-WO*.pdf"))[0]), "Nicolas Murrugarra")
        self.assertEqual(q[0], dt.date(2026, 11, 3))
        self.assertAlmostEqual(q[1], 0.211)          # 8 of 38 canceled, 4 weeks rolling


if __name__ == "__main__":
    unittest.main()

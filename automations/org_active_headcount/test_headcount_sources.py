"""The two 11/1 zeros on the Org Active Headcount tab: a cut name that lost its
dots, and a Verizon edition whose first page is already the next week."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.org_active_headcount import daily, tracker_readings as tr
from automations.org_sales_board import verizon_pull as vp


class CutNames(unittest.TestCase):
    def hits(self, icd, label):
        return tr.match(icd, [{"owner": label, "rep_count": 6}])

    def test_cut_name_with_or_without_dots(self):
        for label in ("VALERIA TRISTA..", "VALERIA TRISTA", "VALERIA TRISTA\u2026",
                      "Valeria Tristan"):
            self.assertTrue(self.hits("Valeria Tristan", label), label)

    def test_someone_else_is_not_matched(self):
        for label in ("VALERIA TORRES", "VALERIA TRI", "MARIA TRISTA", "VALERIA"):
            self.assertFalse(self.hits("Valeria Tristan", label), label)


def _page(doc, week_ending, rows):
    pg = doc.new_page(width=800, height=400)
    pg.insert_text((20, 30), f"Week Ending {week_ending}", fontsize=10)
    pg.insert_text((600, 60), "HC", fontsize=10)
    for i, (name, hc) in enumerate(rows):
        pg.insert_text((20, 90 + i * 20), name, fontsize=10)
        pg.insert_text((600, 90 + i * 20), str(hc), fontsize=10)


class VerizonWeek(unittest.TestCase):
    def setUp(self):
        import fitz
        self.dir = tempfile.TemporaryDirectory()
        self.pdf = Path(self.dir.name) / "edition.pdf"
        doc = fitz.open()
        _page(doc, "November 7, 2026", [("Robert Griffin", 3)])
        _page(doc, "October 31, 2026", [("Nicolas Murrugarra", 15)])
        doc.save(str(self.pdf))
        doc.close()

    def tearDown(self):
        self.dir.cleanup()

    def test_closed_week_is_read_from_its_own_page(self):
        self.assertEqual(vp.scoring_hc(self.pdf, "Nicolas Murrugarra",
                                       week_ending=dt.date(2026, 10, 31)), 15)

    def test_owner_not_on_that_week_is_zero(self):
        self.assertEqual(vp.scoring_hc(self.pdf, "Nicolas Murrugarra",
                                       week_ending=dt.date(2026, 11, 7)), 0)

    def test_week_not_in_the_edition_is_unknown_not_zero(self):
        self.assertIsNone(vp.scoring_hc(self.pdf, "Nicolas Murrugarra",
                                        week_ending=dt.date(2026, 10, 3)))

    def test_no_week_reads_the_first_page(self):
        self.assertEqual(vp.scoring_hc(self.pdf, "Robert Griffin"), 3)

    def test_each_board_day_reads_the_right_week(self):
        for i in range(7):
            day = dt.date(2026, 10, 26) + dt.timedelta(days=i)
            self.assertEqual(daily.vzw_week_ending(day), dt.date(2026, 10, 31), day)
        self.assertEqual(daily.vzw_week_ending(dt.date(2026, 11, 2)), dt.date(2026, 11, 7))


if __name__ == "__main__":
    unittest.main()

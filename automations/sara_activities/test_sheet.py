"""python -m unittest automations.sara_activities.test_sheet"""
import datetime as dt
import unittest

from automations.sara_activities import config as C
from automations.sara_activities import sheet as SH

TAB_HDR = ["Date", "TIME", "Order ID", "Dealer Code", "User Name", "Agent Name",
           "Customer", "Customer Email", "Phone", "NOTES"]
CSV_HDR = ["Date", "Order ID", "Dealer Code", "User Name", "Agent Name",
           "Customer", "Customer Email", "Phone", "Zip", "Disposition"]


def _plan(existing, recs):
    return SH.plan(existing, recs, C.COLUMN_SOURCE, C.TIME_HEADER, C.KEY_HEADER)


class ParseWhen(unittest.TestCase):
    def test_export_tt_is_24h(self):
        self.assertEqual(SH.parse_when("11/21/26 15:02 tt"), dt.datetime(2026, 11, 21, 15, 2))

    def test_grid_ampm(self):
        self.assertEqual(SH.parse_when("11/21/26 03:02 PM"), dt.datetime(2026, 11, 21, 15, 2))
        self.assertEqual(SH.parse_when("11/21/2026 12:14 AM"), dt.datetime(2026, 11, 21, 0, 14))

    def test_junk(self):
        self.assertIsNone(SH.parse_when(""))
        self.assertIsNone(SH.parse_when("Date"))

    def test_time_format(self):
        self.assertEqual(SH.fmt_time(dt.datetime(2026, 1, 1, 15, 2)), "3:02 PM")
        self.assertEqual(SH.fmt_time(dt.datetime(2026, 1, 1, 0, 5)), "12:05 AM")
        self.assertEqual(SH.fmt_time(dt.datetime(2026, 1, 1, 12, 0)), "12:00 PM")


class Plan(unittest.TestCase):
    def setUp(self):
        self.existing = [
            TAB_HDR,
            ["11/21/26 15:02 tt", "3:02 PM", "SPM286004972", "L4NQL", "SAGE.ORTIZ",
             "SAGE ORTIZ", "KRISTINA", "k@x.com", "214", "raf note"],
            ["11/21/26 15:00 tt", "", "NG286004517", "L4NQL", "ANA.GRIFFIN",
             "ANA GRIFFIN", "Jose", "j@x.com", "915", ""],
        ]
        rows = [
            ["11/21/26 15:02 tt", "SPM286004972", "L4NQL", "SAGE.ORTIZ", "SAGE ORTIZ",
             "KRISTINA", "k@x.com", "214", "75409", "Pending"],
            ["11/22/26 10:05 tt", "NG1", "L4NQL", "A.B", "A B", "C1", "c1@x", "1", "1", ""],
            ["11/22/26 14:30 tt", "SPM2", "L4NQL", "D.E", "D E", "C2", "c2@x", "2", "2", ""],
            ["11/22/26 14:30 tt", "SPM2", "L4NQL", "D.E", "D E", "C2", "c2@x", "2", "2", ""],
            ["", "", "", "", "", "", "", "", "", ""],
        ]
        self.recs = SH.records_from_table(CSV_HDR, rows)

    def test_only_new_ids_newest_first(self):
        new, _ = _plan(self.existing, self.recs)
        self.assertEqual([r[2] for r in new], ["SPM2", "NG1"])

    def test_row_layout_by_label(self):
        new, _ = _plan(self.existing, self.recs)
        self.assertEqual(new[0], ["11/22/26", "2:30 PM", "SPM2", "L4NQL", "D.E", "D E",
                                  "C2", "c2@x", "2", ""])

    def test_fills_only_blank_time(self):
        _, fills = _plan(self.existing, self.recs)
        self.assertEqual(fills, [(3, 2, "3:00 PM")])

    def test_columns_moved_still_land(self):
        hdr = ["NOTES", "Order ID", "Date", "TIME", "Phone", "Customer", "Customer Email",
               "Agent Name", "User Name", "Dealer Code"]
        new, _ = _plan([hdr], self.recs[1:2])
        row = dict(zip(hdr, new[0]))
        self.assertEqual(row["Order ID"], "NG1")
        self.assertEqual(row["TIME"], "10:05 AM")
        self.assertEqual(row["NOTES"], "")

    def test_late_record_lands_in_its_slot(self):
        existing = [TAB_HDR,
                    ["11/23/26", "2:33 PM", "A"], ["11/23/26", "1:53 PM", "B"],
                    ["11/21/26 15:02 tt", "3:02 PM", "C"]]
        new = [["11/23/26", "1:46 PM", "LATE"], ["11/23/26", "2:34 PM", "TOP"]]
        out = SH.placements(existing, new, 0, 1)
        sim = existing[1:]
        for at, row in out:
            sim.insert(at - 2, row)
        self.assertEqual([r[2] for r in sim], ["TOP", "A", "B", "LATE", "C"])

    def test_missing_header_refuses(self):
        with self.assertRaises(ValueError):
            _plan([["Date", "Order ID"]], self.recs)

    def test_export_without_order_id_refuses(self):
        with self.assertRaises(ValueError):
            SH.records_from_table(["Date", "Customer"], [["x", "y"]])


if __name__ == "__main__":
    unittest.main()

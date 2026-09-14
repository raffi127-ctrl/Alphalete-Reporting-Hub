"""python -m unittest automations.weekly_knocks_focus.test_box"""
import unittest

from automations.weekly_knocks_focus import box as BX

# Column B of 'Kash Rai - Test Eve' around the box — Eve's labels, typed off
# the board as Raf re-labelled it 2026-09-13.
COL_B = (["WE SUNDAY"] + [""] * 44 + [
    "WEEKLY KNOCKS DATA",
    "Mon-Fri Total Leads Knocked", "Mon-Fri Total Knocks",
    "Mon-Fri AVG Doors / Day", "Mon-Sat Total Talk To's",
    "Mon-Sat % Talk To's per knocks", "Mon-Sat AVG Talk To's / Day",
    "Mon-Sat total apps", "Mon-Sat AVG Talk To's per app",
    "Mon-Fri AVG First Knock", "Mon-Fri AVG Last Knock",
    "Mon-Fri AVG Hrs Knocking / Day", "Mon-Sat AVG Gap / Day",
    "Mon-Sat Total Gap Hours", "Sat Clocked In", "Sat AVG Doors / Day",
    "Sat AVG Talk To's / Day", "Sat First Knock", "Sat AVG Hrs Knocking",
    "Sat AVG Gap Hours", "Sat Last Knock",
    "", "Office Metrics", "Total Apps"])

# weekly_knock_dispositions.board.HEADERS as of 2026-09-13.
HEADERS = [
    "# Reps (Over 20 Doors / Day)", "Rep",
    "Mon–Fri Total Leads Knocked", "Mon–Fri Total Knocks",
    "Mon–Fri Avg Doors / Day", "Mon–Sat Total Talk To's",
    "Mon–Sat % Talk To's per Knocks", "Mon–Sat Avg Talk To's / Day",
    "Mon–Sat Total Apps", "Mon–Sat Avg Talk To's per App",
    "Mon–Fri Avg First Knock", "Mon–Fri Avg Last Knock",
    "Mon–Fri Avg Hrs Knocking / Day", "Mon–Sat Avg Gap / Day",
    "Mon–Sat Total Gap Hours", "Sat Clocked In", "Sat Avg Doors / Day",
    "Sat Avg Talk To's / Day", "Sat First Knock", "Sat Avg Hrs Knocking",
    "Sat Avg Gap Hours", "Sat Last Knock"]

TOTALS = ["23 of 27", "OFFICE TOTALS", "5100", "8300", "70.1", "2111",
          "21.4%", "14.07", "146", "14.46", "1:32 PM", "7:51 PM", "3h 30m",
          "2h 33m", "367h 9m", "14 of 24", "55.2", "9.1", "11:41 AM",
          "3h 11m", "1h 12m", "4:04 PM"]


class BoxTest(unittest.TestCase):
    def test_every_board_column_lands_on_the_row_with_its_name(self):
        header, updates, missing = BX.plan(HEADERS, TOTALS, COL_B)
        self.assertEqual(header, 46)
        self.assertEqual(missing, [])
        got = {label: (row, value) for row, label, value in updates}
        self.assertEqual(len(got), 20)
        self.assertEqual(got["Mon-Fri Total Leads Knocked"], (47, "5100"))
        self.assertEqual(got["Mon-Sat total apps"], (53, "146"))
        self.assertEqual(got["Sat AVG Doors / Day"], (61, "55.2"))
        self.assertEqual(got["Sat AVG Talk To's / Day"], (62, "9.1"))
        self.assertEqual(got["Sat Last Knock"], (66, "4:04 PM"))

    def test_rep_count_and_name_columns_are_not_office_numbers(self):
        _h, updates, missing = BX.plan(HEADERS, TOTALS, COL_B)
        values = {v for _r, _l, v in updates}
        self.assertNotIn("23 of 27", values)
        self.assertNotIn("OFFICE TOTALS", values)

    def test_box_stops_at_blank_row_never_reaches_office_metrics(self):
        _h, rows = BX.find_box(COL_B)
        self.assertNotIn(BX.norm("Total Apps"), rows)
        self.assertEqual(max(rows.values()), 66)

    def test_blank_board_cell_is_not_written(self):
        totals = list(TOTALS)
        totals[HEADERS.index("Sat Clocked In")] = ""
        _h, updates, _m = BX.plan(HEADERS, totals, COL_B)
        self.assertNotIn("Sat Clocked In", {l for _r, l, _v in updates})

    def test_board_column_without_a_box_row_is_reported(self):
        col_b = [x for x in COL_B if x != "Sat AVG Talk To's / Day"]
        _h, _u, missing = BX.plan(HEADERS, TOTALS, col_b)
        self.assertEqual(missing, ["Sat Avg Talk To's / Day"])

    def test_tab_without_box(self):
        self.assertEqual(BX.plan(HEADERS, TOTALS, ["WE SUNDAY", "Total Apps"]),
                         (None, [], []))

    def test_totals_row_found_by_label_not_position(self):
        rows = [["49 of 51", "CHAN PARK TOTALS"], TOTALS,
                ["5 of 6", "▸ TEAM A"], ["1", "Some Rep"]]
        self.assertIs(BX.totals_row(rows), TOTALS)
        self.assertIsNone(BX.totals_row([["1", "Some Rep"]]))


if __name__ == "__main__":
    unittest.main()

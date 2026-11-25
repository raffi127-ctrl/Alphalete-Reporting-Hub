"""Nico's three check panels .

  python -m unittest automations.nico_roster_check.test_panels
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.nico_roster_check import panels as P

WK = dt.date(2026, 11, 28)


def rc(week, status, camp, name, gone=""):
    r = [week, status, "", camp, name] + [""] * 9
    r[13] = gone
    return r


ROLL = [["ow"], ["Week Ending"],
        rc("11.29", "New Start", "Verizon", "Hal Lima"),
        rc("11.29", "Terminated", "Verizon", "Cy India", "11/23/2026"),
        rc("11.22", "Active", "Verizon", "Ed Juliet"),
        rc("10.4", "Active", "Verizon", "Will Hotel"),
        rc("10.4", "Active", "Verizon", "Idle Person"),
        rc("6.28", "Terminated", "Verizon", "Gil Echo"),
        rc("", "Active", "Verizon", "Gil Echo"),                     # Active beats the undated row
        rc("4.26", "Terminated", "B2B", "Jo Golf", "6/19/2026"),
        rc("9.6", "Active", "Verizon", "Jo Golf"),                 # Verizon beats the old AT&T row
        rc("10.25", "Terminated", "Verizon", "Joe Mike", "11/18/2026"),
        rc("11.8", "Active", "Verizon", "Jay Mid Foxtrot"),
        rc("4.26", "Active", "Verizon", "Nico Murrugarra"),
        rc("4.26", "Active", "NDS", "Ed Kilo")]
BOARD = [["WE", "11.29"], ["#", "REP", "Current Week", "Last Wk", "Campaign", "Field Status"],
         ["1", "Ed Juliet", "0", "0", "Verizon", "2nd Wk"],
         ["2", "Cy India", "0", "0", "Verizon", "3rd Wk"],
         ["3", "Will Hotel", "0", "11", "Verizon", "32nd Wk"],
         ["4", "Idle Person", "0", "0", "Verizon", "9th Wk"],
         ["5", "Gil Echo", "0", "0", "Verizon", "23rd Wk"],
         ["6", "Jay Mid Foxtrot", "3", "0", "Verizon", "4th Wk"],
         ["7", "Nico Murrugarra", "0", "0", "Verizon", "32nd Wk"],
         ["", "Verizon", "13", "127", "", ""], ["9", "Not A Rep", "", "", "", "3rd Wk"]]
LOG = [["Rep", "Order Date", "Order #", "Type", "Line Status"],
       ["Jay Mid Foxtrot", "11/23/2026", "A9", "Port", "Submitted"],      # after the Sunday
       ["Jay Mid Foxtrot", "11/14/2026", "A1", "Port", "Active"],
       ["Jay Mid Foxtrot", "11/14/2026", "A1", "Port", "Active"],
       ["Jay Mid Foxtrot", "11/13/2026", "A2", "Port", "Cancelled"]]
TAB = [["Pick"], [], ["Rep", "Brought In"], ["William Hotel", "$815.00"], ["Gil Echo", "$2,435.00"],
       ["Jay Mid Foxtrot", "$1,440.00"], ["Jo Golf", "$2,700.00"], ["Joe Mike", "$380.00"],
       ["TOTAL", "$7,770.00"], ["Reps", "$4,690.00"]]
EARLIER = [[[""] * 6 + ["Jay Mid Foxtrot", "", "", "Training Bonus — training bonus #1 and #2",
                        "added to this check: 800.00"]]]


class Panels(unittest.TestCase):
    def build(self):
        return P.build(WK, P.tab_reps(TAB), P.roll_call_people(ROLL), P.board_field_weeks(BOARD), LOG, EARLIER)

    def test_the_three_panels(self):
        got = self.build()
        self.assertEqual(got["norev"], ["Idle Person"])             # not 2nd wk, owner, NDS, gone or paid
        self.assertEqual(got["revnot"], [("Joe Mike", 380.0)])
        self.assertEqual(got["fs"], [("Jay Mid Foxtrot", 4, 1, 2, "#1 and #2")])

    def test_board_stops_at_the_totals_row(self):
        self.assertNotIn("Not A Rep", P.board_field_weeks(BOARD))

    def test_rows_and_old_block_round_trip(self):
        rows = P.rows_for(self.build())
        self.assertEqual(rows[0], ["ACTIVE REPS - NO REVENUE", "", "REVENUE - NOT ACTIVE", ""])
        grid = [["x"], ["y"], []] + rows + [[], ["below"]]
        s, e = P.old_block(grid)
        self.assertEqual((s, grid[e][0]), (3, "Jay Mid Foxtrot"))

    def test_nothing_reads_none(self):
        rows = P.rows_for({"norev": [], "revnot": [], "fs": []})
        self.assertEqual(rows[1], ["None", "", "None", ""])
        self.assertEqual(rows[-1][0], "None")

    def test_bonus_without_a_number_then_second(self):
        g = [[[""] * 6 + ["Bee November", "", "", "Training Bonus — training bonus"]],
             [[""] * 6 + ["Bee November", "", "", "Training Bonus — 2nd training bonus"]]]
        self.assertEqual(P.tab_training_bonuses(g, ["Bee November"]), {"Bee November": "#1 and #2"})
        self.assertEqual(P.tab_training_bonuses(g[:1], ["Bee November"]), {"Bee November": "Yes (no # noted)"})

    def test_itemized_block_found_by_header_after_a_spacer_column(self):
        g = [["Rep", "Brought In", "Commission", "Profit/Loss", "Rate", "NPA's", "", "REP Name", "Sale Date",
              "Week", "Description", "Product"],
             [""] * 7 + ["Jay Mid Foxtrot", "", "", "Training Bonus \u2014 training bonus #1 and #2", ""]]
        self.assertEqual(P.itemized_columns(g), (7, 10))
        self.assertEqual(P.tab_training_bonuses([g], ["Jay Mid Foxtrot"]), {"Jay Mid Foxtrot": "#1 and #2"})


if __name__ == "__main__":
    unittest.main()

"""Sunday is the block with no next banner to stop at -- and it used to guess.

Every day block on the ICD sales board runs from its day name to the next one.
The LAST one had nothing to stop at, so `_day_blocks` ended it at `col + 9`: a
guess sized for the 8-column block. The Talk-To trio made the block 11 wide and
the guess cut Sunday off at 'AVG app per TT', losing Cx and the Roll Call --
for the one day no other block covers.
"""
import unittest

from automations.icd_sales_board import board_read as B


OLD = ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx", "Roll Call"]
NEW = ["Apps", "Int", "Int Up", "DTV", "NL", "TK",
       "Total Talk-To's", "% of TT's per knock", "AVG app per TT",
       "Cx", "Roll Call"]
DAYS = ["MON", "TUES", "WED", "THU", "FRI", "SAT", "SUN"]


def grid(block):
    """The real shape: row 1 banners, row 2 day-of-month, row 3 sub-headers."""
    banner = ["", "", "", "RUNNING WEEK TOTALS", "", ""]
    hdr = ["#", "", "Rep", "APPS", "INT", "NL"]
    nums = ["", "", "", "", "", ""]
    for i, day in enumerate(DAYS):
        banner += [day] + [""] * (len(block) - 1)
        hdr += list(block)
        nums += [str(7 + i)] + [""] * (len(block) - 1)
    banner += ["Trainer", "Team"]
    hdr += ["", ""]
    nums += ["", ""]
    return [banner, nums, hdr]


class SundayBlock(unittest.TestCase):
    def blocks(self, block):
        return {b.day: b for b in B._day_blocks(grid(block), 3)}

    def test_old_layout_unchanged(self):
        b = self.blocks(OLD)["Sunday"]
        self.assertEqual([m for m, _ in b.measures],
                         ["Apps", "Int", "Int Up", "DTV", "NL", "TK", "Cx"])
        self.assertTrue(b.roll_call_col)

    def test_sunday_keeps_cx_and_roll_call_when_wider(self):
        b = self.blocks(NEW)["Sunday"]
        names = [m for m, _ in b.measures]
        self.assertIn("Cx", names)
        self.assertTrue(b.roll_call_col)

    def test_sunday_matches_the_other_days(self):
        """Whatever Saturday parses, Sunday parses -- that is the invariant the
        `col + 9` guess broke."""
        got = self.blocks(NEW)
        self.assertEqual([m for m, _ in got["Sunday"].measures],
                         [m for m, _ in got["Saturday"].measures])

    def test_all_seven_days_are_read(self):
        self.assertEqual(len(self.blocks(NEW)), 7)

    def test_daynum_still_comes_off_the_row_under_the_banner(self):
        self.assertEqual(self.blocks(NEW)["Sunday"].daynum, "13")

    def test_attribute_columns_are_not_swallowed_into_sunday(self):
        cols = [c for _, c in self.blocks(NEW)["Sunday"].measures]
        banner = grid(NEW)[0]
        self.assertTrue(all(banner[c - 1] != "Trainer" for c in cols))


if __name__ == "__main__":
    unittest.main()

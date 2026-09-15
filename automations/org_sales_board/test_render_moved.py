"""The draft's images must be cut from the layout the tab has WHEN they are
exported (2026-09-15: 4 rows deleted mid-render cut every bottom ORG box)."""
import unittest

from automations.org_sales_board import screenshot_email as se


def _grid(pad: int):
    """An ALPHALETE ORG leaderboard naming the org heads (the bottom boxes are
    only kept for heads on it), `pad` blank rows, then the two ORG boxes."""
    g = [["Title", ""],
         ["ALPHALETE ORG", ""],
         ["1", "Carlos Hidalgo"],
         ["2", "Colten Wright"],
         ["", ""]]
    g += [["", ""] for _ in range(pad)]
    for org in ("CARLOS", "COLTEN"):
        g += [["", f"{org} ORG - Current vs Prior Weeks"],
              ["", "", "Monday"],
              ["", "Sales - This Week"],
              ["", "vs Prior Week"],
              ["", "vs 4 WeekAVG"],
              ["", "Sales (Last Week)"],
              ["", "Sales ( 4 Week AVG)"],
              ["", ""]]
    return g


class RangesMoved(unittest.TestCase):
    def _ranges(self, pad):
        return [("botorg_carlo", f"A{pad + 1}:J{pad + 7}"),
                ("botorg_colten", f"A{pad + 9}:J{pad + 15}")]

    def test_same_layout_is_not_a_move(self):
        self.assertEqual(se.ranges_moved(self._ranges(10), self._ranges(10)), [])

    def test_rows_deleted_above_are_caught(self):
        self.assertEqual(se.ranges_moved(self._ranges(14), self._ranges(10)),
                         ["botorg_carlo", "botorg_colten"])

    def test_a_section_that_appears_or_goes_counts(self):
        before = self._ranges(10)
        self.assertEqual(se.ranges_moved(before, before[:1]), ["botorg_colten"])
        self.assertEqual(se.ranges_moved(before[:1], before), ["botorg_colten"])

    def test_the_same_boxes_four_rows_higher_are_a_move(self):
        """What happened 2026-09-15: the ranges read before the deletion
        (lower) no longer match the tab after it (4 rows higher)."""
        before = se._bottom_org_ranges(_grid(14), start=1)
        after = se._bottom_org_ranges(_grid(10), start=1)
        self.assertEqual(after, [("botorg_carlo", "A16:J22"),
                                 ("botorg_colten", "A24:J30")])
        self.assertEqual(before, [("botorg_carlo", "A20:J26"),
                                  ("botorg_colten", "A28:J34")])
        self.assertEqual(se.ranges_moved(before, after),
                         ["botorg_carlo", "botorg_colten"])


if __name__ == "__main__":
    unittest.main()

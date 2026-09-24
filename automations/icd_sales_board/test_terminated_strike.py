"""A terminated rep keeps their row and loses their name to a line."""
import unittest

from automations.icd_sales_board import site as S

GROUPS = [("Week", [("Apps", "Apps", "wk", True)])]


def html(rows):
    return S._grouped_board(rows, GROUPS)


class StrikeTests(unittest.TestCase):
    def test_a_terminated_rep_is_struck_through(self):
        out = html([{"Rep": "Jane Doe", "Tenure": "5th wk+",
                     "Status": "Terminated", "Apps": 3}])
        self.assertIn("line-through", out)
        self.assertIn("Jane Doe", out)

    def test_an_active_rep_is_not(self):
        out = html([{"Rep": "Jane Doe", "Tenure": "5th wk+",
                     "Status": "Active", "Apps": 3}])
        self.assertNotIn("line-through", out)

    def test_the_status_is_read_loosely(self):
        for v in ("terminated", " Terminated ", "TERMINATED"):
            self.assertIn("line-through",
                          html([{"Rep": "X", "Status": v, "Apps": 1}]), v)

    def test_a_row_with_no_status_is_not_struck(self):
        # The knocks board and the TOTALS row carry no Status.
        self.assertNotIn("line-through", html([{"Rep": "X", "Apps": 1}]))
        self.assertNotIn("line-through",
                         html([{"Rep": S.TOTALS_LABEL, "Apps": 9}]))

    def test_their_production_still_shows(self):
        # A sale landing after someone was marked gone is exactly the case to
        # SEE. The strike marks the person, never the numbers.
        out = html([{"Rep": "Jane Doe", "Status": "Terminated", "Apps": 7}])
        self.assertIn(">7<", out)


if __name__ == "__main__":
    unittest.main()

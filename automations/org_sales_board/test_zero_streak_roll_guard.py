"""The two-week zero rule must not read a board that has not rolled yet.

WHY (Eve, 2026-09-01, extending the rule to the Country Sales Board): these
boards roll on TUESDAY and the rule runs on Tuesday. Before the roll the newest
CLOSED week is still sitting in col C as the live formula, not as the literal
the rule is defined on — and `roster_remove` deletes rows, which moves the
absolute-row anchors the roll is about to rewrite. So the detector answers "has
this TAB rolled", off the tab's own newest week header, not off the calendar.
"""
import datetime as dt
import unittest

from automations.org_sales_board.zero_streak import unrolled_boxes


def box(owner, section, newest, n_weeks=3):
    """A read_boxes()-shaped box whose newest week column is `newest`."""
    weeks = [(newest - dt.timedelta(days=7 * i), 3 + i) for i in range(n_weeks)]
    return {"owner": owner, "section": section, "weeks": weeks, "reps": []}


class RollGuard(unittest.TestCase):
    live = dt.date(2026, 9, 6)          # the live week on Tue 2026-09-01

    def test_not_rolled_is_reported_with_the_week_it_is_stuck_on(self):
        """Tuesday morning, before the board's own roll: col C is still WE 08.30."""
        late = unrolled_boxes([box("ALPHALETE ORG", "Fiber - All Units",
                                   dt.date(2026, 8, 30))], self.live)
        self.assertEqual(late, {"ALPHALETE ORG/Fiber - All Units":
                                dt.date(2026, 8, 30)})

    def test_rolled_board_is_clean(self):
        """After the roll the newest column IS the live week — nothing to report."""
        self.assertEqual(
            unrolled_boxes([box("ALPHALETE ORG", "Fiber - All Units", self.live)],
                           self.live), {})

    def test_one_stale_box_is_enough(self):
        """A partial roll is still a board you must not read: the boxes that did
        roll would be judged on literals while the stale one is judged on a
        formula, and the run cannot tell you which answer you got."""
        late = unrolled_boxes(
            [box("ALPHALETE ORG", "Fiber - All Units", self.live),
             box("ALPHALETE ORG", "Fiber - New Internet", dt.date(2026, 8, 30))],
            self.live)
        self.assertEqual(list(late), ["ALPHALETE ORG/Fiber - New Internet"])

    def test_a_board_ahead_of_the_clock_is_not_flagged(self):
        """Only BEHIND is a problem. A tab that already opened next week (a hand
        roll, or a run from a machine an hour ahead) has its literals frozen,
        which is the state the rule wants — flagging it would block the pass for
        being too correct."""
        self.assertEqual(
            unrolled_boxes([box("ALPHALETE ORG", "Fiber - All Units",
                                self.live + dt.timedelta(days=7))], self.live), {})

    def test_a_box_with_no_week_columns_is_ignored(self):
        """`weeks` empty means the finder read a header with no parseable WE
        dates. That is a shape problem for read_boxes to report, not a roll
        verdict — guessing 'not rolled' here would be a permanent block."""
        self.assertEqual(
            unrolled_boxes([{"owner": "X", "section": "Y", "weeks": [],
                             "reps": []}], self.live), {})


if __name__ == "__main__":
    unittest.main()

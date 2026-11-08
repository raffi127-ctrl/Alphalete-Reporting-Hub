"""Pure rules of the Monday roll (week_roll.py). Run:
python -m unittest automations.alphalete_sales_board.test_week_roll"""
import datetime as dt
import unittest

from automations.alphalete_sales_board import week_roll as W

SPELLED = {2: "2nd Wk", 3: "3rd Wk", 4: "4th Wk", 5: "5th wk+"}


class StatusAndName(unittest.TestCase):
    def test_status_moves_one_week_in_the_boards_spelling(self):
        self.assertEqual(W.next_status("1st Wk", SPELLED), (1, "2nd Wk"))
        self.assertEqual(W.next_status("3rd Wk", SPELLED), (3, "4th Wk"))
        self.assertEqual(W.next_status("4th Wk", SPELLED), (4, "5th wk+"))

    def test_last_bucket_and_others_stay(self):
        for s in ("5th wk+", "RT", "Extra", ""):
            self.assertIsNone(W.next_status(s, SPELLED))

    def test_only_weeks_2_and_3_carry_the_tag(self):
        self.assertEqual(W.next_name("Tony Jones", 1), "Tony Jones (Wk 2)")
        self.assertEqual(W.next_name("Ana (Wk 2)", 2), "Ana (Wk 3)")
        self.assertEqual(W.next_name("Kayla Sprague (Wk 3)", 3), "Kayla Sprague")
        self.assertEqual(W.next_name("Grayson Holly", 4), "Grayson Holly")

    def test_base_name(self):
        self.assertEqual(W.base_name("Gabriel  (Gabe) Caldwell (Wk 2)"), "Gabriel  (Gabe) Caldwell")
        self.assertEqual(W.base_name("Bill Hirwa (NC)"), "Bill Hirwa (NC)")


class Tabs(unittest.TestCase):
    def test_names_and_padded_day(self):
        sun = dt.date(2026, 11, 1)
        self.assertEqual(W.tab_title(W.BOARD_PREFIX, sun), "Sales Board WE 11.1")
        titles = ["Sales Board WE 11.1", "Line Up WE 11.01", "Line Up WE 10.25"]
        self.assertEqual(W.find_tab(titles, W.LINEUP_PREFIX, sun), "Line Up WE 11.01")
        self.assertIsNone(W.find_tab(["SANDBOX — Sales Board WE 11.1"], W.BOARD_PREFIX, sun))

    def test_week_label(self):
        self.assertEqual(W.week_label(dt.date(2026, 10, 26)), "WE 10/26 - 11/1")


class StationsStep(unittest.TestCase):
    """Stations protected for the runners' login: the roll is not a failure."""

    def _run(self, boom):
        from unittest import mock
        with mock.patch.object(W, "point_stations", side_effect=boom) as pt:
            return W.stations_step(object(), "Line Up WE 11.1", "Line Up WE 11.8"), pt

    def test_protected_write_is_one_line_not_a_crash(self):
        notes, _ = self._run(RuntimeError("You are trying to edit a protected cell"))
        self.assertEqual(len(notes), 1)
        self.assertIn("Line Up WE 11.8", notes[0])

    def test_any_other_error_still_stops_the_run(self):
        with self.assertRaises(RuntimeError):
            self._run(RuntimeError("[500] backend"))

    def test_nothing_to_point_touches_nothing(self):
        from unittest import mock
        with mock.patch.object(W, "point_stations") as pt:
            self.assertEqual(W.stations_step(object(), None, "x"), [])
            self.assertEqual(W.stations_step(object(), "x", "x"), [])
        pt.assert_not_called()


class TheLineUpIsNotLucys(unittest.TestCase):
    """A person refreshes the Line Up on Fridays (Eve 2026-11-02)."""

    def _sheet(self, titles):
        from unittest import mock
        sh = mock.MagicMock()
        sh.fetch_sheet_metadata.return_value = {"sheets": [
            {"properties": {"title": t, "index": i}} for i, t in enumerate(titles)]}
        return sh

    def test_a_monday_copy_never_touches_the_line_up(self):
        from unittest import mock
        sh = self._sheet(["Sales Board WE 11.1", "Line Up WE 11.1"])
        board = {"terminated": [], "renames": {}, "missing": [], "history_line": ["WE"]}
        with mock.patch.object(W, "plan"),                 mock.patch.object(W, "roll_board", return_value=board) as rb,                 mock.patch.object(W, "point_stations") as pt:
            rc, notes = W.roll(sh, dt.date(2026, 11, 2), True)
        self.assertEqual((rc, notes), (0, []))
        rb.assert_called_once()
        pt.assert_not_called()
        sh.batch_update.assert_not_called()

    def test_a_board_already_made_points_stations_at_the_hand_made_line_up(self):
        from unittest import mock
        sh = self._sheet(["Line Up WE 11.08", "Sales Board WE 11.08",
                          "Sales Board WE 11.01", "Line Up WE 11.1"])
        with mock.patch.object(W, "point_stations", return_value=3) as pt:
            rc, _ = W.roll(sh, dt.date(2026, 11, 2), True)
        self.assertEqual(rc, 0)
        pt.assert_called_once_with(sh, "Line Up WE 11.1", "Line Up WE 11.08")


class OffBoardMark(unittest.TestCase):
    """'F' in Sunday Apps: off next week's board, not terminated (Raf 2026-11-08)."""

    def _plan(self, *reps):
        """reps = (name, Monday Apps, Sunday Apps)."""
        grid = [["", "", "", "MON", "", "", "SUN", "", ""],
                ["", "#", "WE 11/2 - 11/8", "Apps", "Int", "Roll Call",
                 "Apps", "Int", "Roll Call"]]
        for i, (name, mon, sun) in enumerate(reps, 1):
            grid.append(["", i, name, mon, "", "", sun, sun, ""])
        grid.append(["", "", "TOTALS", "", "", "", "", "", ""])
        return W.plan(grid, grid, grid, dt.date(2026, 11, 9))

    def test_f_comes_off_and_is_not_listed_as_terminated(self):
        p = self._plan(("Ana Stay", "X", ""), ("Bo Fired", "X", "F"), ("Cy Gone", "X", "T"))
        self.assertEqual(p["delete"], [4, 5])
        self.assertEqual(p["off_board"], ["Bo Fired"])
        self.assertEqual(p["terminated"], ["Cy Gone"])

    def test_lowercase_f_counts(self):
        self.assertEqual(self._plan(("Bo Fired", "X", " f "))["off_board"], ["Bo Fired"])

    def test_f_on_another_day_does_nothing(self):
        p = self._plan(("Ana Stay", "F", ""))
        self.assertEqual((p["delete"], p["off_board"]), ([], []))

    def test_terminated_reps_does_not_read_f_as_a_termination(self):
        from automations.terminated_reps import board
        self.assertNotIn("f", board.TERM_MARKS)
        self.assertIn("t", board.TERM_MARKS)


if __name__ == "__main__":
    unittest.main()

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


class LineUpNamesFollowTheBoard(unittest.TestCase):
    """Eve 2026-11-09: a rep gone '(Wk 2)' takes the dropdown's own name."""
    BOARD = ["Ana Griffin", "Bryson Knowles (Wk 2)", "Travis Smith (Wk 3)", "Alyssa Moreno ",
             "Sam Twin", "Sam Twin (Wk 2)", ""]

    def _grid(self, a="Bryson Knowles", b="Travis Smith (Wk 2)"):
        return [["", "Saturday", "", "", ""],
                ["#", "Car Ride Leader #1", "Car Ride #2", "New T?", "Notes"],
                ["1", a, b, "Bryson Knowles", "Bryson Knowles"],
                ["2", "Alyssa Moreno", "Sean (Kash's RT)", "", ""],
                ["3", "Sam Twin", "", "", ""],
                ["", "Rep names from Sales Board", "FFP", "", ""],
                ["", "Ana Griffin", "", "", ""]]

    def _all(self, grid):
        return {(r, c) for r in range(1, len(grid) + 1) for c in range(1, 6)}

    def test_names_take_the_boards_spelling(self):
        g = self._grid()
        cells = W.plan_lineup_names(g, self._all(g), self.BOARD)
        self.assertEqual(cells["B3"], "Bryson Knowles (Wk 2)")
        self.assertEqual(cells["C3"], "Travis Smith (Wk 3)")
        self.assertEqual(cells["B4"], "Alyssa Moreno ")   # the option's own space

    def test_only_car_ride_columns(self):
        g = self._grid()
        cells = W.plan_lineup_names(g, self._all(g), self.BOARD)
        self.assertNotIn("D3", cells)
        self.assertNotIn("E3", cells)

    def test_road_trips_and_blanks_stay(self):
        g = self._grid()
        cells = W.plan_lineup_names(g, self._all(g), self.BOARD)
        self.assertNotIn("C4", cells)
        self.assertNotIn("C5", cells)

    def test_a_right_name_is_not_rewritten(self):
        g = self._grid("Bryson Knowles (Wk 2)", "Travis Smith (Wk 3)")
        cells = W.plan_lineup_names(g, self._all(g), self.BOARD)
        self.assertNotIn("B3", cells)
        self.assertNotIn("C3", cells)

    def test_two_people_on_one_name_are_left_alone(self):
        g = self._grid()
        self.assertNotIn("B5", W.plan_lineup_names(g, self._all(g), self.BOARD))

    def test_a_cell_without_a_dropdown_is_left_alone(self):
        self.assertEqual(W.plan_lineup_names(self._grid(), set(), self.BOARD), {})

    def test_the_list_follows_the_new_board(self):
        f = self._grid()
        f[6][1] = "={'Sales Board WE 11.08'!$C4:$C77}"
        self.assertEqual(W.plan_pool_repoint(f, 6, "Sales Board WE 11.08", "Sales Board WE 11.15"),
                         {"B7": "={'Sales Board WE 11.15'!$C4:$C77}"})
        self.assertEqual(W.plan_pool_repoint(f, 6, "Sales Board WE 11.01", "Sales Board WE 11.15"), {})

    def test_a_broken_step_does_not_fail_the_roll(self):
        from unittest import mock
        sh = mock.Mock()
        sh.worksheet.side_effect = RuntimeError("protected")
        notes = W.lineup_step(sh, "Line Up WE 11.15", "a", "b", True)
        self.assertIn("not updated", notes[0])


class ClosedWeekSync(unittest.TestCase):
    """Eve 2026-11-09: transfers landed after the roll, 380 vs 375."""

    def _tabs(self):
        import copy
        banner = ["", "", "", "RUNNING WEEK TOTALS", "", "LAST WEEK'S TOTALS", ""]
        sub = ["", "#", "WE x", "Apps", "Int", "Apps", "Int"]
        old = [banner, sub, ["", 1, "Amjad (MJ) Malhas", 15, 10, 0, 0],
               ["", 2, "Ana (Wk 2)", 5, 3, 0, 0], ["", 3, "Gone", 1, 1, 0, 0],
               ["", "", "TOTALS", 21, 14, 9, 9], ["", "", "", "", "", "", ""]]
        new = [banner, sub, ["", 1, "Amjad (MJ) Malhas", 0, 0, 12, 6],
               ["", 2, "Ana (Wk 3)", 0, 0, 5, 3], ["", 3, "New Rep", 0, 0, 0, 0],
               ["", "", "TOTALS", 0, 0, 18, 10], ["", "", "", "", "", "", ""],
               ["", "", "WE 11/2 - 11/8", 18, 10, 9, 9],
               ["", "", "WE 10/26 - 11/1", 9, 9, 7, 7]]
        return old, new, copy.deepcopy(new)

    def _plan(self, old, new, formulas):
        from unittest import mock
        lay = mock.Mock(name_col=3, day_row=1, sub_row=2, last=5)
        with mock.patch.object(W.K, "layout", lambda v: lay), \
                mock.patch.object(W.K, "block_rows", lambda v: (3, 5)):
            return W.plan_closed_week_sync(old, old, new, formulas, new, dt.date(2026, 11, 2))

    def test_changed_numbers_only(self):
        cells, apps = self._plan(*self._tabs())
        self.assertEqual(cells["F3"], 15)      # Amjad's Last Week apps
        self.assertEqual(cells["G3"], 10)
        self.assertNotIn("F4", cells)          # Ana already agrees, tag ignored
        self.assertEqual(cells["F6"], 21)      # TOTALS
        self.assertEqual(cells["D8"], 21)      # history line
        self.assertEqual(apps, (18, 21))

    def test_older_history_and_formulas_stay(self):
        old, new, formulas = self._tabs()
        formulas[2][5] = "=SUM(y)"
        cells, _ = self._plan(old, new, formulas)
        self.assertNotIn("F3", cells)
        self.assertFalse([a for a in cells if a.endswith("9")])

    def test_a_rep_on_one_tab_only_is_left_alone(self):
        cells, _ = self._plan(*self._tabs())
        self.assertNotIn("F5", cells)

    def test_a_name_twice_is_left_alone(self):
        old, new, formulas = self._tabs()
        old[3][2] = "Amjad (MJ) Malhas"
        cells, _ = self._plan(old, new, formulas)
        self.assertNotIn("F3", cells)

    def test_agreeing_tabs_write_nothing(self):
        old, new, formulas = self._tabs()
        for r in (2, 3):
            new[r][5:7] = old[r][3:5]
        new[5][5:7] = old[5][3:5]
        new[7][3:] = old[5][3:]
        cells, apps = self._plan(old, new, list(new))
        self.assertEqual(cells, {})
        self.assertIsNone(apps)


if __name__ == "__main__":
    unittest.main()

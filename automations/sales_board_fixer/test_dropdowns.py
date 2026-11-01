"""Every row of a dropdown column has the dropdown (Raf + Eve 2026-11-01)."""
from __future__ import annotations

import unittest

from automations.sales_board_fixer import checks as K

LIST = {"condition": {"type": "ONE_OF_LIST", "values": [
    {"userEnteredValue": "1st Wk"}, {"userEnteredValue": "2nd Wk"},
    {"userEnteredValue": "Extra"}]}, "strict": True, "showCustomUi": True}
OTHER = {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Yes"}]}}
STATUS = 5  # column E


def tab(reps, free=1):
    """reps: [(name, status text, rule)]; `free` blank rows, then TOTALS."""
    rows = [["", "", "", "MON", ""], [""] * 5, ["", "#", "Name", "Apps", "Status"]]
    rules = [[], [], []]
    for name, text, rule in reps:
        rows.append(["", "1", name, "0", text])
        rules.append([None, None, None, None, rule])
    for _ in range(free):
        rows.append(["", "", "", "", "Extra"])
        rules.append([None] * 5)
    rows.append(["", "", "TOTALS", "", ""])
    return rows, rules


def run(reps, free=1, fill_blank=False):
    rows, rules = tab(reps, free)
    return rows, K.check_dropdowns("Board", 7, rows, rules, fill_blank=fill_blank)


GOOD = [("Rep %d" % i, "2nd Wk", LIST) for i in range(6)]


class Dropdowns(unittest.TestCase):
    def test_a_typed_row_gets_the_columns_dropdown(self):
        _, found = run(GOOD + [("New Rep", "1st Wk", None)])
        self.assertEqual([(x.kind, x.where, x.name) for x in found],
                         [("dropdown_missing", "E10", "New Rep")])
        self.assertTrue(found[0].fixable)
        write = found[0].request["updateCells"]
        self.assertEqual(write["fields"], "dataValidation")
        self.assertEqual(write["rows"][0]["values"][0]["dataValidation"], LIST)
        self.assertEqual(write["range"]["startRowIndex"], 9)

    def test_nothing_to_do_when_every_row_has_it(self):
        self.assertEqual(run(GOOD, free=0)[1], [])

    def test_free_rows_only_on_request_and_never_totals(self):
        self.assertEqual(run(GOOD)[1], [])
        rows, found = run(GOOD, fill_blank=True)
        self.assertEqual([x.where for x in found], ["E10"])
        self.assertEqual(rows[9][2], "")

    def test_a_word_off_the_list_is_reported_not_written(self):
        _, found = run(GOOD + [("New Rep", "Veteran", None)])
        self.assertEqual(found[0].kind, "dropdown_value_off")
        self.assertFalse(found[0].fixable)

    def test_a_split_column_is_reported_once_and_left_alone(self):
        reps = [("Rep %d" % i, "Yes", OTHER if i < 3 else LIST) for i in range(6)]
        _, found = run(reps + [("New Rep", "", None)])
        self.assertEqual([x.kind for x in found], ["dropdown_mixed"])
        self.assertFalse(found[0].fixable)

    def test_a_different_list_on_one_row_comes_in_line(self):
        reps = [("Rep %d" % i, "2nd Wk", LIST) for i in range(12)]
        _, found = run(reps + [("Odd Rep", "2nd Wk", OTHER)])
        self.assertEqual([x.kind for x in found], ["dropdown_different"])
        self.assertTrue(found[0].fixable)

    def test_a_column_most_reps_dont_have_is_not_a_dropdown_column(self):
        reps = [("Rep %d" % i, "2nd Wk", LIST if i < 2 else None) for i in range(8)]
        self.assertEqual(run(reps)[1], [])


class SpareNames(unittest.TestCase):
    def test_a_placeholder_doesnt_vote_but_gets_the_dropdown(self):
        reps = [("Rep %d" % i, "2nd Wk", LIST) for i in range(6)]
        reps += [("ZZ EXTRA", "", None) for _ in range(8)]
        _, found = run(reps, free=0)
        self.assertEqual({x.kind for x in found}, {"dropdown_missing"})
        self.assertEqual(len(found), 8)


class FreeRowsGetTheFormat(unittest.TestCase):
    def test_borders_reach_the_free_rows(self):
        rows, _ = tab(GOOD)
        good = (("bottom", "SOLID", ""), ("top", "SOLID", ""))
        bad = good + (("right", "SOLID_MEDIUM", ""),)
        grid = [[], [], []] + [[None, None, None, None, good] for _ in GOOD]
        grid.append([None, None, None, None, bad])
        found = K.check_borders("Board", 7, rows, grid, fill_blank=True)
        self.assertEqual([x.where for x in found], ["E10"])
        write = found[0].request["updateCells"]
        self.assertEqual(write["fields"], "userEnteredFormat.borders")
        self.assertEqual(set(write["rows"][0]["values"][0]["userEnteredFormat"]["borders"]),
                         {"bottom", "top"})

    def test_a_column_with_no_title_between_two_titled_ones_counts(self):
        rows = [["", "", "", "MON", "", "TUE"], [""] * 6, ["", "#", "Name", "Apps", " ", "Apps"]]
        for i in range(6):
            rows.append(["", "1", "Rep %d" % i, "0", "x", "0"])
        rows.append(["", "", "", "0", "x", "0"])
        rows.append(["", "", "TOTALS", "", "", ""])
        good = ("Georgia", 10)
        fonts = [[], [], []] + [[None, None, None, None, good, None] for _ in range(6)]
        fonts.append([None, None, None, None, ("Arial", 10), None])
        found = K.check_fonts("Board", 7, rows, fonts, fill_blank=True)
        self.assertEqual([x.where for x in found], ["E10"])

    def test_fonts_reach_the_free_rows_only_on_request(self):
        rows, _ = tab(GOOD)
        fonts = [[], [], []] + [[None, None, None, None, ("Georgia", 12)] for _ in GOOD]
        fonts.append([None, None, None, None, ("Arial", 10)])
        self.assertEqual(K.check_fonts("Board", 7, rows, fonts), [])
        found = K.check_fonts("Board", 7, rows, fonts, fill_blank=True)
        self.assertEqual([(x.where, x.after) for x in found], [("E10", "Georgia 12")])


if __name__ == "__main__":
    unittest.main()

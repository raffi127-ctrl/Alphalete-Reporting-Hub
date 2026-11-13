"""Direct Deposit went checkbox -> dropdown (Maud 2026-11-13): blank cells keep
the old checkbox paint, and a TRUE was left behind."""
from __future__ import annotations

import json
import unittest

from automations.sales_board_fixer import checks as K

DD = {"condition": {"type": "ONE_OF_LIST", "values": [
    {"userEnteredValue": "Completed"}, {"userEnteredValue": "Submitted"},
    {"userEnteredValue": "Can't get DD"}, {"userEnteredValue": "Pending"}]},
      "strict": True, "showCustomUi": True}
ORANGE = json.dumps({"red": 1, "green": 0.6}, sort_keys=True)
GREEN = json.dumps({"green": 1}, sort_keys=True)


def tab(cells):
    """cells: [(text, paint)] one rep each, column E = Direct Deposit."""
    rows = [["", "", "", "MON", "Direct Deposit"], [""] * 5, ["", "#", "Name", "Apps", ""]]
    rules, bgs = [[], [], []], [[], [], []]
    for i, (text, paint) in enumerate(cells):
        rows.append(["", str(i + 1), "Rep %d" % i, "0", text])
        rules.append([None] * 4 + [DD])
        bgs.append([""] * 4 + [paint])
    rows.append(["", "", "TOTALS", "", ""])
    return rows, rules, bgs


class BlankPaint(unittest.TestCase):
    def test_an_emptied_cell_with_old_paint_goes_white(self):
        rows, rules, bgs = tab([("Completed", GREEN)] * 6 + [("", "")] * 4 + [("", ORANGE)])
        found = K.check_dropdown_blank_paint("t", 1, rows, rules, bgs)
        self.assertEqual([(x.kind, x.where) for x in found], [("dropdown_blank_paint", "E14")])
        req = found[0].request["updateCells"]
        self.assertEqual(req["fields"], "userEnteredFormat.backgroundColor")
        self.assertEqual(req["rows"][0]["values"][0]["userEnteredFormat"], {})

    def test_paint_under_a_value_is_left_alone(self):
        rows, rules, bgs = tab([("Submitted", ORANGE)] * 3 + [("", "")] * 4)
        self.assertEqual(K.check_dropdown_blank_paint("t", 1, rows, rules, bgs), [])

    def test_a_column_painted_on_purpose_is_not_touched(self):
        rows, rules, bgs = tab([("", ORANGE)] * 5 + [("", "")])
        self.assertEqual(K.check_dropdown_blank_paint("t", 1, rows, rules, bgs), [])


class CheckboxLeftover(unittest.TestCase):
    def test_true_becomes_completed(self):
        rows, rules, _ = tab([("Completed", "")] * 5 + [("TRUE", "")])
        found = K.check_checkbox_leftovers("t", rows, rules)
        self.assertEqual([(x.where, x.value) for x in found], [("E9", "Completed")])

    def test_a_real_checkbox_column_keeps_true(self):
        rows, rules, _ = tab([("TRUE", "")] * 3)
        for r in rules[3:]:
            r[4] = {"condition": {"type": "BOOLEAN"}}
        self.assertEqual(K.check_checkbox_leftovers("t", rows, rules), [])


if __name__ == "__main__":
    unittest.main()

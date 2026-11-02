"""Colors one column over, rules stuck on single cells, bold from a rule, a mixed column."""
import json
import unittest

from automations.sales_board_fixer import checks as K, run as R

PINK, GREEN, BLUE = (json.dumps({"red": x}, sort_keys=True) for x in (0.1, 0.2, 0.3))


def board(n=8):
    rows = [["", "", "", "MON", "", "", "", "", ""], [""] * 9,
            ["", "#", "Name", "Apps", "Int", "Up", "DTV", "NL", "Cx"]]
    for i in range(n):
        rows.append(["", "1", "Rep %d" % i] + ["0"] * 6)
    rows.append(["", "", "TOTALS"] + [""] * 6)
    return rows


NORMAL = [None, None, None, "", PINK, GREEN, BLUE, "", ""]
HEAD = [[], [], []]


class BackgroundShift(unittest.TestCase):
    def test_a_row_one_column_over_goes_back(self):
        shifted = [None, None, None, PINK, GREEN, BLUE, "", "", ""]
        grid = HEAD + [list(NORMAL) for _ in range(7)] + [shifted]
        found = K.check_background_shift("B", 7, board(), grid)
        self.assertEqual([x.where for x in found], ["D11", "E11", "F11", "G11"])
        self.assertEqual(found[0].request["updateCells"]["rows"][0]["values"][0]["userEnteredFormat"], {})
        self.assertEqual(found[1].request["updateCells"]["fields"], "userEnteredFormat.backgroundColor")

    def test_one_painted_cell_is_left_alone(self):
        painted = list(NORMAL)
        painted[4] = GREEN
        grid = HEAD + [list(NORMAL) for _ in range(7)] + [painted]
        self.assertEqual(K.check_background_shift("B", 7, board(), grid), [])


def rule(*ranges, type_="NUMBER_EQ"):
    return {"ranges": [{"startRowIndex": r0 - 1, "endRowIndex": r1,
                        "startColumnIndex": c0, "endColumnIndex": c1}
                       for r0, r1, c0, c1 in ranges],
            "booleanRule": {"condition": {"type": type_, "values": [{"userEnteredValue": "0"}]},
                            "format": {}}}


class StrayCells(unittest.TestCase):
    def strays(self, r):
        return [x for x in K.check_conditional("B", 7, [r], 40, block=(4, 95))
                if x.kind == "cf_stray_cell"]

    def test_a_single_cell_comes_off_the_rule(self):
        found = self.strays(rule((4, 95, 4, 9), (60, 60, 30, 31)))
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0].request["updateConditionalFormatRule"]["rule"]["ranges"]), 1)

    def test_a_column_the_rule_really_covers_stays(self):
        self.assertEqual(self.strays(rule((4, 50, 4, 5), (60, 60, 4, 5))), [])

    def test_formula_rules_are_not_touched(self):
        self.assertEqual(self.strays(rule((4, 95, 4, 9), (60, 60, 30, 31), type_="CUSTOM_FORMULA")), [])


class BoldFromARule(unittest.TestCase):
    def test_only_the_given_bold_counts(self):
        cell = {"effectiveFormat": {"textFormat": {"bold": True}, "horizontalAlignment": "CENTER"}}
        self.assertEqual(R._style(cell), (False, "CENTER"))


class MixedColumn(unittest.TestCase):
    def test_bold_and_centering_are_voted_apart(self):
        center = (False, "CENTER")
        grid = HEAD + [[None] * 3 + [center] * 6 for _ in range(10)]
        for i in range(3):
            grid[3 + i][3] = (False, None)
            grid[6 + i][3] = (True, "CENTER")
        found = K.check_styles("B", 7, board(10), grid)
        self.assertEqual(sorted(x.where for x in found), ["D4", "D5", "D6", "D7", "D8", "D9"])
        self.assertEqual({x.after for x in found}, {"center"})

    def test_a_column_with_no_clear_look_is_left_alone(self):
        grid = HEAD + [[None] * 3 + [(False, "CENTER")] * 6 for _ in range(10)]
        for i in range(5):
            grid[3 + i][3] = (False, None)
        self.assertEqual(K.check_styles("B", 7, board(10), grid), [])


if __name__ == "__main__":
    unittest.main()

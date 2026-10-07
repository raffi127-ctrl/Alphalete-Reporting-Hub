import unittest

from automations.sales_board_fixer import checks as K


def board(rows):
    """Tiny board: row 1 banners, row 3 sub-headers, reps from row 4, TOTALS last.
    Columns: A rank-ish, B #, C name, D Total (formula), E MON Apps, F Int, G Roll Call."""
    hdr1 = ["", "", "", "", "MON", "", ""]
    hdr3 = ["", "#", "Name", "Total Apps", "Apps", "Int", "Roll Call"]
    vals, fx = [hdr1, [""] * 7, hdr3], [hdr1, [""] * 7, hdr3]
    for i, (name, d, intv, rc) in enumerate(rows):
        r = 4 + i
        vals.append(["", str(i + 1), name, "0", "0", intv, rc])
        fx.append(["", "=B%d+1" % (r - 1) if i else 1, name, d % {"r": r}, "=F%d" % r, intv, rc])
    vals.append(["", "", "TOTALS", "", "", "", ""])
    fx.append(["", "", "TOTALS", "", "", "", ""])
    return vals, fx


GOOD = "=SUM(E%(r)d)"


class Formulas(unittest.TestCase):
    def test_x_typed_over_formula_gets_formula_back(self):
        rows = [("Rep %d" % i, GOOD, "1", "Here") for i in range(8)]
        rows[3] = ("Rep 3", "X", "1", "Here")
        v, f = board(rows)
        found = K.check_formulas("t", v, f)
        x = [y for y in found if y.where == "D7"]
        self.assertEqual(len(x), 1)
        self.assertEqual(x[0].kind, "x_over_formula")
        self.assertEqual(x[0].value, "=SUM(E7)")

    def test_first_rank_cell_is_not_pointed_at_the_header(self):
        v, f = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(8)])
        self.assertFalse([y for y in K.check_formulas("t", v, f) if y.where == "B4"])

    def test_no_majority_no_finding(self):
        rows = [("Rep %d" % i, GOOD if i % 2 else "5", "1", "Here") for i in range(8)]
        v, f = board(rows)
        self.assertFalse([y for y in K.check_formulas("t", v, f) if y.where.startswith("D")])

    def test_string_literals_are_not_renumbered(self):
        self.assertEqual(K.normalize('=IF(A5="1st Wk",B5,$C$4)', 5),
                         '=IF(A{+0}="1st Wk",B{+0},$C$4)')
        self.assertEqual(K.denormalize("=A{+0}+B{-1}", 9), "=A9+B8")


class RollCall(unittest.TestCase):
    def test_x_with_blank_roll_call_fills_off_and_keeps_x(self):
        rows = [("Rep %d" % i, GOOD, "1", "Here") for i in range(6)]
        rows[2] = ("Rep 2", GOOD, "x", "")
        rows[4] = ("Rep 4", GOOD, "T", "")
        rows[5] = ("Rep 5", GOOD, "X", "Off")       # already set: nothing to do
        v, _ = board(rows)
        found = {y.where: y.value for y in K.check_roll_call("t", v)}
        self.assertEqual(found, {"G6": "Off", "G8": "T"})


class Fonts(unittest.TestCase):
    def test_odd_font_gets_column_majority_via_update_cells(self):
        v, _ = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(8)])
        fonts = [[None] * 7 for _ in range(3)]
        for i in range(8):
            fonts.append([("Arial", 14)] + [("Georgia", 12)] * 6)
        fonts[3 + 2][5] = ("Arial", 10)
        found = K.check_fonts("t", 7, v, fonts)
        self.assertEqual([y.where for y in found], ["F6"])          # col A skipped
        self.assertIn("updateCells", found[0].request)


class Notes(unittest.TestCase):
    def test_note_says_what_changed_and_keeps_an_existing_note(self):
        rows = [("Rep %d" % i, GOOD, "1", "Here") for i in range(6)]
        rows[2] = ("Rep 2", GOOD, "x", "")
        v, _ = board(rows)
        found = K.check_roll_call("t", v)
        notes = [[""] * 7 for _ in range(12)]
        notes[5][6] = "Raf: call him"
        reqs = K.note_requests(found, 7, notes, "10/07")
        self.assertEqual(len(reqs), 1)
        text = reqs[0]["updateCells"]["rows"][0]["values"][0]["note"]
        self.assertTrue(text.startswith("Raf: call him\n\nLucy fixed this (10/07):"))
        self.assertIn("Now: Off.", text)
        self.assertEqual(reqs[0]["updateCells"]["fields"], "note")

    def test_rule_deletes_get_no_note(self):
        rule = Conditional.rule(None, "=COUNTIF(#REF!,A4)>0")
        found = K.check_conditional("t", 7, [rule], ncols=36)
        self.assertEqual(K.note_requests(found, 7, [], "10/07"), [])


class Conditional(unittest.TestCase):
    def rule(self, formula, rows=(3, 40), cols=(2, 5), color=1):
        return {"ranges": [{"sheetId": 7, "startRowIndex": rows[0], "endRowIndex": rows[1],
                            "startColumnIndex": cols[0], "endColumnIndex": cols[1]}],
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                              "values": [{"userEnteredValue": formula}]},
                                "format": {"backgroundColor": {"red": color}}}}

    def test_dead_rules_deleted_highest_index_first(self):
        rules = [self.rule("=A4>0"), self.rule("=COUNTIF(#REF!,A4)>0"),
                 self.rule("=EA46=\"RT\""), self.rule("=A4>0")]
        found = K.check_conditional("t", 7, rules, ncols=36)
        self.assertEqual([y.request["deleteConditionalFormatRule"]["index"] for y in found],
                         [3, 2, 1])
        self.assertEqual([y.kind for y in found], ["cf_duplicate", "cf_foreign", "cf_broken"])

    def test_literal_text_is_not_a_column(self):
        self.assertFalse(K.check_conditional("t", 7, [self.rule('=$B4="ZZZ1"')], ncols=10))


if __name__ == "__main__":
    unittest.main()

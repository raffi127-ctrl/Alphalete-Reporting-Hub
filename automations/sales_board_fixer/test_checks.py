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


def owner_board(n_reps, blanks=6):
    """An owner's All-in-One board: names in col B, 'TUE' banner, 'TOTAL'
    label, blank numbered template rows under the reps.
    Columns: A #, B name, C MON Apps, D Int, E Roll Call, F TUE Apps, G Int, H Roll Call."""
    hdr1 = ["x", "Office", "MON", "", "", "TUE", "", ""]
    hdr3 = ["#", "WE 6/8 - 6/14", "Apps", "Int", "Roll Call", "Apps", "Int", "Roll Call"]
    vals = [hdr1, [""] * 8, hdr3]
    for i in range(n_reps + blanks):
        name = "Rep %d" % i if i < n_reps else ""
        vals.append([str(i + 1), name, "0", "", "", "0", "", ""])
    vals.append(["", "TOTAL", "0", "", "", "0", "", ""])
    vals.append(["", "Team 1", "0", "", "", "", "", ""])     # teams box below
    return vals


class OwnerLayout(unittest.TestCase):
    def test_names_in_col_b_total_label_and_tue(self):
        v = owner_board(6)
        lay = K.layout(v)
        self.assertEqual((lay.name_col, lay.day_row, lay.sub_row, lay.last), (2, 1, 3, 15))
        self.assertTrue(K.is_board(v))
        self.assertEqual(sorted(K.roll_call_cols(v)), ["Monday", "Tuesday"])

    def test_roll_call_names_come_from_col_b(self):
        v = owner_board(6)
        v[5][6] = "X"                                   # Rep 2, TUE Int
        found = K.check_roll_call("t", v)
        self.assertEqual([(y.where, y.name, y.value) for y in found], [("H6", "Rep 2", "Off")])

    def test_blank_template_rows_dont_set_the_format(self):
        v = owner_board(6, blanks=20)
        fmts = [[None] * 8 for _ in range(3)]
        for r in range(26):
            fmts.append([("NUMBER", "0")] * 8 if r < 6 else [("", "")] * 8)
        self.assertEqual(K.check_number_formats("t", 7, v, fmts), [])

    def test_hand_numbered_rank_and_spacer_rows_are_left_alone(self):
        v = owner_board(8, blanks=0)
        f = [list(r) for r in v]
        for r in range(4, 12):
            f[r - 1][2] = "=D%d+G%d" % (r, r)        # Apps formula
            f[r - 1][0] = "=A%d+1" % (r - 1) if r > 4 else "1"
        f[6][0] = "3"                                 # rank typed by hand
        v[8][1] = ""                                  # row 9: spacer, no rep
        f[8][1] = ""
        f[8][2] = ""
        self.assertEqual([y.where for y in K.check_formulas("t", v, f)], [])

    def test_line_up_is_not_a_board(self):
        self.assertFalse(K.is_board([["Trainer", "New Start"], ["Ana", "Bo"]]))


class OwnerTabs(unittest.TestCase):
    def test_week_dated_side_tabs_only_for_the_picked_week(self):
        from automations.sales_board_fixer.run import side_tabs, BOARD_NAME
        visible = ["GYR/Lanes", "10.12", "10.12 Linep", "10.12 Stations", "Lanes",
                   "10.5", "10.5 Lineup", "10.5 Stations", "Territory Line Up"]
        self.assertTrue(BOARD_NAME.search("10.12"))
        self.assertFalse(BOARD_NAME.search("10.12 Stations"))
        self.assertEqual(side_tabs(visible, ["10.12"]),
                         ["10.12 Linep", "10.12 Stations", "Territory Line Up"])


class OwnerRepeats(unittest.TestCase):
    def test_eve_hears_on_the_third_day_in_a_row_only(self):
        import datetime as dt
        from automations.sales_board_fixer.run import repeats
        h, k = {}, ["Cody · Sales Board | D5 | missing_formula"]
        d = dt.date(2026, 10, 13)
        self.assertEqual(repeats(h, k, d), [])
        self.assertEqual(repeats(h, k, d + dt.timedelta(1)), [])
        self.assertEqual(repeats(h, k, d + dt.timedelta(2)), k)
        self.assertEqual(repeats(h, k, d + dt.timedelta(3)), [])   # once, not daily

    def test_a_skipped_day_starts_over(self):
        import datetime as dt
        from automations.sales_board_fixer.run import repeats
        h, k = {}, ["x"]
        d = dt.date(2026, 10, 13)
        repeats(h, k, d); repeats(h, k, d + dt.timedelta(2))
        self.assertEqual(repeats(h, k, d + dt.timedelta(3)), [])


if __name__ == "__main__":
    unittest.main()

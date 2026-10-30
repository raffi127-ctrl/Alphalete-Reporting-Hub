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


    def test_row_that_lost_bold_and_centering_gets_it_back(self):
        v, _ = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(8)])
        styles = [[None] * 7 for _ in range(3)]
        for i in range(8):
            styles.append([(False, None)] + [(True, "CENTER")] * 6)
        styles[3 + 4][4] = (False, "RIGHT")
        found = K.check_styles("t", 7, v, styles)
        self.assertEqual([y.where for y in found], ["E8"])
        fmt = found[0].request["updateCells"]["rows"][0]["values"][0]["userEnteredFormat"]
        self.assertEqual(fmt["horizontalAlignment"], "CENTER")
        self.assertTrue(fmt["textFormat"]["bold"])


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

    def test_last_weeks_lucy_notes_go_a_persons_note_stays(self):
        import datetime as dt
        notes = [["Raf: call him\n\nLucy fixed this (10/14):\n- x. Was: a. Now: b.",
                  "Lucy fixed this (10/20):\n- x.",
                  "Lucy (10/13): city from Blue Ink. Was: blank."]]
        reqs, kept = K.old_note_requests(7, notes, dt.date(2026, 10, 21))
        self.assertEqual(kept, [["Raf: call him", "Lucy fixed this (10/20):\n- x.", ""]])
        self.assertEqual(len(reqs), 2)
        _, kept = K.old_note_requests(7, [["Lucy fixed this (12/29):"]], dt.date(2027, 1, 6))
        self.assertEqual(kept, [[""]])                      # last year's, before Monday
        reqs, kept = K.old_note_requests(7, notes, dt.date(2026, 10, 21), every=True)
        self.assertEqual(kept, [["Raf: call him", "", ""]])  # our board: all of Lucy's go
        self.assertEqual(len(reqs), 3)

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

    def test_stray_self_count_deleted_on_purpose_one_kept(self):
        # Stations 10/26: C6:D6 counted $B$3:$F$38 (itself) -> Joseph struck
        grid = self.rule("=COUNTIF($B$4:$S$37, B4)>1", rows=(3, 37), cols=(1, 10))
        stray = self.rule("=COUNTIF($B$3:$F$38, C6) > 0", rows=(5, 6), cols=(2, 4), color=0.8)
        off = self.rule("=COUNTIF($B$44:$J$157, F44)>0", rows=(43, 157), cols=(5, 10), color=0.5)
        placed = self.rule("=COUNTIF($F$44:$J$157, B4)>0", rows=(3, 37), cols=(1, 10), color=0.3)
        found = K.check_conditional("t", 7, [grid, stray, off, placed], ncols=34)
        self.assertEqual([(y.kind, y.request["deleteConditionalFormatRule"]["index"])
                          for y in found], [("cf_self", 1)])

    def test_car_ride_strike_pasted_on_the_car_rides_goes(self):
        # Colten 10/28: Monday's pool rule also sat on E17:E21 -> names struck
        def piece(r0, r1, c0, c1):
            return {"sheetId": 7, "startRowIndex": r0, "endRowIndex": r1,
                    "startColumnIndex": c0, "endColumnIndex": c1}
        strike = {"textFormat": {"strikethrough": True}}
        mon = self.rule("=COUNTIF($D$3:$G$46, E17) > 0")
        mon["ranges"] = [piece(16, 21, 4, 5), piece(49, 84, 3, 7)]
        mon["booleanRule"]["format"] = strike
        tue = self.rule("=COUNTIF($L$3:$O$46, L50) > 0", rows=(49, 84), cols=(11, 15))
        tue["booleanRule"]["format"] = strike
        found = K.check_conditional("t", 7, [mon, tue], ncols=52)
        self.assertEqual([(y.kind, y.where, y.after) for y in found],
                         [("cf_strike_stray", "regla 0", "D50:G84")])
        new = found[0].request["updateConditionalFormatRule"]["rule"]
        self.assertEqual(new["booleanRule"]["condition"]["values"][0]["userEnteredValue"],
                         "=COUNTIF($D$3:$G$46, D50) > 0")
        self.assertEqual(new["booleanRule"]["format"], strike)

    def test_off_list_strike_above_its_list_stays(self):
        # ours, Stations: M5 struck when on the OFF list below -- not a pool
        off = self.rule("=COUNTIF($F$44:$H$157, M5)>0")
        off["ranges"] = [{"sheetId": 7, "startRowIndex": 4, "endRowIndex": 5,
                          "startColumnIndex": 12, "endColumnIndex": 13},
                         {"sheetId": 7, "startRowIndex": 43, "endRowIndex": 157,
                          "startColumnIndex": 1, "endColumnIndex": 10}]
        off["booleanRule"]["format"] = {"textFormat": {"strikethrough": True}}
        self.assertFalse(K.check_conditional("t", 7, [off], ncols=34))

    def test_literal_text_is_not_a_column(self):
        self.assertFalse(K.check_conditional("t", 7, [self.rule('=$B4="ZZZ1"')], ncols=10))

    def test_status_color_one_row_off_is_reanchored(self):
        # Jairo 10/29: names B4:B142 painted by =BL5="1st Wk" -> the row above
        shifted = self.rule('=BL5="1st Wk"', rows=(3, 142), cols=(1, 2))
        right = self.rule('=AZ4="2nd Wk"', rows=(3, 142), cols=(1, 2), color=0.5)
        below = self.rule('=BL5="RT"', rows=(40, 60), cols=(1, 2), color=0.3)  # not on row 4
        found = K.check_conditional("t", 7, [shifted, right, below], ncols=70, block=(4, 142))
        self.assertEqual([(y.kind, y.where, y.after) for y in found],
                         [("cf_row_shift", "regla 0", '=BL4="1st Wk"')])
        new = found[0].request["updateConditionalFormatRule"]["rule"]
        self.assertEqual(new["ranges"], shifted["ranges"])
        self.assertEqual(new["booleanRule"]["format"], shifted["booleanRule"]["format"])
        # without the rep block (Line Up / Stations) nothing is guessed
        self.assertFalse(K.check_conditional("t", 7, [shifted], ncols=70))


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

    def test_owner_roll_call_uses_the_boards_own_word(self):
        v = owner_board(6)
        for r in (3, 4, 5):                               # Rep 0..2 MON: X -> "OFF"
            v[r][3], v[r][4] = "X", "OFF"
        v[6][6] = "X"                                     # Rep 3 TUE: X, Roll Call blank
        v[7][6] = "T"                                     # Rep 4 TUE: T, never shown here
        found = {y.where: y.value for y in K.check_roll_call("t", v, learn=True)}
        self.assertEqual(found, {"H7": "OFF", "H8": None})   # T: reported, not guessed
        self.assertEqual(K.check_roll_call("t", v)[0].value, "Off")   # ours: fixed word

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

    def test_b2b_board_units_and_no_totals_label(self):
        # Eveliz's 'Sales Board Miami B2B': Units not Apps, totals row unlabeled
        v = [[" ", "", "MON", "", "", "", "", "TUE"],
             ["", "", "", "", "", "", "", ""],
             ["", "RANKING SALES BOARD", "Units", "INT", "AIR", "VOIP", "NL", "Units"],
             ["1", "Kenna Brito", "7.0", "", "1", "", "6", "8.0"],
             ["2", "ZZ EXTRA", "0.0", "", "", "", "", "0.0"],
             ["", "", "25.0", "", "", "", "", ""],
             ["", "Last Week", "", "", "", "", "", ""]]
        lay = K.layout(v)
        self.assertEqual((lay.name_col, lay.sub_row, lay.last), (2, 3, 5))
        self.assertTrue(K.is_board(v))

    def test_week_total_columns_between_names_and_mon(self):
        # Drew's 'Sales Board NDS': no TOTALS label, week totals in C..F before MON
        v = [[" ", "", "WEEK TOTALS", "", "", "", "MON", "Monday", "", "", ""],
             ["", "", "", "", "", "", "", "12", "", "", ""],
             ["", '"Results get Rewarded"', "Apps", "Cx Count", "NDS INT", "NDS NL",
              "Apps", "Cx Count", "NDS INT", "NDS NL", "Roll Call"],
             ["1", "Matthew Grant", "10.0", "4", "0", "10", "9.0", "3", "", "9", ""],
             ["2", "ZZ EXTRA", "0.0", "0", "0", "0", "0.0", "", "", "", ""],
             ["", "", "117.0", "57", "4", "113", "", "", "", "", ""],
             ["", "Reps in the Field", "12", "", "", "", "", "", "", "", ""]]
        lay = K.layout(v)
        self.assertEqual((lay.name_col, lay.sub_row, lay.last), (2, 3, 5))
        self.assertTrue(K.is_board(v))


class OwnerTabs(unittest.TestCase):
    def test_week_dated_side_tabs_only_for_the_picked_week(self):
        from automations.sales_board_fixer.run import side_tabs, BOARD_NAME
        visible = ["GYR/Lanes", "10.12", "10.12 Linep", "10.12 Stations", "Lanes",
                   "10.5", "10.5 Lineup", "10.5 Stations", "Territory Line Up"]
        self.assertTrue(BOARD_NAME.search("10.12"))
        self.assertFalse(BOARD_NAME.search("10.12 Stations"))
        self.assertEqual(side_tabs(visible, ["10.12"]),
                         ["10.12 Linep", "10.12 Stations", "Territory Line Up"])

    def test_this_weeks_dated_tab_beats_a_dead_leftmost_board(self):
        import datetime as dt
        from automations.sales_board_fixer.run import this_weeks_tab, BOARD_NAME
        visible = ["Fiber Sales Board", "10/12", "10/5", "9/28", "Line Up ", "Stations"]
        self.assertTrue(BOARD_NAME.search("10/12"))
        self.assertEqual(this_weeks_tab(visible, dt.date(2026, 10, 14)), "10/12")
        self.assertEqual(this_weeks_tab(visible, dt.date(2026, 10, 11)), "10/5")
        self.assertIsNone(this_weeks_tab(visible, dt.date(2026, 11, 20)))
        self.assertEqual(this_weeks_tab(["12/28"], dt.date(2027, 1, 2)), "12/28")

    def test_last_years_same_name_tab_and_week_ending_names(self):
        import datetime as dt
        from automations.sales_board_fixer.run import this_weeks_tab
        # Palace: newest on the left, named by Sunday, a year of old tabs to the right
        palace = ["10.18", "10.11", "10.4", "1026", "10.19", "10.12"]
        self.assertIsNone(this_weeks_tab(palace, dt.date(2026, 10, 19), week_end=True))
        self.assertEqual(this_weeks_tab(palace, dt.date(2026, 10, 15), week_end=True), "10.18")
        self.assertEqual(this_weeks_tab(["10.25"] + palace, dt.date(2026, 10, 20),
                                        week_end=True), "10.25")


class LineupNames(unittest.TestCase):
    BOARDS = {"Sales Board WE 10.25": (3, 4, 63)}

    def fix(self, f, boards=None, home=None, keep=()):
        return [(y.where, y.kind, y.value) for y in
                K.check_lineup_names("t", f, boards or self.BOARDS, home, keep)]

    def test_short_range_is_stretched_to_the_row_above_totals(self):
        f = [["", ""], ["", "={'Sales Board WE 10.25'!$C4:$C51}"]]
        self.assertEqual(self.fix(f), [("B2", "lineup_short",
                                        "={'Sales Board WE 10.25'!$C4:$C63}")])

    def test_long_range_is_cut_back_so_totals_stays_out(self):
        f = [["={'Sales Board WE 10.25'!$C4:$C70}"]]
        self.assertEqual(self.fix(f)[0][2], "={'Sales Board WE 10.25'!$C4:$C63}")

    def test_right_range_sums_and_other_columns_left_alone(self):
        f = [["={'Sales Board WE 10.25'!$C4:$C63}",
              "=SUM('Sales Board WE 10.25'!$C4:$C51)",
              "={'Sales Board WE 10.25'!$F4:$F51}"]]
        self.assertEqual(self.fix(f), [])

    def test_a_teams_slice_is_not_every_rep(self):
        # Kash's Territory Line Up: B4:B13, B14:B23... per team, starts mid-board
        f = [["={'Sales Board WE 10.25'!C13:C23}", "={'Sales Board WE 10.25'!C24:C33}"]]
        self.assertEqual(self.fix(f), [])

    def test_old_week_moves_to_the_board_in_use(self):
        # Cyrus 2026-10-22: Line Up read '5.18' (rows 4-104), board in use '10.20'
        boards = {"5.18": (2, 4, 104), "10.20": (2, 4, 28)}
        f = [["={'5.18'!$B4:$B104}"]]
        self.assertEqual(self.fix(f, boards, home="10.20", keep={"10.20"}),
                         [("A1", "lineup_old_week", "={'10.20'!$B4:$B28}")])

    def test_a_board_of_this_run_never_moves(self):
        # Jacob: two boards in use, the Line Up reads the first
        boards = {"NEW Sales Board": (2, 4, 138), "w.e 10/12/26": (2, 4, 90)}
        f = [["={'NEW Sales Board'!B4:B138}"]]
        self.assertEqual(self.fix(f, boards, home="w.e 10/12/26",
                                  keep={"NEW Sales Board", "w.e 10/12/26"}), [])

    def test_split_list_only_the_lowest_piece_ends_above_totals(self):
        # Miami JAIRO 2026-10-22: four columns, the last one ran to 131 (TOTALS 114)
        boards = {"JAIRO": (2, 4, 113)}
        f = [["={JAIRO!B4:B38}", "={JAIRO!B39:B73}", "={JAIRO!B73:B113}", "={JAIRO!B93:B131}"]]
        self.assertEqual(self.fix(f, boards, home="JAIRO", keep={"JAIRO"}),
                         [("D1", "lineup_short", "={JAIRO!B93:B113}")])
        f = [["={COLTEN!B4:B38}", "={COLTEN!B39:B72}", "={COLTEN!B73:B107}"]]
        self.assertEqual(self.fix(f, {"COLTEN": (2, 4, 107)}), [])

    def test_gone_tab_left_alone(self):
        f = [["={'Sales Board'!B4:B13}"]]
        self.assertEqual(self.fix(f), [])


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


class OutsideBlock(unittest.TestCase):
    """Eve, 2026-10-26: the whole tab, not just the rep rows."""

    def teams(self, mindset="=SUM($E%(r)d:$G%(r)d)"):
        v, f = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(8)])
        for team in ("Sins", "Alphaletes", "Hashiras", "Mindset", "Ceaseless"):
            r = len(f) + 1
            cell = (mindset if team == "Mindset" else "=SUM($E%(r)d:$G%(r)d)") % {"r": r}
            v.append(["", "", team, "0", "0", "0", ""])
            f.append(["", "", team, cell, "0", "0", ""])
        return v, f

    def test_typed_number_in_teams_block_gets_formula_back(self):
        v, f = self.teams(mindset="75")
        found = K.check_outside_block("t", v, f)
        self.assertEqual([(x.where, x.value, x.name) for x in found],
                         [("D16", "=SUM($E16:$G16)", "Mindset")])

    def test_healthy_teams_block_is_quiet(self):
        v, f = self.teams()
        self.assertEqual(K.check_outside_block("t", v, f), [])

    def test_totals_row_is_not_a_rep_row(self):
        v, f = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(8)])
        f[-1][3] = "12"           # TOTALS typed: rep formulas above don't count
        self.assertEqual(K.check_outside_block("t", v, f), [])

    def test_typed_between_dragged_row_formulas(self):
        v, f = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(8)])
        f[-1][3:6] = ["=SUM(D4:D11)", "40", "=SUM(F4:F11)"]
        found = K.check_outside_block("t", v, f)
        self.assertEqual([(x.where, x.value) for x in found], [("E12", "=SUM(E4:E11)")])

    def test_typed_history_column_left_alone(self):
        v, f = board([("Rep %d" % i, GOOD, "1", "Here") for i in range(8)])
        for n in (232, 499, 355):
            v.append(["", "", "WE", str(n), "", "", ""])
            f.append(["", "", "WE", n, "", "", ""])
        self.assertEqual(K.check_outside_block("t", v, f), [])

    def test_whole_run_typed_over_is_fixed_in_one_pass(self):
        v, f = self.teams()
        for r in (13, 14, 15):              # Sins, Alphaletes, Hashiras frozen
            f[r - 1][3] = "205"
        found = K.check_outside_block("t", v, f)
        self.assertEqual([x.where for x in found], ["D13", "D14", "D15"])
        self.assertEqual(found[0].value, "=SUM($E13:$G13)")


def stats_board(field_shown, board_shown, field_fx=None, sold=(1, 0, 2, 0), tk=(50, 40, 0, 0)):
    n = len(field_shown)
    sold, tk = (tuple(sold) + (0,) * 7)[:n], (tuple(tk) + (0,) * 7)[:n]
    """n days (MON..., one per shown value) of Apps | TK, 6 reps, TOTALS, a blank row, then
    'Total Reps in the Field' and 'Reps that got on the Board' under each Apps."""
    days = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[:n]
    w = 3 + 2 * n
    hdr1 = ["", "", ""] + [x for d in days for x in (d, "")]
    hdr3 = ["", "#", "Name"] + ["Apps", "TK"] * n
    vals, fx = [hdr1, [""] * w, hdr3], [hdr1, [""] * w, hdr3]
    for i in range(6):
        row = ["", str(i + 1), "Rep %d" % i]
        for d in range(n):
            row += [str(sold[d]) if i == 0 else "0", str(tk[d]) if i < 2 else ""]
        vals.append(row)
        fx.append(row)
    vals.append(["", "", "TOTALS"] + [""] * (w - 3))
    fx.append(["", "", "TOTALS"] + [""] * (w - 3))
    vals.append([""] * w)
    fx.append([""] * w)
    for label, shown, f in (("Total Reps in the Field", field_shown, field_fx),
                            ("Reps that got on the Board", board_shown, None)):
        v, x = ["", "", label], ["", "", label]
        for d in range(n):
            c = 4 + 2 * d
            apps, tkc = K.col_letter(c), K.col_letter(c + 1)
            good = "=COUNTIF(%s4:%s9,\">0\")+COUNTIF(%s4:%s9,\">0\")" % (apps, apps, tkc, tkc)
            v.append(str(shown[d]))
            x.append((f or {}).get(d, good))
            v.append("")
            x.append("")
        vals.append(v)
        fx.append(x)
    return vals, fx


class DayStats(unittest.TestCase):
    def test_day_with_knocks_but_zero_in_field_gets_other_days_formula(self):
        v, f = stats_board((2, 0, 1, 0), (1, 0, 1, 0), field_fx={1: "=0"})
        found = K.check_day_stats("t", v, f)
        self.assertEqual([(y.kind, y.where) for y in found], [("day_stats_formula", "F12")])
        self.assertEqual(found[0].value, '=COUNTIF(F4:F9,">0")+COUNTIF(G4:G9,">0")')

    def test_day_nobody_worked_yet_is_not_flagged(self):
        v, f = stats_board((2, 2, 1, 0), (1, 0, 1, 0))
        self.assertEqual(K.check_day_stats("t", v, f), [])

    def test_fewer_in_field_than_on_board_with_no_formula_to_copy_is_reported(self):
        bad = {d: "=1" for d in range(4)}
        v, f = stats_board((1, 2, 1, 0), (1, 0, 2, 0), field_fx=bad)
        found = K.check_day_stats("t", v, f)
        self.assertEqual([(y.kind, y.where) for y in found], [("day_stats_wrong", "H12")])
        self.assertFalse(found[0].fixable)

    def test_board_without_summary_rows_is_skipped(self):
        v, f = stats_board((2, 2, 1, 0), (1, 0, 1, 0))
        self.assertEqual(K.check_day_stats("t", v[:10], f[:10]), [])


class DayRows(unittest.TestCase):
    def test_odd_day_formula_and_typed_day_get_the_days_formula(self):
        v, f = stats_board((2, 0, 1, 0, 0, 0, 0), (1, 0, 1, 0, 0, 0, 0), field_fx={1: "=0"})
        f[11][9] = "7"                                   # THU typed over
        found = {y.where: (y.kind, y.value) for y in K.check_day_rows("t", v, f)}
        self.assertEqual(found["F12"], ("day_formula_differs", '=COUNTIF(F4:F9,">0")+COUNTIF(G4:G9,">0")'))
        self.assertEqual(found["J12"][0], "typed_over_formula")

    def test_three_days_agreeing_is_not_enough(self):
        v, f = stats_board((2, 0, 1, 0), (1, 0, 1, 0), field_fx={1: "=0", 3: "=1"})
        self.assertFalse([y for y in K.check_day_rows("t", v, f) if y.row == 12])

    def test_sum_that_only_starts_on_another_row_is_left_alone(self):
        v, f = stats_board((2, 0, 1, 0, 0, 0, 0), (1, 0, 1, 0, 0, 0, 0),
                           field_fx={1: '=COUNTIF(F3:F9,">0")+COUNTIF(G3:G9,">0")'})
        self.assertFalse([y for y in K.check_day_rows("t", v, f) if y.row == 12])

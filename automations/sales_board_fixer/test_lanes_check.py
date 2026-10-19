"""python -m unittest automations.sales_board_fixer.test_lanes_check"""
import unittest

from automations.sales_board_fixer import lanes_check as LC

CUR, LAST = "Sales Board WE 10.18", "Sales Board WE 10.11"


def lane(tab, end, cond, status="DQ"):
    t = "'%s'!" % tab
    return ('=iferror(FILTER(%sC4:C%d, %sD4:D%d%s,%sDC4:DC%d<>"T",%s%s4:%s%d<>"1st Wk"),"")'
            % (t, end, t, end, cond, t, end, t, status, status, end))


CONDS = [">=10", ">=8, '{t}'!D4:D{e}<10"]


def tab(cur_end=72, last_end=83, cur=None, last=None, extra="=FILTER(E3:E, E3:E<>\"\")"):
    def conds(t, e):
        return [lane(t, e, c.format(t=t, e=e)) for c in CONDS]
    cur = cur if cur is not None else conds(CUR, cur_end)
    last = last if last is not None else conds(LAST, last_end)
    vals = [["Current Week", "", "", "Last week", "", "", ""],
            ["Super Saiyan Lane 10+ Apps", "Fast Lane 8+", "", "Super Saiyan Lane 10+ Apps",
             "Fast Lane 8+", "", "2wks in a Row"],
            ["Ann", "Bo", "", "Cy", "Di", "", "x"],
            ["Ed", "", "", "", "", "", ""]]
    forms = [vals[0], vals[1], cur + [""] + last + ["", extra], vals[3]]
    entered = [[True] * 7, [True] * 7, [True, True, False, True, True, False, True],
               [False] * 7]
    return forms, vals, entered


def board(status_col="DQ"):
    """A Sales Board grid wide enough for DC / DQ, 'Field Status' at status_col."""
    from automations.sales_board_fixer.checks import col_index
    w = col_index("DT")
    g = [[""] * w for _ in range(90)]
    g[0][col_index("D") - 1], g[2][col_index("D") - 1] = "RUNNING WEEK TOTALS", "Total Apps"
    g[0][col_index("DC") - 1], g[2][col_index("DC") - 1] = "SUN", "Apps"
    g[0][col_index(status_col) - 1] = "Field Status"
    for r in range(3, 70):
        g[r][2] = "Rep %d" % r
        g[r][col_index("DC") - 1] = "1.00"
        g[r][col_index(status_col) - 1] = "5th wk+"
    return g


TARGETS = {"current": (CUR, 72), "last": (LAST, 83)}


class LanesCheck(unittest.TestCase):
    def kinds(self, found):
        return sorted({f.kind for f in found})

    def test_healthy_tab_only_reports_the_dead_t_condition(self):
        f, v, e = tab()
        found = LC.check(f, v, e, {CUR: board(), LAST: board()}, TARGETS, None)
        self.assertEqual(self.kinds(found), ["lane_dead_cond"])
        self.assertFalse(any(x.fixable for x in found))

    def test_deleted_lane_comes_back_from_its_twin(self):
        f, v, e = tab()
        f[2][1] = ""
        found = [x for x in LC.check(f, v, e, {}, TARGETS, None) if x.where == "B3"]
        self.assertEqual(found[0].kind, "lane_formula_lost")
        self.assertIn("'%s'!D4:D72<10" % CUR, found[0].value)
        self.assertNotIn(LAST, found[0].value)

    def test_both_twins_gone_uses_the_healthy_copy(self):
        f, v, e = tab()
        good_b = f[2][1]
        f[2][1] = f[2][4] = "Ed"
        found = LC.check(f, v, e, {}, TARGETS, {"formulas": {"B": good_b}, "headers": {}})
        b = [x for x in found if x.where == "B3"][0]
        self.assertEqual(b.value, good_b)
        # and the other block's lane then heals off the one just put back
        e3 = [x for x in found if x.where == "E3"][0]
        self.assertIn("'%s'!D4:D83<10" % LAST, e3.value)

    def test_ref_error_counts_as_lost(self):
        f, v, e = tab()
        f[2][0] = f[2][0].replace("DQ4:DQ72", "#REF!")
        x = [y for y in LC.check(f, v, e, {}, TARGETS, None) if y.where == "A3"][0]
        self.assertEqual(x.kind, "lane_formula_lost")
        self.assertNotIn("#REF!", x.value)

    def test_wrong_end_row_is_repointed(self):
        f, v, e = tab(cur_end=60)
        found = [x for x in LC.check(f, v, e, {}, TARGETS, None) if x.kind == "lane_range"]
        self.assertEqual(sorted(x.where for x in found), ["A3", "B3"])

    def test_inserted_column_moves_the_letter(self):
        f, v, e = tab()
        good = LC.remember(f, v, {CUR: board(), LAST: board()})
        self.assertEqual(good["headers"]["DQ"], "field status|")
        found = LC.check(f, v, e, {CUR: board("DR"), LAST: board()}, TARGETS, good)
        moved = [x for x in found if x.kind == "lane_col_moved"]
        self.assertEqual(sorted(x.where for x in moved), ["A3", "B3"])
        self.assertIn("'%s'!DR4:DR72" % CUR, moved[0].value)
        self.assertIn("'%s'!DQ4:DQ83" % LAST, f[2][3])   # last week untouched

    def test_col_m_formula_comes_back(self):
        f, v, e = tab()
        good = LC.remember(f, v, {})
        f[2][6] = ""
        x = [y for y in LC.check(f, v, e, {}, TARGETS, good) if y.where == "G3"][0]
        self.assertEqual(x.kind, "lane_extra_lost")
        self.assertEqual(x.value, good["formulas"]["G"])

    def test_typed_under_a_lane_is_reported_not_cleared(self):
        f, v, e = tab()
        e[3][0] = True
        x = [y for y in LC.check(f, v, e, {}, TARGETS, None) if y.kind == "lane_spill_blocked"]
        self.assertEqual(x[0].where, "A4")
        self.assertFalse(x[0].fixable)

    def test_threshold_not_matching_header(self):
        f, v, e = tab()
        f[2][1] = f[2][1].replace(">=8", ">=7")
        x = [y for y in LC.check(f, v, e, {}, TARGETS, None) if y.kind == "lane_threshold"]
        self.assertEqual([y.where for y in x], ["B3"])

    def test_twins_that_differ_only_in_spaces_are_the_same(self):
        f, v, e = tab()
        f[2][3] = f[2][3].replace(", ", ",")
        self.assertFalse([y for y in LC.check(f, v, e, {}, TARGETS, None)
                          if y.kind == "lane_twin_differs"])
        f[2][3] = f[2][3].replace(">=10", ">=11")
        self.assertTrue([y for y in LC.check(f, v, e, {}, TARGETS, None)
                         if y.kind == "lane_twin_differs"])

    def test_restore_lost_for_the_ten_minute_job(self):
        f, v, _ = tab()
        f[2][3] = "oops"
        out = LC.restore_lost(f, v, None)
        self.assertEqual(list(out), [3])
        self.assertIn(CUR, out[3])          # lanes.py repoints it to last week


if __name__ == "__main__":
    unittest.main()

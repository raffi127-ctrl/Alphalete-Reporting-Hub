import unittest
from types import SimpleNamespace as NS

from automations.sales_board_fixer import lineup_city as L


def grid():
    hdr = [""] * 26
    hdr[0], hdr[8], hdr[9], hdr[23], hdr[24] = "#", "Zip Code", "City", "Zip Code", "City"
    rows = [[""] * 26, hdr]
    for n, (zip_, city, tz, tc) in enumerate([("75024", "Plano", "75024", "Plano"),
                                              ("75104", "Cedar Hill", "75104", "Cedar Hill"),
                                              ("", "", "", "")], 1):
        row = [""] * 26
        row[0], row[8], row[9], row[23], row[24] = n, zip_, city, tz, tc
        rows.append([str(x) for x in row])
    return rows


def with_formulas():
    f = [list(r) for r in grid()]
    for r in range(3, 6):
        f[r - 1][9] = '=XLOOKUP(I%d, X:X, Y:Y, "")' % r
    return f


class Layout(unittest.TestCase):
    def test_first_pair_is_the_line_up_second_is_the_table(self):
        lay = L.layout(grid())
        self.assertEqual((lay["zip"], lay["city"], lay["table_zip"], lay["table_city"]),
                         (9, 10, 24, 25))
        self.assertEqual((lay["first"], lay["last"]), (3, 5))

    def test_a_row_added_moves_the_columns_and_rows_with_it(self):
        g = [[""] * 26] + grid()
        lay = L.layout(g)
        self.assertEqual((lay["first"], lay["last"]), (4, 6))

    def test_old_tab_without_the_table_is_left_alone(self):
        g = grid()
        g[1][23] = g[1][24] = ""
        self.assertIsNone(L.layout(g))


class Cells(unittest.TestCase):
    def test_typed_city_goes_back_to_the_formula(self):
        f = with_formulas()
        f[3][9] = "Cedar Hill"
        cells, kept = L.plan_cells(grid(), f, L.layout(grid()))
        self.assertEqual(cells, {"J4": '=XLOOKUP(I4, X:X, Y:Y, "")'})
        self.assertEqual(kept, [])

    def test_nothing_to_do_when_formulas_are_there(self):
        self.assertEqual(L.plan_cells(grid(), with_formulas(), L.layout(grid())), ({}, []))

    def test_spacing_is_not_a_difference(self):
        f = with_formulas()
        f[2][9] = '=XLOOKUP(I3,X:X,Y:Y,"")'
        self.assertEqual(L.plan_cells(grid(), f, L.layout(grid()))[0], {})

    def test_zip_missing_from_the_table_keeps_the_typed_city(self):
        g, f = grid(), with_formulas()
        g[4][8], g[4][9] = "76017", "Arlington"
        f[4][9] = "Arlington"
        cells, kept = L.plan_cells(g, f, L.layout(g))
        self.assertEqual(cells, {})
        self.assertIn("76017", kept[0])


class Protection(unittest.TestCase):
    lay = {"first": 3, "last": 38, "city": 10}

    def rng(self, **kw):
        r = {"sheetId": 7, "startRowIndex": 2, "endRowIndex": 38,
             "startColumnIndex": 9, "endColumnIndex": 10}
        r.update(kw)
        return r

    def test_none_yet_adds_one(self):
        req = L.plan_protection(7, self.lay, [])
        self.assertEqual(req["addProtectedRange"]["protectedRange"]["range"], self.rng())
        self.assertEqual(req["addProtectedRange"]["protectedRange"]["editors"]["users"], L.EDITORS)

    def test_already_right_is_left_alone(self):
        p = {"protectedRangeId": 1, "range": self.rng(), "editors": {"users": list(L.EDITORS)}}
        self.assertIsNone(L.plan_protection(7, self.lay, [p]))

    def test_raf_missing_is_added_to_the_same_protection(self):
        # Maud's own lock on WE 11.15: her + reporting, no Raf
        p = {"protectedRangeId": 1, "range": self.rng(),
             "editors": {"users": ["maudmiller4@gmail.com", "alphaletereporting@gmail.com"]}}
        req = L.plan_protection(7, self.lay, [p])["updateProtectedRange"]["protectedRange"]
        self.assertEqual(req["protectedRangeId"], 1)
        self.assertEqual(req["editors"]["users"], L.EDITORS)

    def test_another_column_protected_does_not_count(self):
        p = {"protectedRangeId": 1, "range": self.rng(startColumnIndex=1, endColumnIndex=2),
             "editors": {"users": list(L.EDITORS)}}
        self.assertIn("addProtectedRange", L.plan_protection(7, self.lay, [p]))


class NeverStopsTheFixer(unittest.TestCase):
    def test_locked_out_is_one_line_for_eve(self):
        def boom(_):
            raise RuntimeError("You are trying to edit a protected cell")
        lines = L.do_tab(NS(worksheet=boom), "Line Up WE 11.15", True)
        self.assertIn("protected", lines[0])


if __name__ == "__main__":
    unittest.main()

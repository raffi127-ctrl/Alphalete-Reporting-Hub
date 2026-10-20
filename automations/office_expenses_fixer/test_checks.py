import unittest

from automations.office_expenses_fixer import checks as C


def tab(amounts, total_row=8, sum_to=None, monthly="=C{t}+B{t}*52/12"):
    """The template's shape: A name, B weekly, C monthly; header row 2,
    expenses from row 3, TOTAL, then Monthly / Weekly Expenses."""
    f = [["OFFICE EXPENSES", "", ""], ["Expense", "Weekly Expenses", "Monthly Expenses"]]
    for i, (name, wk, mo) in enumerate(amounts):
        f.append([name, wk, mo])
    while len(f) < total_row - 1:
        f.append(["", "", ""])
    end = sum_to or total_row - 1
    t = total_row
    f.append(["TOTAL", "=SUM(B3:B%d)" % end, "=SUM(C3:C%d)" % end])
    f.append(["Monthly Expenses ", monthly.format(t=t), ""])
    f.append(["Weekly Expenses", "=B{t}+C{t}*12/52".format(t=t), ""])
    return f


class Sums(unittest.TestCase):
    def test_expense_added_under_the_sum_range_stretches_it(self):
        f = tab([("Rent", "", 2500), ("Indeed", 100, ""), ("Zoom", 14, "")], sum_to=4)
        found = C.check_sums(f, f)
        self.assertEqual([(x.where, x.value) for x in found], [("B8", "=SUM(B3:B7)")])

    def test_amount_typed_as_text_becomes_a_number(self):
        f = tab([("Rent", "", "$2,500"), ("Indeed", 100, "")])
        found = C.check_sums(f, f)
        self.assertEqual([(x.where, x.value) for x in found], [("C3", 2500)])

    def test_a_dash_is_not_an_amount(self):
        f = tab([("Rent", "-", "-")])
        self.assertEqual(C.check_sums(f, f), [])

    def test_side_by_side_blocks_all_found(self):
        f = [["OFFICE EXPENSES"], ["Weekly Expenses", "", "Monthly Expenses", ""],
             ["Recruiting", 5, "Rent", 2500], ["Admin", 6, "Internet", 80],
             ["TOTAL", "=SUM(B3:B4)", "TOTAL", "=SUM(D3:D4)"],
             ["TOTAL", "", "=(B5*4)+D5", ""]]
        self.assertEqual([(b.label_col, b.amt_col, b.total_row, b.first) for b in C.blocks(f)],
                         [(1, 2, 5, 3), (3, 4, 5, 3)])


    def test_a_total_with_no_expenses_header_is_another_table(self):
        f = [["", "Office Space"], ["Lobby", 250], ["Atmo", 500], ["Total", "=SUM(B2:B3)"]]
        self.assertEqual(C.blocks(f), [])


class Errors(unittest.TestCase):
    def test_errors_the_template_already_has_are_one_line(self):
        tpl_f = [["", "=#REF!"], ["", "=A1+1"]]
        tpl_v = [["", "#REF!"], ["", "1"]]
        f = [["", ""], ["", "=#REF!"], ["", "=#DIV/0"]]
        v = [["", ""], ["", "#REF!"], ["", "#DIV/0!"]]
        found = C.check_errors(v, f, C.template_errors(tpl_v, tpl_f))
        self.assertEqual([(x.kind, x.where) for x in found],
                         [("error_value", "B3"), ("template_error", "B2")])


class Derived(unittest.TestCase):
    def test_lost_monthly_formula_comes_back_from_the_other_offices(self):
        good = [tab([("Rent", "", 1)]), tab([("Rent", "", 1)], total_row=9)]
        broken = tab([("Rent", "", 1)], monthly="5000")
        peers = C.peer_formulas([C.shape(g) for g in good + [broken]])
        found = C.check_derived(broken, broken, peers)
        self.assertEqual([(x.kind, x.where, x.value) for x in found],
                         [("derived_lost", "B9", "=C8+B8*52/12")])

    def test_a_different_working_formula_is_only_reported(self):
        good = [tab([("Rent", "", 1)]) for _ in range(3)]
        own = tab([("Rent", "", 1)], monthly="=C{t}*1+B{t}*4")
        peers = C.peer_formulas([C.shape(g) for g in good + [own]])
        found = C.check_derived(own, own, peers)
        self.assertEqual([(x.kind, x.fixable) for x in found], [("derived_differs", False)])

    def test_one_office_alone_sets_no_rule(self):
        only = tab([("Rent", "", 1)])
        self.assertEqual(C.peer_formulas([C.shape(only)]), {((1, 2), (1, 3)): {}})

    def test_offices_of_another_shape_dont_vote(self):
        nds = [[["OFFICE EXPENSES"], ["Weekly Expenses", "", "Monthly Expenses", ""],
                ["Recruiting", 5, "Rent", 2500],
                ["TOTAL", "=SUM(B3:B3)", "TOTAL", "=SUM(D3:D3)"],
                ["TOTAL", "", "=(B4*4)+D4", ""]] for _ in range(3)]
        mine = tab([("Rent", "", 1)])
        peers = C.peer_formulas([C.shape(g) for g in nds + [mine]])
        self.assertEqual(C.check_derived(mine, mine, peers), [])

    def test_total_typed_over_gets_its_sum_back(self):
        good = [tab([("Rent", "", 1)]) for _ in range(2)]
        bad = tab([("Rent", "", 1)])
        bad[7][2] = 2500                               # C8 typed over
        peers = C.peer_formulas([C.shape(g) for g in good + [bad]])
        found = C.check_total_typed_over(bad, list(peers))
        self.assertEqual([(x.where, x.value) for x in found], [("C8", "=SUM(C3:C7)")])


class Notes(unittest.TestCase):
    def test_note_keeps_what_was_there(self):
        x = C.Finding("sum_short", "B8", "", before="=SUM(B3:B4)", after="=SUM(B3:B7)",
                      value="=SUM(B3:B7)")
        notes = [[""] * 3 for _ in range(8)]
        notes[7][1] = "Raf: check rent"
        req = C.note_requests([x], 5, notes, "10/20")[0]
        text = req["updateCells"]["rows"][0]["values"][0]["note"]
        self.assertTrue(text.startswith("Raf: check rent\n\nLucy fixed this (10/20):"))


if __name__ == "__main__":
    unittest.main()

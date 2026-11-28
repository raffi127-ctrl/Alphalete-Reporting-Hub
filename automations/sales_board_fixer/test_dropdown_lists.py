"""Each dropdown column offers its own options (Raf 2026-11-27: Direct Deposit
showed 'Indeed / Linkedin' -- one rule shared with 'Add applied to'). The right
list: pinned by name (Direct Deposit / DD), else last week's tab, same column."""
from __future__ import annotations

import unittest

from automations.sales_board_fixer import checks as K
from automations.sales_board_fixer import run as R


def rule(*words):
    return {"condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": w} for w in words]},
            "showCustomUi": True}


DD = rule(*K.DD_LIST)
INDEED = rule("Indeed", "Linkedin")
FIELD = rule("1st Wk", "2nd Wk", "Extra")
DPC, DDC, FSC = 5, 6, 7   # E 'Direct Deposit' (row 1), F 'DD' (row 3), G 'Field Status'


def tab(reps, free=1, shift=False):
    """reps: [(name, text, E rule, F rule, G rule)]; `free` blank rows, then
    TOTALS. shift: an extra empty column in front (columns moved this week)."""
    pad = [""] if shift else []
    rows = [["", "", "", "MON"] + pad + ["Direct Deposit", "", "Field Status"],
            [""] * (7 + len(pad)),
            ["", "#", "Name", "Apps"] + pad + ["", "DD", ""]]
    rules = [[], [], []]
    for name, text, e, f, g in reps:
        rows.append(["", "1", name, "0"] + pad + [text, "", ""])
        rules.append([None] * 4 + [None] * len(pad) + [e, f, g])
    for _ in range(free):
        rows.append([""] * (7 + len(pad)))
        rules.append([None] * 4 + [None] * len(pad) + [INDEED, INDEED, None])
    rows.append(["", "", "TOTALS"] + [""] * (4 + len(pad)))
    return rows, rules


def good(n=6, g=FIELD):
    return [("Rep %d" % i, "", DD, DD, g) for i in range(n)]


class Pinned(unittest.TestCase):
    def test_finds_both_columns_by_header(self):
        rows, rules = tab(good())
        cols = K.dropdown_list_cols(rows, rules)
        self.assertEqual(cols, {DPC: (frozenset(K.DD_LIST), True), DDC: (frozenset(K.DD_LIST), True)})

    def test_wrong_list_gets_the_right_one_copied_text_kept(self):
        rows, rules = tab(good(5) + [("Dylan", "Completed", INDEED, DD, FIELD)], free=0)
        found = K.check_dropdown_lists("Board", 7, rows, rules)
        self.assertEqual([(x.kind, x.where, x.name) for x in found],
                         [("dropdown_wrong_list", "E9", "Dylan")])
        x = found[0]
        self.assertIsNone(x.value)                       # the word stays
        paste = x.request["copyPaste"]
        self.assertEqual(paste["pasteType"], "PASTE_DATA_VALIDATION")
        self.assertEqual(paste["source"]["startColumnIndex"], DPC - 1)
        self.assertIn("Completed", x.before)

    def test_whole_pinned_column_wrong_is_still_fixed(self):
        rows, rules = tab([("Rep %d" % i, "", DD, INDEED, FIELD) for i in range(6)])
        found = [x for x in K.check_dropdown_lists("Board", 7, rows, rules) if x.where.startswith("F")]
        self.assertEqual(len(found), 7)                  # 6 reps + the free row
        self.assertTrue(all(x.request["copyPaste"]["source"]["startColumnIndex"] == DPC - 1
                            for x in found))

    def test_a_subset_is_still_wrong(self):
        rows, rules = tab(good(5) + [("Raf fixed", "", rule("Completed", "Submitted"), DD, FIELD)],
                          free=0)
        self.assertEqual([x.where for x in K.check_dropdown_lists("Board", 7, rows, rules)], ["E9"])

    def test_no_good_cell_anywhere_is_report_only(self):
        rows, rules = tab([("Rep %d" % i, "", INDEED, INDEED, FIELD) for i in range(6)], free=0)
        found = K.check_dropdown_lists("Board", 7, rows, rules)
        self.assertTrue(found and not any(x.fixable for x in found))


class LastWeek(unittest.TestCase):
    def prev(self, g=FIELD, shift=False):
        rows, rules = tab(good(8, g), free=0, shift=shift)
        return (99, rows, rules)

    def test_any_column_takes_last_weeks_list(self):
        rows, rules = tab(good(6) + [("Odd", "", DD, DD, INDEED)], free=0)
        found = K.check_dropdown_lists("Board", 7, rows, rules, self.prev())
        self.assertEqual([(x.kind, x.where) for x in found], [("dropdown_wrong_list", "G10")])
        self.assertEqual(found[0].request["copyPaste"]["source"]["sheetId"], 7)   # this tab

    def test_columns_that_moved_still_match_by_name(self):
        rows, rules = tab(good(6) + [("Odd", "", DD, DD, INDEED)], free=0)
        found = K.check_dropdown_lists("Board", 7, rows, rules, self.prev(shift=True))
        self.assertEqual([x.where for x in found], ["G10"])

    def test_no_good_cell_this_week_copies_from_last_week(self):
        # Direct Deposit AND DD both wrong on every row (pinned: always fixed)
        rows, rules = tab([("Rep %d" % i, "", INDEED, INDEED, FIELD) for i in range(6)], free=0)
        found = K.check_dropdown_lists("Board", 7, rows, rules, self.prev())
        self.assertEqual(len(found), 12)
        self.assertTrue(all(x.request["copyPaste"]["source"]["sheetId"] == 99 for x in found))

    def test_column_with_no_good_cell_left_is_only_told(self):
        reps = [("Rep %d" % i, "", DD, DD, None) for i in range(5)] + [("Odd", "", DD, DD, INDEED)]
        rows, rules = tab(reps, free=0)
        found = K.check_dropdown_lists("Board", 7, rows, rules, self.prev())
        self.assertEqual([(x.kind, x.fixable) for x in found], [("dropdown_list_changed", False)])

    def test_whole_column_changed_is_only_told(self):
        rows, rules = tab(good(6, g=INDEED), free=0)
        found = K.check_dropdown_lists("Board", 7, rows, rules, self.prev())
        self.assertEqual([(x.kind, x.where, x.fixable) for x in found],
                         [("dropdown_list_changed", "G", False)])
        lines = R.list_changed_lines({"Board": found})
        self.assertEqual(len(lines), 1)
        self.assertIn("Field Status", list(lines.values())[0])

    def test_no_last_week_no_opinion(self):
        rows, rules = tab(good(6) + [("Odd", "", DD, DD, INDEED)], free=0)
        self.assertEqual(K.check_dropdown_lists("Board", 7, rows, rules), [])

    def test_majority_check_leaves_those_columns_alone(self):
        reps = [("Rep %d" % i, "", INDEED, DD, FIELD) for i in range(9)] + [("X", "", DD, DD, FIELD)]
        rows, rules = tab(reps, free=0)
        self.assertEqual(K.check_dropdowns("Board", 7, rows, rules, skip_cols={DPC, DDC, FSC}), [])


class Filter(unittest.TestCase):
    def test_filter_comes_off_and_back_without_its_sort(self):
        flt = {"range": {"sheetId": 7}, "sortSpecs": [{"dimensionIndex": 3}],
               "filterSpecs": [{"columnIndex": 9, "filterCriteria": {"hiddenValues": ["ATT"]}}]}
        reqs = R.lift_filter(7, flt, [{"copyPaste": {}}])
        self.assertEqual(reqs[0], {"clearBasicFilter": {"sheetId": 7}})
        self.assertEqual(reqs[1], {"copyPaste": {}})
        back = reqs[2]["setBasicFilter"]["filter"]
        self.assertNotIn("sortSpecs", back)
        self.assertEqual(back["filterSpecs"], flt["filterSpecs"])


if __name__ == "__main__":
    unittest.main()

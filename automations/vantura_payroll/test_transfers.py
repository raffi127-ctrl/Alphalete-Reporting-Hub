"""Standing rep transfers off the 'Payroll Transfers' tab (Carlos 2026-11-11:
Jacob Ortega's sale under Sebastian's login pays Jacob when it posts).

  python -m unittest automations.vantura_payroll.test_transfers
"""
from __future__ import annotations

import unittest

from automations.vantura_payroll import run as R

HDR = ["Customer", "Sale Date", "From Rep", "To Rep", "Note", "Added", "Last applied"]
quiet = lambda *_a, **_k: None  # noqa: E731


def _rules(*rows):
    return R.rules_from_values([HDR] + [list(r) + [""] * (7 - len(r)) for r in rows], log=quiet)


def _raw(rep, sale, customer, amount="$188.00"):
    return ["11.15", rep, sale, "11/13/2026", "OOF", "", customer, amount]


class Rules(unittest.TestCase):
    def test_rows_become_rules_and_junk_is_skipped(self):
        rules = _rules(["", "11/11/2026", "Sebastian Avellaneda", "Jacob Isaiah Ortega", "note"],
                       ["", "", "", "", ""],                       # blank line
                       ["How it works: ...", "", "", "", ""],       # the note row: no To Rep
                       ["", "", "", "Nobody", ""])                  # To Rep but no key
        self.assertEqual([r["to_rep"] for r in rules], ["Jacob Isaiah Ortega"])
        self.assertEqual(rules[0]["row"], 2)
        self.assertEqual(R.rules_from_values([], log=quiet), [])
        self.assertEqual(R.rules_from_values([["Customer", "Nope"]], log=quiet), [])


class Matching(unittest.TestCase):
    def test_from_rep_words_and_sale_date(self):
        rule = _rules(["", "11/11/2026", "Sebastian Avellaneda", "Jacob Isaiah Ortega"])[0]
        self.assertTrue(R._transfer_matches(rule, "SEBASTIAN PEDRO AVELLANEDA", "11/11/2026", "ANY ONE"))
        self.assertTrue(R._transfer_matches(rule, "Sebastian Avellaneda", "2026-11-11", "x"))
        self.assertFalse(R._transfer_matches(rule, "Sebastian Avellaneda", "11/12/2026", "x"))   # other day
        self.assertFalse(R._transfer_matches(rule, "Sebastian Monge", "11/11/2026", "x"))        # other Sebastian
        self.assertFalse(R._transfer_matches(rule, "Jacob Isaiah Ortega", "11/11/2026", "x"))

    def test_customer_name_is_word_for_word_case_blind(self):
        rule = _rules(["Noemi Avila", "", "", "Edgar Camunez"])[0]
        self.assertTrue(R._transfer_matches(rule, "Anyone", "10/1/2026", "NOEMI AVILA"))
        self.assertTrue(R._transfer_matches(rule, "Anyone", "", "Noemi  Avila "))
        self.assertFalse(R._transfer_matches(rule, "Anyone", "", "Noemi Avila Jr"))
        self.assertFalse(R._transfer_matches(rule, "Anyone", "", "Avila"))

    def test_apply_rewrites_col_b_only_for_matches(self):
        rules = _rules(["", "11/11/2026", "Sebastian Avellaneda", "Jacob Isaiah Ortega"],
                       ["Noemi Avila", "", "", "Edgar Camunez"])
        rows = [_raw("Sebastian Pedro Avellaneda", "11/11/2026", "FRELISHA JEFFERSON"),
                _raw("Sebastian Pedro Avellaneda", "11/11/2026", "FRELISHA JEFFERSON", "$15.00"),
                _raw("Aaron De La Torre", "11/11/2026", "JASON CALVERLY"),
                _raw("Rodolfo Bazan", "10/2/2026", "Noemi Avila")]
        R._TRANSFERS_NOTE.clear()
        moved = R._apply_transfers(rows, rules, where="test", log=quiet)
        self.assertEqual(moved, 3)
        self.assertEqual([r[1] for r in rows],
                         ["Jacob Isaiah Ortega", "Jacob Isaiah Ortega", "Aaron De La Torre", "Edgar Camunez"])
        self.assertEqual([r["hits"] for r in rules], [2, 1])
        self.assertEqual(len(R._TRANSFERS_NOTE), 3)
        self.assertIn("FRELISHA JEFFERSON (11/11/2026) Sebastian Pedro Avellaneda -> Jacob Isaiah Ortega",
                      R._TRANSFERS_NOTE)
        R._TRANSFERS_NOTE.clear()

    def test_rules_from_a_sheet_object_and_a_missing_tab(self):
        class _WS:
            def get_all_values(self):
                return [HDR, ["", "11/11/2026", "Sebastian Avellaneda", "Jacob Isaiah Ortega", "n", "11/11/2026", ""]]

        class _SH:
            def worksheet(self, title):
                assert title == R.TRANSFERS_TAB
                return _WS()
        self.assertEqual(len(R._transfer_rules(_SH(), log=quiet)), 1)
        self.assertEqual(R._TRANSFERS_RULES_N[0], 1)

        import gspread

        class _NoTab:
            def worksheet(self, title):
                raise gspread.WorksheetNotFound(title)
        self.assertEqual(R._transfer_rules(_NoTab(), log=quiet), [])
        self.assertEqual(R._TRANSFERS_RULES_N[0], 0)


if __name__ == "__main__":
    unittest.main()

"""Standing rep transfers off the 'Payroll Transfers' tab (Carlos 2026-11-11:
Jacob Ortega's sale under Sebastian's login pays Jacob when it posts).

  python -m unittest automations.vantura_payroll.test_transfers
"""
from __future__ import annotations

import datetime as dt
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


class SoldUnder(unittest.TestCase):
    """Carlos 2026-11-19: all of Esmeralda's sales the week of 11/16 are
    Jacob's -- a rule per customer off the order log, marked on the CS tab."""

    OL = [["Week Ending", "Pay Period", "Order Date", "Last Updated", "Rep", "Line", "Line Status", "Customer"],
          ["11/22/2026", "Pending", "11/19/2026", "", "Esmeralda Gonzalez", "1", "", "Ana Lopez"],
          ["11/22/2026", "Pending", "11/19/2026", "", "Esmeralda Gonzalez", "2", "", "Ana Lopez"],
          ["11/22/2026", "Pending", "11/20/2026", "", "Esmeralda Gonzalez", "1", "", "Bo Diaz"],
          ["11/15/2026", "Pending", "11/11/2026", "", "Esmeralda Gonzalez", "1", "", "Old Customer"],
          ["11/22/2026", "Pending", "11/19/2026", "", "Roseanna Jurado", "1", "", "Not Hers"]]

    def test_customers_in_range_once_each(self):
        got = R.sold_under_customers(self.OL, "Esmeralda Gonzalez",
                                       dt.date(2026, 11, 16), dt.date(2026, 11, 22))
        self.assertEqual(got, [("Ana Lopez", dt.date(2026, 11, 19)),
                               ("Bo Diaz", dt.date(2026, 11, 20))])

    def test_sync_adds_only_new_customers_and_only_when_writing(self):
        from unittest import mock
        tr = [["Customer", "Sale Date", "From Rep", "To Rep", "Note", "Added", "Last applied"],
              ["Ana Lopez", "", "Esmeralda Gonzalez", "Jacob Isaiah Ortega", "", "", ""]]
        ws_tr, ws_ol = mock.Mock(), mock.Mock()
        ws_tr.get_all_values.return_value = tr
        ws_ol.get_all_values.return_value = self.OL
        sh = mock.Mock()
        sh.worksheet.side_effect = lambda n: {"Payroll Transfers": ws_tr, "NDS Order Log": ws_ol}[n]
        rows = R.sync_sold_under(sh, write=False, log=lambda m: None, today=dt.date(2026, 11, 20))
        self.assertEqual([r[0] for r in rows], ["Bo Diaz"])
        self.assertEqual(rows[0][2:4], ["Esmeralda Gonzalez", "Jacob Isaiah Ortega"])
        ws_tr.append_rows.assert_not_called()
        R.sync_sold_under(sh, write=True, log=lambda m: None, today=dt.date(2026, 11, 20))
        ws_tr.append_rows.assert_called_once()
        # the rule it wrote moves the DD line, whatever week it lands in
        rule = R.rules_from_values([tr[0], rows[0]], log=lambda m: None)[0]
        self.assertTrue(R._transfer_matches(rule, "Esmeralda Gonzalez", "12/03/2026", "BO DIAZ"))
        self.assertFalse(R._transfer_matches(rule, "Roseanna Jurado", "12/03/2026", "BO DIAZ"))

    def test_the_commission_sheet_marks_the_moved_lines_only(self):
        hdr = ["Rep", "Brought In", "Commission", "Profit/Loss", "NPA's", "",
               "REP Name", "Sale Date", "Activation Date", "Description", "Product",
               "Description Detail", "Customer Name", "Total $ to ICD", "Commission"]
        mat = [["Pick", "11.29"] + [""] * 13, hdr,
               ["", "", "", "", "", "", "Jacob Isaiah Ortega", "11/19/2026", "", "OOF", "Port Line", "", "ANA LOPEZ", "$213", "$85"],
               ["", "", "", "", "", "", "Jacob Isaiah Ortega", "11/19/2026", "", "OOF", "Port Line", "", "HIS OWN", "$213", "$85"],
               ["", "", "", "", "", "", "Nicholas Smedra", "11/19/2026", "", "OOF", "Port Line", "", "SOMEONE", "$213", "$85"]]
        rules = [{"row": 2, "customer": "Ana Lopez", "sale_date": "", "from_rep": "Esmeralda Gonzalez",
                  "to_rep": "Jacob Isaiah Ortega", "hits": 0},
                 {"row": 5, "customer": "", "sale_date": "", "from_rep": "Nicholas Paul Smedra",
                  "to_rep": "Nicholas Smedra", "hits": 0}]
        self.assertEqual(R.moved_line_notes(mat, rules),
                         {2: "Moved from Esmeralda Gonzalez (sold under their login)"})

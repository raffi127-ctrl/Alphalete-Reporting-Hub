"""Credit Checks column on the ECO knocks board (Raf 2026-11-06). Offline."""
import json
import types
import unittest

from automations.icd_alerts import knocks_post as K, post as P
from automations.total_knocks import render as R


def _relay(records):
    row = [""] * (P.COL_SALES + 1)
    row[P.COL_OFFICE], row[P.COL_RECORDS] = "raf", json.dumps(records)
    return row


ATT = types.SimpleNamespace(key="raf", campaign="att")
KNOCKS = [{"Rep": "Chloe A. Johnson"}, {"Rep": "Cole Bollman"}]


class CreditChecksFor(unittest.TestCase):
    def test_sara_spelling_lands_on_the_knocks_row(self):
        out = K.credit_checks_for(ATT, _relay({"CHLOE JOHNSON": 2,
                                               "Cole Bollman": 1}), KNOCKS)
        self.assertEqual(out, {"Chloe A. Johnson": 2, "Cole Bollman": 1})

    def test_unmatched_rep_keeps_sara_name_so_total_is_whole(self):
        out = K.credit_checks_for(ATT, _relay({"NO AGENT NOTED": 3}), KNOCKS)
        self.assertEqual(out, {"NO AGENT NOTED": 3})

    def test_no_saraplus_or_no_relay_means_no_column(self):
        box = types.SimpleNamespace(key="x", campaign="b2b_box")
        self.assertIsNone(K.credit_checks_for(box, _relay({"A B": 1}), KNOCKS))
        self.assertIsNone(K.credit_checks_for(ATT, None, KNOCKS))

    def test_no_checks_yet_is_no_column_not_zeros(self):
        self.assertIsNone(K.credit_checks_for(ATT, _relay({}), KNOCKS))


class InsertColumn(unittest.TestCase):
    def test_after_hours_total_is_sara_total_band_sums_reps(self):
        cols = [R.COL_REP, R.COL_HRS_KNOCKING, R.COL_NO_ANSWER]
        disp = list(cols)
        table = [["OFFICE TOTAL", "", ""], ["TEAM", "", ""],
                 ["Cole Bollman", "", ""], ["Ana Griffin", "", ""]]
        R._insert_credit_column(cols, disp, table,
                                {"Cole Bollman": 2, "Ana Griffin": 3,
                                 "NO AGENT NOTED": 4},
                                n_extra=0, bands={1: [2, 3]})
        self.assertEqual(cols[2], R.COL_CREDIT_CHECKS)
        self.assertEqual([r[2] for r in table], ["9", "5", "2", "3"])


if __name__ == "__main__":
    unittest.main()

"""An Active-NO ICD on a leader's list is a real $0, not a missing row.

WE 10.25.26 (2026-10-29): the DD bulletin went out flagged "sent with data
gap(s)" for six ICDs (Ana Griffin, Cinthya Reyes, Lizette Ruiz, ...). Each has a
row on 'Org DDs Ongoing Report' — marked Active NO and $0 for weeks — but the
loader skips NO rows, so the podium read them as "no DD row".

    python -m unittest automations.override_bulletin.test_dd_inactive_listed
"""
from __future__ import annotations

import unittest

from automations.override_bulletin import dd_data as D
from automations.override_bulletin.test_dd_special_block import _WS, _this_week


def _load(gone_this_week):
    wk = _this_week()
    rows = [["ICD", "Active ICD", "Campaign", "ORG", "Total DD", wk, "8.30.26"]]
    for i in range(20):
        rows.append([f"Owner {i}", "YES", "ATT", "Carlos", "$120,000.00",
                     "$6,000.00", "$5,900.00"])
    rows.append(["Ana Griffin", "NO", "Costco", "Carlos", "$73,238.00",
                 gone_this_week, "$0.00"])
    rows.append(["Total - Raf", "", "", "", "$2,400,000.00",
                 "$120,000.00", "$118,000.00"])
    tree = [["PODIUM LEADERS"], ["Leader", "Loc"], ["Carlos Hidalgo", "TX"],
            [""], ["PODIUM ORG LISTS"], ["Leader", "ICD"],
            ["Carlos Hidalgo", "Owner 1"], ["Carlos Hidalgo", "Ana Griffin"],
            ["Carlos Hidalgo", "Nobody Atall"]]
    return D.load(ws=_WS(rows), tree_ws=_WS(tree), aliases={}, credico=False)


class InactiveListedTest(unittest.TestCase):
    def _gaps(self, d):
        return " ".join(d["blocking"])

    def test_inactive_zero_is_not_a_gap(self):
        for cell in ("", "$0.00"):
            self.assertNotIn("Ana Griffin", self._gaps(_load(cell)))

    def test_a_truly_missing_row_still_is(self):
        self.assertIn("Nobody Atall", self._gaps(_load("")))

    def test_inactive_with_money_this_week_still_flags(self):
        self.assertIn("Ana Griffin", self._gaps(_load("$500.00")))


if __name__ == "__main__":
    unittest.main()

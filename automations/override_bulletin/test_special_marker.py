"""Tests for the auto-set SPECIAL marker (`markers.set_marker` + its run.py call).

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.override_bulletin.test_special_marker

WHAT THESE GUARD (2026-10-02). run.py passed `write_week`'s return value — the
column LETTER "G" — to set_marker, which expects a 0-based index and died on
`"G" % 26`. run.py's try/except turned that into one quiet "auto-marker skipped"
line, so from 2026-08-01 on no special period ever got its red marker, and
without a marker the special is never placed: P8-2026 (WE 8.16.26) and P9-2026
(WE 9.13.26, Colten $33,745.60 + Carlos $272.55) both had to be fixed by hand.
"""
from __future__ import annotations

import inspect
import unittest

from automations.override_bulletin import markers as M
from automations.override_bulletin import run as R


class _WS:
    title = "Copy of Org Overrides Ongoing Report"

    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


def _tab():
    rows = [["ALL ORG OVERRIDES", "9.27.26", "9.20.26", "9.13.26"]]
    rows += [["x", "", "", ""] for _ in range(5)]
    rows.append(["Special Overrides", "", "", "P8-2026"])   # row 7 = annotation row
    return _WS(rows)


class SetMarkerColumn(unittest.TestCase):
    def test_index_and_letter_land_on_the_same_cell(self):
        ws = _tab()
        self.assertEqual(M.set_marker(ws, M.SPECIAL, "P9-2026", 3), "D7")
        self.assertEqual(M.set_marker(ws, M.SPECIAL, "P9-2026", "D"), "D7")

    def test_run_passes_the_column_index_not_write_weeks_letter(self):
        src = inspect.getsource(R.run)
        call = src[src.index("M.set_marker(ws, M.SPECIAL"):]
        call = call[:call.index(")") + 1]
        self.assertNotIn("prior, col,", call)
        self.assertIn("week_col", src[src.index("M.set_marker(ws, M.SPECIAL"):][:200])


class SpecialLedgerMatchTest(unittest.TestCase):
    """2026-10-16: a P10-2026 ledger line that was NOT a Special was placed as
    Carlos' Special ($7,890.63) before the real one existed. Only lines that
    say 'Special Override' count."""

    HDR = ["ICD Owner Name and OFFICE NAME", "NS_Explanation__c", "Transaction Amount"]

    def _amounts(self, rows):
        return M.amounts_for([self.HDR] + rows, M.SPECIAL, "P10-2026",
                             owner_col=self.HDR[0], expl_col=self.HDR[1],
                             amt_col=self.HDR[2])

    def test_other_p10_line_is_not_a_special(self):
        self.assertIsNone(self._amounts(
            [["Carlos Hidalgo", "P10-2026 Captain Override", "7890.63"]]))

    def test_special_line_still_counts(self):
        self.assertEqual(self._amounts(
            [["Carlos Hidalgo", "P10-2026 Captain Override", "7890.63"],
             ["Carlos Hidalgo", "P10-2026 Special Override", "300.10"]]),
            {M._norm_name("Carlos Hidalgo"): 300.10})


class P10LedgerOnlyColtenCarlosTest(unittest.TestCase):
    """2026-10-30: the P10-2026 Special lines also carried Rafael ($116,259.02)
    and Trang ($35,150.90). Summed in, $191,039 tripped the size guard on a
    $127,674 week and Colten/Carlos never landed. Only they take it from here."""

    HDR = SpecialLedgerMatchTest.HDR
    LEDGER = [
        ["Carlos Hidalgo (Alphalete Specialized Marketing, Inc.)",
         "P10-2026 Special Override - EDM", "343.85"],
        ["Colten Wright (South Shore Specialized Marketing, Inc.)",
         "P10-2026 Special Override - NDS", "39293.20"],
        ["Rafael Hidalgo (Alphalete Marketing, Inc.)",
         "P10-2026 Special Override - ATT", "115571.32"],
        ["", "P10-2026 Special Override - EDM", "687.70"],
        ["Trang Canavan (Fresh Success Marketing Group, Inc.)",
         "P10-2026 Special Override - RES-ATT", "35150.90"],
        ["Colten Wright (South Shore Specialized Marketing, Inc.)",
         "September 2026 Standard Overrides - Credico", "500.00"],
    ]

    def _plan(self, week_total):
        rows = [["ALL ORG OVERRIDES", "10.18.26", "10.11.26"],
                ["Total", "", str(week_total)]]
        ws = _WS(rows)
        mk = {"kind": M.SPECIAL, "period": "P10-2026", "row": 9, "col": 2,
              "week": "10.11.26", "pending": True}
        orig = M.read_markers
        M.read_markers = lambda _ws: [mk]
        try:
            return M.plan_placements(ws, [self.HDR] + self.LEDGER,
                                     owner_col=self.HDR[0], expl_col=self.HDR[1],
                                     amt_col=self.HDR[2])
        finally:
            M.read_markers = orig

    def test_only_colten_and_carlos_are_placed(self):
        to_place, pending, _orph, held = self._plan(127674.00)
        self.assertEqual(held, [])
        self.assertEqual(pending, [])
        self.assertEqual(to_place[0]["amounts"],
                         {"colten wright": 39293.20, "carlos hidalgo": 343.85})

    def test_credico_needs_the_full_label(self):
        self.assertEqual(
            M.amounts_for([self.HDR] + self.LEDGER, M.CREDICO, "P9-2026",
                          owner_col=self.HDR[0], expl_col=self.HDR[1],
                          amt_col=self.HDR[2]),
            {"colten wright": 500.00})
        # the period label alone must NOT pick up the Special line
        self.assertIsNone(
            M.amounts_for([self.HDR] + self.LEDGER, M.CREDICO, "P10-2026",
                          owner_col=self.HDR[0], expl_col=self.HDR[1],
                          amt_col=self.HDR[2]))


class SpecialAlsoLandsInAllOrgTest(unittest.TestCase):
    def test_special_is_added_to_the_all_org_cell(self):
        rows = [["ALL ORG OVERRIDES", "10.11.26"],
                ["Colten Wright", "25486.11"],          # row 2
                ["Colten Wright", "10109"],             # row 3 leader
                ["Captain Override", "10109"],          # row 4
                ["Special Override", ""]]               # row 5
        ws = _WS(rows)
        mk = {"kind": M.SPECIAL, "period": "P10-2026", "row": 9, "col": 1,
              "amounts": {"colten wright": 39293.20}}
        updates, _ = M.apply_placements(
            ws, [mk], roster={"colten wright": (2, True, "Colten Wright")},
            captains={"colten wright": {"total": 3, "captain": 4, "special": 5}})
        self.assertIn({"range": "B2", "values": [[64779.31]]}, updates)
        self.assertIn({"range": "B5", "values": [[39293.2]]}, updates)


class NextCredicoMarkerTest(unittest.TestCase):
    WEEKS = ["11.22.26", "11.15.26", "11.8.26", "11.1.26", "10.25.26", "10.18.26"]

    def test_five_weeks_after_the_last(self):
        mks = [{"kind": M.CREDICO, "period": "P9-2026", "week": "10.18.26"}]
        self.assertEqual(M.next_credico_marker(mks, self.WEEKS, "11.22.26"), "P10-2026")
        self.assertIsNone(M.next_credico_marker(mks, self.WEEKS, "11.15.26"))

    def test_december_rolls_to_january(self):
        mks = [{"kind": M.CREDICO, "period": "P12-2026", "week": "10.18.26"}]
        self.assertEqual(M.next_credico_marker(mks, self.WEEKS, "11.22.26"), "P1-2027")


if __name__ == "__main__":
    unittest.main()

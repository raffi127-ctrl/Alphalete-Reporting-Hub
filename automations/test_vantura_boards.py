"""vantura_boards — the one place that knows the three board tabs.

Pins the 2026-10-03 rename (Carlos): the AT&T program is NDS on the sheet
("NDS Sales Board", col L "NDS", subtotal "AT&T NDS"), the Verizon tab is
"Verizon Sales Board", and everything the sheet used to say — "B2B" rows,
the "AT&T (B2B)" subtotal, the "Sales Board" / "D2D Sales Board" titles — is
a legacy alias that still READS as the same board. Internal keys (program
"B2B") keep working through the same aliases.

Run:  python -m pytest automations/test_vantura_boards.py
"""
from __future__ import annotations

import unittest

from automations import vantura_boards as VB


class CanonCampaign(unittest.TestCase):
    def test_the_att_program_reads_as_nds_under_either_spelling(self):
        for raw in ("NDS", "nds", " Nds ", "B2B", "b2b", " B2B "):
            self.assertEqual(VB.canon_campaign(raw), "NDS", raw)

    def test_the_other_boards(self):
        self.assertEqual(VB.canon_campaign("Box"), "BOX")
        self.assertEqual(VB.canon_campaign("BOX"), "BOX")
        self.assertEqual(VB.canon_campaign("VERIZON"), "Verizon")
        self.assertEqual(VB.canon_campaign("verizon"), "Verizon")

    def test_unknown_labels_pass_through_stripped(self):
        self.assertEqual(VB.canon_campaign(" JE "), "JE")
        self.assertEqual(VB.canon_campaign("Base"), "Base")
        self.assertEqual(VB.canon_campaign(""), "")
        self.assertEqual(VB.canon_campaign(None), "")


class TabFor(unittest.TestCase):
    def test_program_b2b_lands_on_the_nds_tab(self):
        self.assertEqual(VB.tab_for("B2B"), "NDS Sales Board")
        self.assertEqual(VB.tab_for("NDS"), "NDS Sales Board")
        self.assertEqual(VB.BOARD_TABS["NDS"], "NDS Sales Board")
        self.assertEqual(VB.MAIN_TAB, "NDS Sales Board")

    def test_box_and_verizon(self):
        self.assertEqual(VB.tab_for("BOX"), "BOX Sales Board")
        self.assertEqual(VB.tab_for("Verizon"), "Verizon Sales Board")

    def test_unknown_or_blank_is_the_main_board(self):
        self.assertEqual(VB.tab_for(""), VB.MAIN_TAB)
        self.assertEqual(VB.tab_for("JE"), VB.MAIN_TAB)

    def test_campaign_of_knows_both_titles(self):
        self.assertEqual(VB.campaign_of("NDS Sales Board"), "NDS")
        self.assertEqual(VB.campaign_of("Sales Board"), "NDS")
        self.assertEqual(VB.campaign_of("Verizon Sales Board"), "Verizon")
        self.assertEqual(VB.campaign_of("D2D Sales Board"), "Verizon")
        self.assertEqual(VB.campaign_of("BOX Sales Board"), "BOX")
        self.assertEqual(VB.campaign_of("WeekData"), "")

    def test_every_title_is_in_the_protected_list(self):
        for t in ("NDS Sales Board", "BOX Sales Board", "Verizon Sales Board",
                  "Sales Board", "D2D Sales Board"):
            self.assertIn(t, VB.ALL_BOARD_TABS)


class StatLabels(unittest.TestCase):
    def test_new_and_old_subtotal_labels_end_the_block(self):
        for label in ("AT&T NDS", "at&t nds", "AT&T (B2B)", "BOX", "Verizon",
                      "TOTAL"):
            self.assertTrue(VB.is_stat_label(label), label)
        self.assertFalse(VB.is_stat_label("Diego Borres"))
        self.assertEqual(VB.SUBTOTAL_LABELS["NDS"], "AT&T NDS")


HDR = ["#", "REP", "Current Week", "Last Wk", "Monday", "Tuesday",
       "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Campaign",
       "Trainer", "Field Status", "Team", "Leadership Status"]


def _grid(col_l, label):
    return [
        [""], ["WE", "10.4"], [""], HDR,
        ["1", "Ann", "3", "1", "1", "2", "", "", "", "", "", col_l, "Nico",
         "3rd Wk", "", "Entry Level"],
        [],
        ["2", "Bob", "0", "4", "", "", "", "", "", "", "", col_l, "Nico",
         "1st Wk", "", "In Training"],
        ["48", label, "3", "5", "1", "2", "", "", "", "", "", col_l],
        ["50", "TOTAL", "3", "5"],
        ["52", "% on the Board"],
        ["53", "All AT&T NDS Reps", "0"],
    ]


class ParseBoard(unittest.TestCase):
    def test_today_s_board(self):
        reps = VB.parse_board(_grid("NDS", "AT&T NDS"), tab="NDS Sales Board")
        self.assertEqual([r["name"] for r in reps], ["Ann", "Bob"])
        self.assertEqual([r["row"] for r in reps], [5, 7])
        self.assertEqual({r["campaign"] for r in reps}, {"NDS"})
        self.assertEqual({r["campaign_raw"] for r in reps}, {"NDS"})
        self.assertEqual(reps[0]["days"], ["1", "2", "", "", "", "", ""])
        self.assertEqual(reps[0]["lead"], "Entry Level")
        self.assertEqual(VB.stat_row(_grid("NDS", "AT&T NDS")), 8)

    def test_the_backup_copy_from_before_the_rename(self):
        """Col L "B2B", subtotal "AT&T (B2B)": same reps, same block end,
        campaign canonicalised to NDS with the raw spelling kept."""
        reps = VB.parse_board(_grid("B2B", "AT&T (B2B)"), tab="Sales Board")
        self.assertEqual([r["name"] for r in reps], ["Ann", "Bob"])
        self.assertEqual({r["campaign"] for r in reps}, {"NDS"})
        self.assertEqual({r["campaign_raw"] for r in reps}, {"B2B"})
        self.assertEqual(VB.stat_row(_grid("B2B", "AT&T (B2B)")), 8)


class _WS:
    def __init__(self, title, grid=None, b2=""):
        self.title, self._grid, self._b2 = title, grid or [], b2

    def get(self, _rng, **_kw):
        return self._grid

    def acell(self, _a1):
        class _C:
            value = self._b2
        return _C()


class _Sheet:
    def __init__(self, *titles):
        self._ws = {t: _WS(t, _grid("NDS", "AT&T NDS"), b2="10.4")
                    for t in titles}

    def worksheet(self, title):
        if title not in self._ws:
            raise KeyError(title)          # gspread raises WorksheetNotFound
        return self._ws[title]


class BoardWs(unittest.TestCase):
    def test_today_s_titles_win(self):
        sh = _Sheet("NDS Sales Board", "BOX Sales Board", "Verizon Sales Board")
        self.assertEqual(VB.board_ws(sh, "B2B").title, "NDS Sales Board")
        self.assertEqual(VB.board_ws(sh, "NDS").title, "NDS Sales Board")
        self.assertEqual(VB.board_ws(sh, "Verizon").title, "Verizon Sales Board")
        self.assertEqual(VB.board_ws(sh, "D2D Sales Board").title,
                         "Verizon Sales Board")
        self.assertEqual(VB.week_label(sh), "10.4")

    def test_a_board_not_renamed_yet_is_found_under_its_old_title(self):
        sh = _Sheet("Sales Board", "BOX Sales Board", "D2D Sales Board")
        self.assertEqual(VB.board_ws(sh, "NDS").title, "Sales Board")
        self.assertEqual(VB.board_ws(sh, "NDS Sales Board").title, "Sales Board")
        self.assertEqual(VB.board_ws(sh, "Verizon").title, "D2D Sales Board")
        reps = VB.all_reps(sh)
        self.assertEqual(sorted({r["tab"] for r in reps}),
                         ["BOX Sales Board", "D2D Sales Board", "Sales Board"])
        self.assertEqual(len(reps), 6)
        self.assertEqual(VB.week_label(sh), "10.4")

    def test_a_missing_board_raises_and_all_reps_skips_it(self):
        sh = _Sheet("NDS Sales Board")
        with self.assertRaises(KeyError):
            VB.board_ws(sh, "BOX")
        self.assertEqual([r["tab"] for r in VB.all_reps(sh)],
                         ["NDS Sales Board", "NDS Sales Board"])

    def test_a_non_board_tab_is_a_plain_lookup(self):
        sh = _Sheet("NDS Sales Board", "WeekData")
        self.assertEqual(VB.board_ws(sh, "WeekData").title, "WeekData")


if __name__ == "__main__":
    unittest.main()

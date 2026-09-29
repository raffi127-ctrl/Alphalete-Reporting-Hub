"""Carlos's reps sell under Raf's SaraPlus code; Raf's board is not theirs.

Raf, 2026-09-29: "can we make it where carlos's reps that are selling in my
code don't get added to my sales board please?" — with Jorge Gramajo on the
sold list and 'Unassigned: 1' under the team lines, which is what one of
Carlos's reps looks like from his side: a sale on his board, on nobody's team.

ONE ROSTER. These are the same fourteen the knock boards split on
(total_knocks.guests.GUEST_REPS) — the point of the test is that the sales
board reads that list rather than keeping a second one.

    .venv/bin/python -m unittest automations.alphalete_sales_board.test_guest_reps
"""
from __future__ import annotations

import unittest

from automations.alphalete_sales_board import calc
from automations.alphalete_sales_board import times_of_sales as TOS

BOARD = ["Benjamin Kushpit", "Zoria Johnson", "Jorge Gramajo"]


def agent(name, **kw):
    a = {"name": name, "internet_sales": 0, "internet_upgrades": 0,
         "aia_sales": 0, "dtv_streaming": 0, "wireless_lines_sold": 0}
    a.update(kw)
    return a


class OffTheBoard(unittest.TestCase):
    def test_a_guest_is_not_counted_even_with_a_row_on_the_board(self):
        out, notes, missing = calc.calculate(
            [agent("JORGE GRAMAJO", wireless_lines_sold=1)], BOARD)
        self.assertEqual(out, [])
        # NOT 'missing' either — a missing rep is a paperwork problem somebody
        # is asked to fix on every sweep, and this is a decision.
        self.assertEqual(missing, [])
        self.assertIn("Carlos Hidalgo's rep", " ".join(notes))

    def test_an_ownerville_spelling_with_a_middle_name_still_matches(self):
        out, _n, missing = calc.calculate(
            [agent("JOSE MANUEL PIMENTEL LUGO", internet_sales=1)], BOARD)
        self.assertEqual(out, [])
        self.assertEqual(missing, [])

    def test_the_office_s_own_reps_are_untouched(self):
        out, _n, _m = calc.calculate(
            [agent("BENJAMIN KUSHPIT", wireless_lines_sold=4),
             agent("ZORIA JOHNSON", internet_sales=1, wireless_lines_sold=1)],
            BOARD)
        self.assertEqual(sorted(r["board_name"] for r in out),
                         ["Benjamin Kushpit", "Zoria Johnson"])

    def test_a_similar_name_is_not_swept_up(self):
        # 'Luis Valenzuela' shares a first name with the roster's 'Luis
        # Servellon' and nothing else. A sale dropped in error is invisible to
        # everyone; one left on the board is visible and gets corrected.
        out, _n, _m = calc.calculate(
            [agent("LUIS VALENZUELA", internet_sales=1)],
            BOARD + ["Luis Valenzuela"])
        self.assertEqual([r["board_name"] for r in out], ["Luis Valenzuela"])

    def test_the_times_of_sales_pace_leaves_them_out_too(self):
        # Off the SAME sweep: the snapshot and the board's TOTALS must not
        # disagree by exactly those sales.
        both = [agent("BENJAMIN KUSHPIT", wireless_lines_sold=4),
                agent("JORGE GRAMAJO", wireless_lines_sold=1)]
        self.assertEqual(TOS.totals(both)["total_units"], 4)
        self.assertEqual(TOS.totals(both[:1])["total_units"], 4)


if __name__ == "__main__":
    unittest.main()

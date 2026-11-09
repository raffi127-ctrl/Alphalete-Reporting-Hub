import datetime as dt
import unittest

from automations.verizon_office import nico_sheet as N

BOARD = [["", "Nov 7, 2026"], ["#", "REP"], ["1", "Diego Chacon"], ["2", "Will Bautista"],
         ["3", "Brandy Samantha Ahumada Ruiz"], ["4", "Richard Bautista"], ["", "TEAM SALES"]]
HIST = [[""]] * 4 + [["2026-11-06", "Brandy Samantha Ahumada Ruiz", "4", "", "", "", "samantha", "Included"],
                     ["2026-11-09", "Diego Chacon", "2", "", "", "", "chacon", "Included"]]


def post(ts_local, text):
    when = dt.datetime(2026, 11, 9, *ts_local, tzinfo=N.T.TZ)
    return {"ts": "%.6f" % when.timestamp(), "user": "U1", "text": text}


class PlanTest(unittest.TestCase):
    def test_only_new_highs_appended_names_as_on_board(self):
        msgs = [post((13, 0), "Verizon :fire:\nCHACON :drop_of_blood::drop_of_blood:\nSAMANTHA :drop_of_blood:"),
                post((14, 0), "Verizon :fire:\nCHACON :drop_of_blood::drop_of_blood::drop_of_blood:\n"
                              "SAMANTHA :drop_of_blood:\nBAUTISTA :drop_of_blood:")]
        rows, problems = N.plan(dt.date(2026, 11, 9), msgs, BOARD, HIST)
        self.assertEqual([(r[1], r[2]) for r in rows],
                         [("Brandy Samantha Ahumada Ruiz", "1"), ("Diego Chacon", "3")])
        # BAUTISTA is two board reps with no label history -> reported, not guessed
        self.assertEqual(len(problems), 1)
        self.assertIn("BAUTISTA", problems[0])
        self.assertEqual(rows[0][7], "Included")

    def test_board_names_stop_at_rep_block(self):
        self.assertEqual(N.board_names(BOARD)[-1], "Richard Bautista")


if __name__ == "__main__":
    unittest.main()

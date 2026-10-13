import datetime as dt
import unittest

from automations.sales_board_fixer import tenure as T

D = dt.date


def board(reps):
    """C name, E/F MON Apps/Int, G Location (end of the filter), then
    H '# Days Worked', I 'Start Date', J 'Termination Date', K 'ATTUID' (row 3).
    reps = [(name, start shown, days formula)]."""
    hdr1 = ["", "", "", "", "MON", "", "Location", "# Days Worked", "Start Date",
            "Termination Date", ""]
    hdr3 = ["", "#", "Name", "", "Apps", "Int", "REP", "REP", "REP", "REP", "ATTUID"]
    vals, fx = [hdr1, [""] * 11, hdr3], [hdr1, [""] * 11, hdr3]
    for i, (name, start, days) in enumerate(reps):
        row = ["", str(i + 1), name, "", "0", "", "", "", start, "", ""]
        vals.append(row)
        fx.append(row[:7] + [days] + row[8:])
    vals.append(["", "", "TOTALS"] + [""] * 8)
    fx.append(["", "", "TOTALS"] + [""] * 8)
    return vals, fx


FILTER = {"range": {"sheetId": 1, "startRowIndex": 2, "endRowIndex": 20,
                    "startColumnIndex": 2, "endColumnIndex": 7},
          "sortSpecs": [{"dimensionIndex": 3, "sortOrder": "DESCENDING"}]}


class Filter(unittest.TestCase):
    def test_widens_to_the_last_rep_column_and_keeps_the_sort(self):
        v, _ = board([("Ana", "", "")] * 6)
        (x,) = T.check_filter("t", 1, v, FILTER)
        bf = x.request["setBasicFilter"]["filter"]
        self.assertEqual(bf["range"]["endColumnIndex"], 11)       # through K (ATTUID)
        self.assertEqual(bf["sortSpecs"], FILTER["sortSpecs"])
        self.assertEqual(x.after, "C..K")

    def test_already_wide_is_quiet(self):
        v, _ = board([("Ana", "", "")] * 6)
        wide = dict(FILTER, range=dict(FILTER["range"], endColumnIndex=11))
        self.assertEqual(T.check_filter("t", 1, v, wide), [])


class TrueStart(unittest.TestCase):
    EARLIEST = D(2026, 6, 7)

    def test_wk_tag_wins(self):
        # Irwin, 2026-10-13: 'Irwin (Wk 3)' on WE 10.11 -> Mon 10/5 - 2 weeks = 9/21,
        # whatever shuffled date sat in his row
        h = [(D(2026, 9, 27), None, "Irwin"),
             (D(2026, 10, 4), D(2026, 8, 17), "Irwin"),
             (D(2026, 10, 11), D(2026, 8, 10), "Irwin (Wk 3)"),
             (D(2026, 10, 18), D(2026, 1, 14), "Irwin")]
        self.assertEqual(T.true_start(h, self.EARLIEST)[0], D(2026, 9, 21))

    def test_held_tuesday_start_inside_the_wk_week_is_kept(self):
        # Zoria: '(Wk 2)' on WE 6.21 says week of 6/8; the board held 6/9 for months
        h = ([(D(2026, 6, 14), D(2026, 6, 9), "Zoria"), (D(2026, 6, 21), D(2026, 6, 9), "Zoria (Wk 2)")]
             + [(D(2026, 6, 28) + dt.timedelta(weeks=i), D(2026, 6, 9), "Zoria") for i in range(4)])
        self.assertEqual(T.true_start(h, self.EARLIEST)[0], D(2026, 6, 9))

    def test_long_held_date_beats_the_shuffle(self):
        h = ([(D(2026, 6, 7) + dt.timedelta(weeks=i), D(2026, 4, 20), "Ben")
              for i in range(10)]
             + [(D(2026, 9, 20), D(2026, 8, 31), "Ben"),
                (D(2026, 9, 27), D(2026, 8, 31), "Ben")])
        self.assertEqual(T.true_start(h, self.EARLIEST)[0], D(2026, 4, 20))

    def test_newcomer_without_a_streak_gets_first_monday(self):
        h = [(D(2026, 9, 27), D(2026, 1, 14), "Kim"), (D(2026, 10, 4), D(2026, 8, 3), "Kim")]
        self.assertEqual(T.true_start(h, self.EARLIEST)[0], D(2026, 9, 21))

    def test_stuck_wrong_streak_far_from_first_week_is_ignored(self):
        h = [(D(2026, 9, 27) + dt.timedelta(weeks=i), D(2026, 6, 1), "Lo") for i in range(4)]
        self.assertEqual(T.true_start(h, self.EARLIEST)[0], D(2026, 9, 21))

    def test_on_the_first_tab_with_no_streak_is_unknown(self):
        h = [(self.EARLIEST, D(2026, 3, 2), "Old"), (D(2026, 6, 14), D(2026, 5, 1), "Old")]
        self.assertIsNone(T.true_start(h, self.EARLIEST)[0])


class Fixes(unittest.TestCase):
    def test_start_and_days_go_on_the_reps_own_row(self):
        v, f = board([("Rep %d" % i, "6/1/2026", "=IF(J%d=0,TODAY()-I%d,J%d-I%d)" % ((4 + i,) * 4))
                      for i in range(5)]
                     + [("Irwin", "1/14/2026", ""), ("No Start", "", "")])
        hist = {"rep %d" % i: [(D(2026, 6, 7) + dt.timedelta(weeks=w), D(2026, 6, 1), "Rep %d" % i)
                                for w in range(5)] for i in range(5)}
        hist["irwin"] = [(D(2026, 9, 27), None, "Irwin")]
        found = T.audit("t", 1, v, f, None, hist, D(2026, 6, 7))
        got = {(x.kind, x.where): x.value for x in found}
        self.assertEqual(got, {("start_date_moved", "I9"): "9/21/2026",
                               ("days_formula", "H9"): "=IF(J9=0,TODAY()-I9,J9-I9)"})


if __name__ == "__main__":
    unittest.main()

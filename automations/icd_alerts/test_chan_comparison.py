"""Chan's comparison line has to carry what the board actually draws.

2026-09-17. Megan, on Aya's board and then Cyrus's and then Kash's: "Chan is
missing some of the info in the compare line". All three showed the same teal
row, because all three read the same cached line:

    1 of 1   CHAN M-F AVG TOTAL   3856  6979   (blank)  6979.0  0  0.0%  0.0 ...

Two faults in one row:

  IT WAS ONE ROW. The renderer counts ROWS for "# Reps" and divides the
  per-rep columns by that count -- so Chan read as a single rep who knocked
  6,979 doors, and "Avg Doors / Rep" printed his whole week.

  IT CARRIED ONLY COUNTS. Only TP.COUNT_COLUMNS were summed, and that list
  was written for disposition columns. So Total Talk to showed 0 while Talk
  To - Not Int showed 965, First/Last Knock were blank, Gaps was 0, and
  Avg Knocks / Hr -- derived from the times -- was blank too.
"""
from __future__ import annotations

import unittest

from automations.icd_alerts import chan as C
from automations.total_knocks import pull as TP


def _rep(knocks=100, talk=10, first="1:00 PM", last="7:00 PM",
         gaps=2, gapmin=30, sale=1):
    return {TP.COL_TOTAL_KNOCKS: str(knocks), TP.COL_TOTAL_TALK_TO: str(talk),
            TP.COL_FIRST_KNOCK: first, TP.COL_LAST_KNOCK: last,
            TP.COL_GAPS: str(gaps), TP.COL_TOTAL_GAPS: str(gapmin),
            TP.COL_SALE: str(sale)}


def _week(reps_per_day):
    return {"d%d" % i: [_rep() for _ in range(n)]
            for i, n in enumerate(reps_per_day)}


class TheRowCountIsChansRepCountTest(unittest.TestCase):
    def test_one_row_per_averaged_rep(self):
        """The '1 of 1' bug: the renderer counts rows, so one row is one rep
        and his whole week lands in Avg Doors / Rep."""
        by_day = _week([4, 6])
        rows = C._average_rows(by_day, list(by_day))
        self.assertEqual(len(rows), 5)

    def test_the_rows_sum_to_the_daily_average(self):
        """Splitting across reps must not change the total the board draws."""
        by_day = _week([4, 6])          # 10 rep-days, 100 knocks each
        rows = C._average_rows(by_day, list(by_day))
        total = sum(int(r[TP.COL_TOTAL_KNOCKS]) for r in rows)
        self.assertEqual(total, 500)    # 1000 over two days

    def test_a_remainder_is_not_lost(self):
        """Integer division across reps must still sum to the average."""
        by_day = {"d0": [_rep(knocks=101) for _ in range(3)]}
        rows = C._average_rows(by_day, ["d0"])
        self.assertEqual(sum(int(r[TP.COL_TOTAL_KNOCKS]) for r in rows), 303)

    def test_never_zero_rows(self):
        by_day = {"d0": [_rep()]}
        self.assertEqual(len(C._average_rows(by_day, ["d0"])), 1)

    def test_no_days_is_no_comparison(self):
        self.assertEqual(C._average_rows({}, ["d0"]), [])


class TheRowCarriesEveryDrawnColumnTest(unittest.TestCase):
    def setUp(self):
        by_day = _week([2, 2])
        self.rows = C._average_rows(by_day, list(by_day))

    def test_total_talk_to_is_carried(self):
        """It read 0 while Talk To - Not Int read 965, which is impossible."""
        self.assertEqual(
            sum(int(r[TP.COL_TOTAL_TALK_TO]) for r in self.rows), 20)

    def test_gaps_are_carried(self):
        self.assertEqual(sum(int(r[TP.COL_GAPS]) for r in self.rows), 4)
        self.assertEqual(sum(int(r[TP.COL_TOTAL_GAPS]) for r in self.rows), 60)

    def test_first_and_last_knock_are_carried(self):
        self.assertEqual(self.rows[0][TP.COL_FIRST_KNOCK], "1:00 PM")
        self.assertEqual(self.rows[0][TP.COL_LAST_KNOCK], "7:00 PM")

    def test_dispositions_still_work(self):
        self.assertEqual(sum(int(r[TP.COL_SALE]) for r in self.rows), 2)


class TimesAverageAndSurviveWindowsTest(unittest.TestCase):
    def test_the_mean_not_the_extreme(self):
        """One rep starting at 8am on one Tuesday must not become Chan's
        first knock for the week."""
        self.assertEqual(C._avg_time(["1:00 PM", "3:00 PM"]), "2:00 PM")

    def test_noon_and_midnight_read_correctly(self):
        self.assertEqual(C._avg_time(["12:30 PM"]), "12:30 PM")
        self.assertEqual(C._avg_time(["12:00 AM"]), "12:00 AM")

    def test_unparsable_is_blank_not_a_crash(self):
        self.assertEqual(C._avg_time([]), "")
        self.assertEqual(C._avg_time(["", "  ", "not a time"]), "")

    def test_no_platform_specific_strftime(self):
        """%-I does not exist on Windows and ICD machines include PCs -- it
        would raise there and cost the comparison on boards nobody here sees."""
        import inspect
        src = inspect.getsource(C._avg_time)
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        self.assertNotIn("%-I", code)
        self.assertNotIn("%-H", code)


if __name__ == "__main__":
    unittest.main()

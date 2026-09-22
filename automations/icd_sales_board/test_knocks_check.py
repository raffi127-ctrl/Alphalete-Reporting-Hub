"""What the knocks history check does and does not cry about. No network."""
import datetime as dt
import unittest

from automations.icd_sales_board import knocks_check as KC

HDR = ["Date", "Office", "Rep", "Total Knocks"]
TODAY = dt.date(2026, 9, 22)          # a Tuesday


def rows(office, pairs):
    return [[d.isoformat(), office, "R", str(n)] for d, n in pairs]


def weekdays(start, n, per_day):
    """n days back from `start`, skipping Sundays."""
    out, d = [], start
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() != 6:
            out.append((d, per_day))
    return out


class ShortDayTests(unittest.TestCase):
    def test_a_weekend_day_is_judged_against_weekends(self):
        # THE FIRST VERSION'S BUG: comparing every day to the office's recent
        # days flagged 15 of 19 offices, all of them weekend days measured
        # against midweek. Saturdays here are consistently a third of midweek
        # and must not be called short.
        pairs = []
        for i in range(1, 29):
            d = TODAY - dt.timedelta(days=i)
            if d.weekday() == 6:
                continue
            pairs.append((d, 300 if d.weekday() == 5 else 900))
        got = KC.check(TODAY, [HDR] + rows("Cyrus Wade", pairs))
        self.assertEqual(got, [])

    def test_a_genuine_collapse_is_flagged(self):
        pairs = weekdays(TODAY, 20, 900)
        pairs[0] = (pairs[0][0], 100)          # yesterday, way down
        got = KC.check(TODAY, [HDR] + rows("Cyrus Wade", pairs))
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["Short"])

    def test_small_numbers_are_left_alone(self):
        # 44 against a usual 60 is a big ratio and nothing at all in reality.
        pairs = weekdays(TODAY, 20, 60)
        pairs[0] = (pairs[0][0], 5)
        self.assertEqual(KC.check(TODAY, [HDR] + rows("Nii", pairs)), [])

    def test_one_comparable_day_is_not_enough_to_judge(self):
        d1 = TODAY - dt.timedelta(days=1)
        d2 = TODAY - dt.timedelta(days=8)
        got = KC.check(TODAY, [HDR] + rows("New Office", [(d2, 900), (d1, 10)]))
        self.assertEqual(got, [])


class MissingDayTests(unittest.TestCase):
    def test_a_missing_workday_is_flagged(self):
        pairs = [p for p in weekdays(TODAY, 20, 900)
                 if p[0] != TODAY - dt.timedelta(days=1)]
        got = KC.check(TODAY, [HDR] + rows("Cyrus Wade", pairs))
        self.assertEqual(got[0]["Missing"], [TODAY - dt.timedelta(days=1)])

    def test_a_sunday_nobody_works_is_not_missing(self):
        got = KC.check(TODAY, [HDR] + rows("Cyrus Wade",
                                           weekdays(TODAY, 20, 900)))
        self.assertEqual(got, [])

    def test_one_stray_sunday_does_not_make_every_sunday_expected(self):
        # 'any prior same-weekday' called four offices missing a day on a
        # Sunday they had simply not gone out.
        pairs = weekdays(TODAY, 20, 900)
        pairs.append((dt.date(2026, 9, 6), 40))      # one lone Sunday
        got = KC.check(TODAY, [HDR] + rows("Cyrus Wade", pairs))
        self.assertEqual([r for r in got if r["Missing"]], [])


class LineTests(unittest.TestCase):
    def test_a_clean_office_says_nothing(self):
        grid = [HDR] + rows("Cyrus Wade", weekdays(TODAY, 20, 900))
        self.assertEqual(KC.line_for("Cyrus Wade", TODAY, grid), "")

    def test_the_line_names_the_day(self):
        pairs = [p for p in weekdays(TODAY, 20, 900)
                 if p[0] != TODAY - dt.timedelta(days=1)]
        line = KC.line_for("Cyrus Wade", TODAY, [HDR] + rows("Cyrus Wade", pairs))
        self.assertIn("Mon", line)
        self.assertIn("21", line)

    def test_it_finds_an_office_filed_under_a_longer_name(self):
        grid = [HDR] + rows("Next Horizon Group, Inc. Nii Tagoe",
                            [p for p in weekdays(TODAY, 20, 900)
                             if p[0] != TODAY - dt.timedelta(days=1)])
        self.assertIn("no knocks logged", KC.line_for("Nii Tagoe", TODAY, grid))

    def test_a_bad_grid_is_silence_not_a_crash(self):
        self.assertEqual(KC.check(TODAY, [["nonsense"]]), [])
        self.assertEqual(KC.line_for("Anyone", TODAY, []), "")


if __name__ == "__main__":
    unittest.main()

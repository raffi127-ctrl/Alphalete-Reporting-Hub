"""The day slicing is the whole risk in the cross-check.

p=701 runs Sun-Sat and recruiting runs Sat-Fri, so assembling one recruiting
week means taking the tail of one AppStream week and the head of the next. An
off-by-one there would either drop a day or count one twice — and it would
show up as a MISMATCH blamed on the pull, which is the opposite of what this
report is for."""
import datetime as dt
import unittest

import automations.sms_audit.crosscheck as C
from automations.sms_audit.crosscheck import _slices, totals


class SliceTest(unittest.TestCase):

    def days(self, lo, hi):
        out = []
        for sun, idxs in _slices(lo, hi):
            out.extend(sun + dt.timedelta(days=i) for i in idxs)
        return out

    def test_the_slices_are_exactly_the_recruiting_week(self):
        lo, hi = dt.date(2026, 9, 19), dt.date(2026, 9, 25)
        got = self.days(lo, hi)
        want = [lo + dt.timedelta(days=n) for n in range(7)]
        self.assertEqual(got, want)

    def test_seven_days_with_nothing_counted_twice(self):
        lo, hi = dt.date(2026, 9, 19), dt.date(2026, 9, 25)
        got = self.days(lo, hi)
        self.assertEqual(len(got), 7)
        self.assertEqual(len(set(got)), 7)

    def test_it_opens_on_the_saturday_and_closes_on_the_friday(self):
        lo, hi = dt.date(2026, 8, 15), dt.date(2026, 8, 21)
        got = self.days(lo, hi)
        self.assertEqual(got[0], lo)
        self.assertEqual(got[0].strftime("%a"), "Sat")
        self.assertEqual(got[-1], hi)
        self.assertEqual(got[-1].strftime("%a"), "Fri")

    def test_every_slice_starts_on_a_sunday(self):
        # p=701 is indexed from Sunday; a non-Sunday start would silently
        # shift all seven columns
        for sun, _idxs in _slices(dt.date(2026, 9, 19), dt.date(2026, 9, 25)):
            self.assertEqual(sun.weekday(), 6, sun)

    def test_it_holds_across_a_month_boundary(self):
        lo, hi = dt.date(2026, 8, 29), dt.date(2026, 9, 4)
        self.assertEqual(self.days(lo, hi),
                         [lo + dt.timedelta(days=n) for n in range(7)])


class TotalTest(unittest.TestCase):

    def test_it_sums_only_the_named_days_over_every_recruiter(self):
        parsed = {"A": {"Sch": [0, 1, 2, 3, 4, 5, 6], "SU": [0] * 7},
                  "B": {"Sch": [10, 0, 0, 0, 0, 0, 100], "SU": [1] * 7}}
        # Sch: A's Sat is 6, B's is 100.  SU: only B has any, 1 a day.
        self.assertEqual(totals(parsed, [6]), (106, 1))
        self.assertEqual(totals(parsed, [0, 1]), (11, 2))

    def test_a_recruiter_missing_a_section_counts_as_zero_not_a_crash(self):
        self.assertEqual(totals({"A": {"Sch": [1] * 7}}, [0]), (1, 0))


if __name__ == "__main__":
    unittest.main()


class OursReadsTheRightWeekTest(unittest.TestCase):
    """The cross-check compared AppStream's week 1 against whatever sat in the
    UNSUFFIXED local file, which a backfill leaves holding the last week
    pulled. It reported "11580 booked: AppStream 373 vs ours 281" — two
    different weeks, a mismatch invented by reading the wrong file. A
    cross-check that cries wolf is worse than none."""

    LO, HI = dt.date(2026, 9, 19), dt.date(2026, 9, 25)

    def _patch(self, recs, seen):
        def fake(office, suffix=""):
            seen.append(suffix)
            return recs.get(suffix, []), "file[{}]".format(suffix)
        return fake

    def test_it_asks_for_the_weeks_own_tag_first(self):
        seen = []
        recs = {"w0925": [{"date": "09-22-2026", "status": "Showed Up"}]}
        C.A.load_office = self._patch(recs, seen)
        booked, shown, _src = C.ours("11580", self.LO, self.HI)
        self.assertEqual(seen[0], "w0925")
        self.assertEqual((booked, shown), (1, 1))

    def test_a_file_from_another_week_is_refused_not_compared(self):
        recs = {"": [{"date": "08-18-2026", "status": "Showed Up"}]}
        C.A.load_office = self._patch(recs, [])
        booked, shown, why = C.ours("11580", self.LO, self.HI)
        self.assertIsNone(booked)
        self.assertIsNone(shown)
        self.assertIn("not this week", why)

    def test_no_show_does_not_count_as_shown(self):
        recs = {"w0925": [{"date": "09-22-2026", "status": "No Show"},
                          {"date": "09-23-2026", "status": "Showed Up"}]}
        C.A.load_office = self._patch(recs, [])
        booked, shown, _ = C.ours("11580", self.LO, self.HI)
        self.assertEqual((booked, shown), (2, 1))

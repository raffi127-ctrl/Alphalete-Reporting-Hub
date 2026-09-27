"""The day slicing is the whole risk in the cross-check.

p=701 runs Sun-Sat and recruiting runs Sat-Fri, so assembling one recruiting
week means taking the tail of one AppStream week and the head of the next. An
off-by-one there would either drop a day or count one twice — and it would
show up as a MISMATCH blamed on the pull, which is the opposite of what this
report is for."""
import datetime as dt
import unittest

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

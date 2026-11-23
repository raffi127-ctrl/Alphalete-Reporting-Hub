"""A shape is not a value.

2026-11-23, Lioney Garcia: her packet's date of birth read "5/27/2026" --
six months ago, a newborn -- and it was queued to be typed onto a payroll
record. Every check passed, because every check was about punctuation.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.apex_new_starts.blueink_data import _impossible_dob as why


class ADateOfBirthHasToBePossible(unittest.TestCase):

    def test_the_one_that_got_through(self):
        said = why("5/27/2026")
        self.assertTrue(said)
        self.assertIn("not a birth date", said)

    def test_a_date_in_the_future_is_refused(self):
        ahead = dt.date.today() + dt.timedelta(days=400)
        self.assertIn("future", why(ahead.strftime("%m/%d/%Y")))

    def test_real_birthdays_pass(self):
        """The two people this ran against today. A false alarm on a real
        birthday costs somebody their first day."""
        for ok in ("8/1/2007", "4/23/2004", "2/13/2006", "6/5/2008"):
            self.assertEqual(why(ok), "", ok)

    def test_the_bounds_are_wide_on_purpose(self):
        """This is not a view about who may work here -- it is the
        difference between a birth date and a field read off the wrong
        line."""
        just_old_enough = dt.date.today() - dt.timedelta(days=int(365.25 * 15))
        self.assertEqual(why(just_old_enough.strftime("%m/%d/%Y")), "")

    def test_somebody_impossibly_old_is_refused(self):
        self.assertIn("over 100", why("1/1/1890"))

    def test_a_date_we_cannot_read_is_let_through(self):
        """The shape rule has already passed by this point, so an unparsed
        value is a format we do not know rather than a wrong date. Refusing
        it would be a false alarm, which costs a real person a real day."""
        self.assertEqual(why("not a date"), "")
        self.assertEqual(why(""), "")

    def test_the_reason_is_returned_not_just_a_verdict(self):
        """The person's row has to say WHAT was wrong, or somebody opens the
        packet looking for a problem nobody described."""
        self.assertIn("0 years old", why("5/27/2026"))


class ItIsOnlyAskedOfTheBirthDate(unittest.TestCase):

    def test_the_check_is_wired_to_dob_alone(self):
        import inspect
        from automations.apex_new_starts import blueink_data as BID
        src = inspect.getsource(BID.one_hire) if hasattr(BID, "one_hire") \
            else open(BID.__file__).read()
        self.assertIn('if sem == "dob":', src)


if __name__ == "__main__":
    unittest.main()

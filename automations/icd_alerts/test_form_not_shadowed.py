"""A code row must not silently override what an owner typed into the form.

2026-09-17. Aya filled in the sign-up form: weekdays from 13:00, Saturday
11:00-18:00. A code row enrolled for her by hand carried the ORG DEFAULT --
13:30, and Saturday 10:45-17:00. all_offices() merges the sign-up tab and then
the code table, CODE WINNING, so the defaults were served and her answers were
not. She would have gone dark an hour before her office stopped selling on a
Saturday, and nothing anywhere would have said so: the form shows 18:00, the
code says 17:00, and neither side can see the other.

Megan's reason for wanting the form used at all was "so that we can make sure
we have all the correct info that she wants" -- which a silent override
defeats exactly.
"""
from __future__ import annotations

import unittest

from automations.icd_alerts import offices as O


class _Fake:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _office(**kw):
    base = dict(campaign="att", timezone="America/Chicago",
                day_start="13:30", day_end="20:30",
                sat_start="10:45", sat_end="17:00", saturday=True)
    base.update(kw)
    return _Fake(**base)


class ShadowingIsReportedTest(unittest.TestCase):
    def setUp(self):
        self._orig = dict(O.OFFICES)
        self.addCleanup(lambda: (O.OFFICES.clear(), O.OFFICES.update(self._orig)))

    def test_a_disagreeing_code_row_is_reported(self):
        """Aya's exact case: her Saturday runs an hour longer than the default."""
        O.OFFICES.clear()
        O.OFFICES["aya"] = _office(sat_end="17:00", day_start="13:30")
        got = O.shadowed({"aya": _office(sat_end="18:00", day_start="13:00")})
        self.assertIn("aya", got)
        self.assertEqual(got["aya"]["sat_end"], ("18:00", "17:00"))
        self.assertEqual(got["aya"]["day_start"], ("13:00", "13:30"))

    def test_an_agreeing_code_row_is_not_reported(self):
        O.OFFICES.clear()
        O.OFFICES["aya"] = _office(sat_end="18:00", day_start="13:00")
        self.assertEqual(
            O.shadowed({"aya": _office(sat_end="18:00", day_start="13:00")}), {})

    def test_an_office_with_no_code_row_cannot_be_shadowed(self):
        """The form is the only record for them, so there is nothing to
        override -- that is the desired state, not a finding."""
        O.OFFICES.clear()
        self.assertEqual(O.shadowed({"aya": _office(sat_end="18:00")}), {})

    def test_campaign_counts_as_owner_chosen(self):
        """Wrong campaign is the silent one -- every board blank at once."""
        O.OFFICES.clear()
        O.OFFICES["x"] = _office(campaign="att")
        got = O.shadowed({"x": _office(campaign="b2b_box")})
        self.assertEqual(got["x"]["campaign"], ("b2b_box", "att"))


class TheRealRosterIsNotShadowedTest(unittest.TestCase):
    def test_owner_chosen_fields_are_the_ones_a_form_asks(self):
        """If the form grows a field, it belongs here too -- otherwise the
        next override is silent again."""
        for f in ("campaign", "timezone", "day_start", "day_end",
                  "sat_start", "sat_end"):
            self.assertIn(f, O.OWNER_CHOSEN)


if __name__ == "__main__":
    unittest.main()

"""A wrong-office read must name the cause it can actually prove.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.ad_sales_board.test_wrong_office

WHAT THIS GUARDS (2026-09-05). `fetch.select_office` fires
`p=104&newOfficeId=<id>` and never checks the switch took. When AppStream
declines it, the session silently STAYS on the office selected before, and the
next Source Report reads as that office's. The `_same_owner` guard catches it
and refuses to write — correct — but the message it raised asserted one cause
with total confidence:

    "Another job sharing this AppStream session switched the office mid-run."

For Dhyey Patel (22767) that was wrong, and expensively so. From 2026-09-04
22:05 every run came back for 'Joey Ramirez' — office 23206, the entry
immediately BEFORE Dhyey in OFFICES. A job on another machine stealing the
session lands on an arbitrary office and does not repeat; the SAME predecessor,
every run, is a switch that never took. Whoever picked up the ticket was being
sent to hunt a concurrency bug that does not exist, when the thing to check is
whether office 22767 is still selectable on that login at all.
"""
from __future__ import annotations

import unittest

from automations.ad_sales_board import run as ad
from automations.indeed_source_report.offices import OFFICES


class PreviousOfficeLookup(unittest.TestCase):
    def test_returns_the_entry_before_it(self):
        ids = [str(o) for o, _n in OFFICES]
        for i in range(1, len(ids)):
            self.assertEqual(ad._prev_office_name(ids[i]),
                             list(OFFICES)[i - 1][1])

    def test_first_office_has_no_predecessor(self):
        self.assertEqual(ad._prev_office_name(str(list(OFFICES)[0][0])), "")

    def test_unknown_office_is_not_an_error(self):
        self.assertEqual(ad._prev_office_name("99999"), "")

    def test_the_live_case_dhyey_follows_joey(self):
        """The pairing that produced the misdiagnosis. If the roster order ever
        changes this stops being the example — that is worth knowing."""
        self.assertEqual(ad._prev_office_name("22767"), "Joey Ramirez")

    def test_a_stuck_switch_is_told_apart_from_a_stolen_session(self):
        """_same_owner against the predecessor is the whole discriminator."""
        prev = ad._prev_office_name("22767")
        self.assertTrue(ad._same_owner("Joey Ramirez", prev))
        self.assertFalse(ad._same_owner("Kinsey Guenther", prev))


if __name__ == "__main__":
    unittest.main()

"""The Await text's interview times follow the clock for EVERY office that
pushes (Megan 2026-10-28) -- each with its own windows, never another's.
No browser, no AppStream."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.oat_processing import await_template as AT
from automations.oat_processing import await_window as AW


class PerOfficeWindows(unittest.TestCase):

    def test_carlos_text_is_unchanged(self):
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 13, 0)),
                         "available TODAY between 1:45pm-3:45pm")
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 7, 0)),
                         "available TODAY between 8:15am-10:45am or "
                         "12:15pm-3:45pm")

    def test_an_office_uses_its_own_windows(self):
        own = [AW._w(9, 0, 11, 0), AW._w(13, 0, 17, 0)]
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 14, 0), own),
                         "available TODAY between 3:00pm-5:00pm")
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 18, 0), own),
                         "available TOMORROW between 9:00am-11:00am or "
                         "1:00pm-5:00pm")

    def test_a_single_window_office(self):
        one = [AW._w(10, 0, 12, 0)]
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 11, 20), one),
                         "available TODAY at 12:00pm")

    def test_an_office_with_no_windows_is_left_alone(self):
        page = mock.Mock()
        with mock.patch.object(AT, "_goto_templates") as go:
            self.assertTrue(AT.ensure_await_template(page, "99999"))
        go.assert_not_called()       # never opened, never edited

    def test_the_regex_still_matches_every_shape_it_writes(self):
        own = [AW._w(9, 0, 11, 0), AW._w(13, 0, 17, 0)]
        for h in range(6, 23):
            for w in (None, own):
                c = AW.await_clause(dt.datetime(2026, 10, 28, h, 10), w)
                self.assertTrue(AT.CLAUSE_RE.search(
                    "Are you %s for a quick ZOOM?" % c), c)


if __name__ == "__main__":
    unittest.main()

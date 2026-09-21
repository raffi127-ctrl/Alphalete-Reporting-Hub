"""A fault that heals itself on the next tick should never ping anybody.

2026-09-21, 10:00-10:01: Khalil, Aya and Ryan each posted a red "something
broke" in the same minute -- the moment every office starts its first read of
the day -- and every one read fine two to seven minutes later. Carlos did the
same at 10:38 the day before. Megan: alert only when it repeats.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import post as P


def _fault(stage, count, office="aya"):
    return {"office": office, "stage": stage, "summary": "TimeoutError", "count": str(count),
            "first": "10:00", "detail": "", "platform": "Darwin", "rownum": 5}


class WhoWaitsTest(unittest.TestCase):
    def test_a_first_sweep_failure_waits(self):
        self.assertTrue(P.waits_for_a_repeat(_fault("sweep", 1)))

    def test_its_second_occurrence_posts(self):
        self.assertFalse(P.waits_for_a_repeat(_fault("sweep", 2)))

    def test_slow_and_timeout_variants_wait_too(self):
        for st in ("knocks-slow", "box-timeout", "sweep-slow", "knocks", "box"):
            self.assertTrue(P.waits_for_a_repeat(_fault(st, 1)), st)

    def test_sign_in_never_waits(self):
        """That one needs a person to walk to the machine."""
        self.assertFalse(P.waits_for_a_repeat(_fault("signin-servicecloud", 1)))

    def test_one_time_stages_never_wait(self):
        """An install has no next tick; holding it would lose it forever."""
        self.assertFalse(P.waits_for_a_repeat(_fault("install", 1)))

    def test_an_unreadable_count_posts_rather_than_hides(self):
        self.assertFalse(P.waits_for_a_repeat(_fault("sweep", "x")))


class NotifyHoldsAndPostsTest(unittest.TestCase):
    def _run(self, faults):
        tab = mock.Mock()
        book = mock.Mock(**{"worksheet.return_value": tab})
        with mock.patch.object(P, "open_faults", return_value=faults), \
             mock.patch.object(P, "_fault_threads", return_value={}), \
             mock.patch.object(P, "_save_fault_threads", create=True), \
             mock.patch.object(P, "_slack", return_value="1.1") as posted, \
             mock.patch.object(P, "ask_office_to_sign_in") as dm:
            P.notify_faults(dt.date(2026, 9, 21), send=True, book=book,
                            log=lambda *_: None)
        return posted, dm, tab

    def test_a_one_off_is_not_posted_and_not_marked(self):
        posted, _dm, tab = self._run([_fault("sweep", 1)])
        posted.assert_not_called()
        tab.update_cell.assert_not_called()

    def test_a_repeat_is_posted(self):
        posted, _dm, _tab = self._run([_fault("sweep", 2)])
        self.assertTrue(posted.called)

    def test_a_sign_in_problem_still_dms_at_once(self):
        _p, dm, _t = self._run([_fault("signin-servicecloud", 1, office="ryan")])
        self.assertTrue(dm.called)


if __name__ == "__main__":
    unittest.main()

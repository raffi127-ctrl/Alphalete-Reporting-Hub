"""The per-person pre-start send clock.

What these pin down, in the order they matter:
  * nothing goes out EARLY -- the half of the rule that needed enforcing;
  * a late BOB and a machine that was down both still send;
  * an unreadable start date sends nobody, loudly;
  * the tab window reaches both next week and the week just gone.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.shared import new_start_timing as T


MON = dt.date(2026, 11, 23)          # a start date


class TheFloor(unittest.TestCase):
    def test_two_days_before_is_the_first_day_it_goes(self):
        self.assertEqual(T.floor_date(MON), dt.date(2026, 11, 21))
        self.assertTrue(T.due(MON, today=dt.date(2026, 11, 21)))

    def test_three_days_out_is_too_early(self):
        self.assertFalse(T.due(MON, today=dt.date(2026, 11, 20)))

    def test_a_week_out_is_too_early(self):
        self.assertFalse(T.due(MON, today=dt.date(2026, 11, 16)))

    def test_the_lead_is_a_floor_not_a_single_day(self):
        # The day after the floor, and their own start day, still send: a tick
        # that only fired on the floor itself would drop anyone whose machine
        # was down that day, and they would never be sent at all.
        for d in (22, 23):
            self.assertTrue(T.due(MON, today=dt.date(2026, 11, d)),
                            "%s should still be due" % d)

    def test_someone_bobd_the_day_before_is_already_past_their_floor(self):
        # Start tomorrow, found today: their floor fell yesterday, so they go
        # on this tick rather than never.
        start = dt.date(2026, 11, 19)
        self.assertTrue(T.due(start, today=dt.date(2026, 11, 18)))

    def test_after_their_start_it_still_sends(self):
        # Unsigned paperwork does not stop mattering because the day passed;
        # what stops a second send is the step's own marker, not this.
        self.assertTrue(T.due(MON, today=dt.date(2026, 11, 30)))

    def test_a_zero_lead_sends_on_the_day(self):
        self.assertEqual(T.floor_date(MON, lead_days=0), MON)
        self.assertFalse(T.due(MON, dt.date(2026, 11, 22), lead_days=0))
        self.assertTrue(T.due(MON, MON, lead_days=0))


class AnUnreadableStartDateSendsNobody(unittest.TestCase):
    def test_none_is_never_due(self):
        self.assertIsNone(T.floor_date(None))
        self.assertFalse(T.due(None, today=MON))

    def test_a_string_date_is_not_accepted_as_a_date(self):
        # Refusing is the point: a parsed-looking string would send on a
        # guessed day.
        self.assertFalse(T.due("11/23/2026", today=MON))

    def test_a_datetime_is_not_mistaken_for_a_date(self):
        # dt.datetime IS a dt.date subclass, so this one passes the isinstance
        # check -- it must still compare sanely rather than blow up.
        self.assertIsInstance(T.due(dt.datetime(2026, 11, 23), today=MON),
                              bool)

    def test_a_negative_lead_refuses_rather_than_sending_after_the_start(self):
        self.assertIsNone(T.floor_date(MON, lead_days=-1))
        self.assertFalse(T.due(MON, today=MON, lead_days=-1))


class WhatTheLogSays(unittest.TestCase):
    def test_due_people_get_no_held_back_line(self):
        self.assertEqual(T.why_not_yet(MON, dt.date(2026, 11, 21)), "")

    def test_too_early_says_when_theirs_goes(self):
        line = T.why_not_yet(MON, dt.date(2026, 11, 18))
        self.assertIn("2026-11-21", line)       # the day theirs goes
        self.assertIn("2026-11-23", line)       # their start
        self.assertNotIn("floor", line.lower())  # plain words, not our jargon

    def test_no_start_date_says_so_in_words(self):
        line = T.why_not_yet(None, MON)
        self.assertIn("no start date", line.lower())

    def test_days_until_counts_down_and_goes_negative(self):
        self.assertEqual(T.days_until(MON, dt.date(2026, 11, 18)), 5)
        self.assertEqual(T.days_until(MON, MON), 0)
        self.assertEqual(T.days_until(MON, dt.date(2026, 11, 25)), -2)
        self.assertIsNone(T.days_until(None, MON))


class SplitKeepsUndatedSeparate(unittest.TestCase):
    def test_three_buckets(self):
        people = [("ready", MON),
                  ("waiting", dt.date(2026, 12, 7)),
                  ("undated", None)]
        ready, waiting, undated = T.split(
            people, start_of=lambda p: p[1], today=dt.date(2026, 11, 21))
        self.assertEqual([p[0] for p in ready], ["ready"])
        self.assertEqual([p[0] for p in waiting], ["waiting"])
        self.assertEqual([p[0] for p in undated], ["undated"])

    def test_undated_is_not_folded_into_not_yet(self):
        # The whole reason for three lists: "not yet" needs no attention and
        # "no date on the chart" needs somebody to look.
        _ready, waiting, undated = T.split(
            [("x", None)], start_of=lambda p: p[1], today=MON)
        self.assertEqual(waiting, [])
        self.assertEqual(len(undated), 1)


class TheTabWindow(unittest.TestCase):
    def setUp(self):
        self.tabs = [
            (dt.date(2026, 11, 30), "D2D OBCL 11.30"),   # two weeks out
            (dt.date(2026, 11, 23), "D2D OBCL 11.23"),   # next week
            (dt.date(2026, 11, 16), "D2D OBCL 11.16"),   # this week
            (dt.date(2026, 11, 2), "D2D OBCL 11.2"),     # three weeks gone
        ]

    def test_saturday_reaches_next_weeks_tab(self):
        # The case one-newest-tab could not answer: on the 21st the people who
        # are DUE are on the 11.23 tab.
        got = [t for _d, t in T.window_tabs(self.tabs,
                                            today=dt.date(2026, 11, 21))]
        self.assertIn("D2D OBCL 11.23", got)

    def test_it_also_still_sees_the_week_that_started(self):
        # Somebody who started Thursday and has not signed is on 11.16.
        got = [t for _d, t in T.window_tabs(self.tabs,
                                            today=dt.date(2026, 11, 21))]
        self.assertIn("D2D OBCL 11.16", got)

    def test_it_does_not_reach_a_tab_nobody_is_due_on(self):
        got = [t for _d, t in T.window_tabs(self.tabs,
                                            today=dt.date(2026, 11, 21))]
        self.assertNotIn("D2D OBCL 11.30", got)   # too far ahead
        self.assertNotIn("D2D OBCL 11.2", got)    # too far behind

    def test_order_is_preserved_newest_first(self):
        got = [d for d, _t in T.window_tabs(self.tabs,
                                            today=dt.date(2026, 11, 21))]
        self.assertEqual(got, sorted(got, reverse=True))

    def test_a_tab_with_no_readable_date_is_dropped_not_crashed_on(self):
        got = T.window_tabs([(None, "D2D OBCL")] + self.tabs,
                            today=dt.date(2026, 11, 21))
        self.assertTrue(all(isinstance(d, dt.date) for d, _t in got))


if __name__ == "__main__":
    unittest.main()

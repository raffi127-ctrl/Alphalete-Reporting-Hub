"""Each person's own start date, read off the chart they sit in.

This is what the per-person send clock keys on (Megan, 2026-11-18: "2 days
before their start ... off their own start date rather than one time for
everybody"), so the thing worth pinning is that two charts on ONE tab give
their people DIFFERENT dates. A per-tab date would send the late adds on the
main cohort's day, which is the fault this replaces.

    python -m unittest automations.blueink_docs.test_chart_dates
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.blueink_docs import config
from automations.blueink_docs.roster import attach_chart_dates, parse_tab
from automations.shared import new_start_timing as timing

HEADER = ["#", "2ND Round Interviewer", "Trainer", "Name", "Last Name",
          "Contact Added", "Email", "Phone", "Location", "Final Status",
          "\nBG Status : Last Checked ", "Digi Docs", "Friday Confirmation"]


def _row(first, last, email):
    return ["1", "Interviewer", "1:00", first, last, "TRUE", email,
            "8173955555", "", "", "Passed", "FALSE", "Confirmed: OTP"]


def _tab(*sections):
    """sections = (date_text, [person-rows]); each gets its own date + header."""
    values = []
    for date_text, rows in sections:
        values += [[date_text] + [""] * 12, list(HEADER)]
        values += list(rows) + [[""] * 13]
    return values


class EachChartCarriesItsOwnDate(unittest.TestCase):
    def test_two_charts_one_tab_two_different_start_dates(self):
        values = _tab(("11/23/2026", [_row("Ana", "Lopez", "ana@x.com")]),
                      ("11/25/2026", [_row("Ben", "Ruiz", "ben@x.com")]))
        people = attach_chart_dates(values, parse_tab(values, "D2D OBCL 11.23"),
                                    "D2D OBCL 11.23")
        got = {p.name: p.chart_date for p in people}
        self.assertEqual(got["Ana Lopez"], dt.date(2026, 11, 23))
        self.assertEqual(got["Ben Ruiz"], dt.date(2026, 11, 25))

    def test_the_year_comes_from_the_tab_when_the_chart_omits_it(self):
        values = _tab(("11/23", [_row("Ana", "Lopez", "ana@x.com")]))
        people = attach_chart_dates(values, parse_tab(values, "D2D OBCL 11.23.2026"),
                                    "D2D OBCL 11.23.2026")
        self.assertEqual(people[0].chart_date, dt.date(2026, 11, 23))

    def test_chart_date_is_none_before_anyone_attaches_it(self):
        values = _tab(("11/23/2026", [_row("Ana", "Lopez", "ana@x.com")]))
        self.assertIsNone(parse_tab(values, "D2D OBCL 11.23")[0].chart_date)


class WhoIsDueOnWhichDay(unittest.TestCase):
    """The gate `run.py` applies, exercised on a real parsed tab."""

    def setUp(self):
        self.values = _tab(
            ("11/23/2026", [_row("Mon", "Starter", "mon@x.com")]),
            ("11/27/2026", [_row("Thu", "Starter", "thu@x.com")]))
        self.people = attach_chart_dates(
            self.values, parse_tab(self.values, "D2D OBCL 11.23"),
            "D2D OBCL 11.23")

    def _split(self, today):
        return timing.split(self.people, start_of=lambda p: p.chart_date,
                            today=today, lead_days=config.SEND_LEAD_DAYS)

    def test_the_monday_starter_goes_on_saturday_and_the_thursday_one_waits(self):
        # The whole point: one tab, one run, two answers. Under the old
        # whole-tab batch both would have gone on Saturday, and the Thursday
        # starter would have had five days to misplace their contract.
        ready, waiting, undated = self._split(dt.date(2026, 11, 21))
        self.assertEqual([p.name for p in ready], ["Mon Starter"])
        self.assertEqual([p.name for p in waiting], ["Thu Starter"])
        self.assertEqual(undated, [])

    def test_by_the_thursday_starters_own_floor_they_are_due_too(self):
        ready, _waiting, _u = self._split(dt.date(2026, 11, 25))
        self.assertEqual(sorted(p.name for p in ready),
                         ["Mon Starter", "Thu Starter"])

    def test_nobody_is_due_a_week_out(self):
        ready, waiting, _u = self._split(dt.date(2026, 11, 16))
        self.assertEqual(ready, [])
        self.assertEqual(len(waiting), 2)

    def test_a_chart_with_no_date_sends_nobody_and_lands_in_its_own_bucket(self):
        values = _tab(("", [_row("No", "Date", "nd@x.com")]))
        people = attach_chart_dates(values, parse_tab(values, "D2D OBCL 11.23"),
                                    "D2D OBCL 11.23")
        ready, waiting, undated = timing.split(
            people, start_of=lambda p: p.chart_date,
            today=dt.date(2026, 11, 21), lead_days=config.SEND_LEAD_DAYS)
        self.assertEqual(ready, [])
        self.assertEqual(waiting, [])            # not quietly "not yet"
        self.assertEqual([p.name for p in undated], ["No Date"])


class TheLeadIsTwoDays(unittest.TestCase):
    def test_config_still_says_two(self):
        # If this changes, it was a decision -- Megan asked for two
        # (2026-11-18). The test is here so the change is a visible one.
        self.assertEqual(config.SEND_LEAD_DAYS, 2)


if __name__ == "__main__":
    unittest.main()

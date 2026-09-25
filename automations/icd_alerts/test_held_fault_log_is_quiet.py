"""A held fault says itself once a day, not once a minute.

Cyrus's ONE slow sweep on 2026-09-24 produced 228 pairs of lines in the
poster log. A fault that waits for a repeat is deliberately never posted, so
it stays "open" all day, and open faults were printed on every 60-second
tick.

That is not a cosmetic problem. The repetition is what made a once-a-day,
below-threshold event look like a live crisis: it was first reported up as
"~228 occurrences today" and diagnosed from that number, when the truth was
one occurrence re-read 228 times.

What must stay true is that quietening the log never quietens a fault:
  * the first sighting still prints;
  * a fault whose count MOVES prints again -- that is the tick it starts
    alerting;
  * a dry run still shows everything, because a person running it by hand is
    asking what is open right now;
  * the 'ICD Faults' tab and the Slack posting are untouched.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import post as P

DAY = dt.date(2026, 9, 24)


def _fault(count="1", office="cyrus", stage="sweep-slow"):
    return {"office": office, "stage": stage, "count": count,
            "summary": "RuntimeError: this read took 208 seconds.",
            "first": "11:11", "detail": "", "platform": "Darwin",
            "rownum": 7}


class TheLogSaysItOnce(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self._orig = P.FAULT_SAID_PATH
        P.FAULT_SAID_PATH = self.tmp / "said.json"

    def tearDown(self):
        P.FAULT_SAID_PATH = self._orig

    def _ticks(self, n, fault=None, send=True):
        """Run notify_faults n times, returning the lines each tick logged."""
        out = []
        for _ in range(n):
            lines = []
            with mock.patch.object(P, "open_faults",
                                   return_value=[fault or _fault()]), \
                    mock.patch.object(P, "_fault_threads", return_value={}), \
                    mock.patch.object(P, "_slack", return_value="1.1"), \
                    mock.patch("automations.recruiting_report.fill.open_by_key",
                               return_value=mock.MagicMock()):
                P.notify_faults(DAY, send=send, log=lines.append)
            out.append(lines)
        return out

    def test_the_first_tick_still_says_it(self):
        first = self._ticks(1)[0]
        self.assertTrue(any("FAULT:" in l and "cyrus" in l for l in first),
                        "the first sighting was swallowed")

    def test_and_says_it_is_suppressing(self):
        first = self._ticks(1)[0]
        self.assertTrue(any("suppressed" in l for l in first),
                        "silence should explain itself")

    def test_the_next_sixty_ticks_are_quiet(self):
        ticks = self._ticks(60)
        later = [l for t in ticks[1:] for l in t if "FAULT:" in l]
        self.assertEqual(later, [],
                         "the held fault was re-printed %d times" % len(later))

    def test_the_holding_line_is_said_once_too(self):
        ticks = self._ticks(5)
        self.assertTrue(any("HOLDING" in l for l in ticks[0]))
        later = [l for t in ticks[1:] for l in t if "HOLDING" in l]
        self.assertEqual(later, [], "HOLDING repeated after the first tick")

    def test_a_count_that_moves_prints_again(self):
        """The moment it starts alerting is the one line that must not be
        swallowed."""
        self._ticks(3)                       # count 1, now quiet
        second = self._ticks(1, fault=_fault(count="2"))[0]
        self.assertTrue(any("FAULT:" in l for l in second),
                        "a fault going 1 -> 2 stayed quiet, which is the tick "
                        "it starts alerting")

    def test_another_office_is_not_silenced(self):
        self._ticks(3)
        other = self._ticks(1, fault=_fault(office="aya"))[0]
        self.assertTrue(any("aya" in l for l in other))

    def test_a_different_stage_on_the_same_office_still_prints(self):
        self._ticks(3)
        other = self._ticks(1, fault=_fault(stage="knocks-slow"))[0]
        self.assertTrue(any("FAULT:" in l for l in other))

    def test_tomorrow_says_it_again(self):
        self._ticks(3)
        lines = []
        with mock.patch.object(P, "open_faults", return_value=[_fault()]), \
                mock.patch.object(P, "_fault_threads", return_value={}), \
                mock.patch.object(P, "_slack", return_value="1.1"), \
                mock.patch("automations.recruiting_report.fill.open_by_key",
                           return_value=mock.MagicMock()):
            P.notify_faults(DAY + dt.timedelta(days=1), send=True,
                            log=lines.append)
        self.assertTrue(any("FAULT:" in l for l in lines))

    def test_a_dry_run_always_shows_everything(self):
        """A person asking what is open must not be answered with silence
        because the poller mentioned it an hour ago."""
        self._ticks(3)
        for tick in self._ticks(2, send=False):
            self.assertTrue(any("FAULT:" in l for l in tick),
                            "a dry run hid an open fault")

    def test_an_unwritable_state_file_never_hides_a_fault(self):
        P.FAULT_SAID_PATH = pathlib.Path("/nope/cannot/write/said.json")
        for tick in self._ticks(3):
            self.assertTrue(any("FAULT:" in l for l in tick),
                            "a fault went quiet because state could not be "
                            "written -- it must fail loud, not silent")


if __name__ == "__main__":
    unittest.main()

"""A gap is measured to when the knocks were READ, not to when Lucy speaks.

2026-11-12, Raf's office: the 3:08 PM gap text was built from knocks read at
2:46 and measured against 3:08, so the data's 22 minutes were added to every
rep -- 41 of 53 landed between 22 and 28 "min". Raf: "This is off. Not that
many people on break when we look at telemapper."

    python -m unittest automations.icd_alerts.test_gaps_measured_from_the_read

Made-up reps. Nothing here reads a sheet, texts anybody or posts.
"""
import datetime as dt
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import gap_callouts as GC
from automations.icd_alerts import knocks_post as KP

DAY = dt.date(2026, 11, 12)
SPEAK = dt.datetime(2026, 11, 12, 15, 8)            # when the text goes out
READ = "11/12/2026 14:46:38"                        # the relay's Received At
CLOCK = dt.datetime(2026, 11, 12, 15, 8, 38)        # this machine, same instant

ROWS = [
    {"Rep": "Knocking Nell", "Last Knock": "2:45 PM"},     # 1 min quiet at the read
    {"Rep": "Steady Sam", "Last Knock": "2:40 PM"},        # 6 min
    {"Rep": "Quiet Quinn", "Last Knock": "2:06 PM"},       # 40 min -- really idle
]


class TheMomentOfTheRead(unittest.TestCase):

    def test_now_is_wound_back_by_the_age_of_the_relay(self):
        got = KP._read_moment(SPEAK, READ, clock=CLOCK)
        self.assertEqual(got, dt.datetime(2026, 11, 12, 14, 46))

    def test_a_fresh_relay_changes_nothing_worth_the_name(self):
        got = KP._read_moment(SPEAK, "11/12/2026 15:08:30", clock=CLOCK)
        self.assertLess(SPEAK - got, dt.timedelta(seconds=10))

    def test_the_office_keeps_its_own_clock(self):
        # An Eastern office: its `now` is an hour ahead of this machine. Only
        # the AGE is taken off, so the answer stays on the office's clock.
        east = SPEAK + dt.timedelta(hours=1)
        self.assertEqual(KP._read_moment(east, READ, clock=CLOCK),
                         dt.datetime(2026, 11, 12, 15, 46))

    def test_an_age_we_cannot_trust_leaves_now_alone(self):
        for bad in ("", "not a time", "11/12/2026 16:30:00",      # the future
                    "11/11/2026 14:46:38"):                       # yesterday
            self.assertEqual(KP._read_moment(SPEAK, bad, clock=CLOCK), SPEAK,
                             "should not guess from %r" % bad)


class TheListSaysWhoWasIdleWhenWeLooked(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(KP, "OUT_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def _text(self, now):
        return KP._gaps_text(None, ROWS, now, dest="t", remember=False)

    def test_measured_to_the_send_everybody_looks_idle(self):
        # What went out at 3:08: all three, the data's 22 minutes on each.
        old = self._text(SPEAK)
        for name in ("Knocking Nell", "Steady Sam", "Quiet Quinn"):
            self.assertIn(name, old)
        self.assertIn("Knocking Nell - 23 min", old)

    def test_measured_to_the_read_only_the_idle_rep_is_named(self):
        new = self._text(KP._read_moment(SPEAK, READ, clock=CLOCK))
        self.assertIn("Quiet Quinn - 40 min", new)
        self.assertNotIn("Knocking Nell", new)
        self.assertNotIn("Steady Sam", new)


class EveryGapListUsesIt(unittest.TestCase):

    def test_the_board_run_never_measures_a_gap_list_to_now(self):
        src = inspect.getsource(KP.run)
        self.assertIn("gap_now = _read_moment(now, row[KN_RECEIVED])", src)
        self.assertEqual(src.count("_gaps_text(office, rows_for_board, gap_now"), 4)
        self.assertNotIn("_gaps_text(office, rows_for_board, now", src)

    def test_the_slack_call_out_uses_it_too(self):
        src = inspect.getsource(GC.run)
        self.assertIn("K._read_moment(now, krow[K.KN_RECEIVED])", src)
        self.assertNotIn("pick(rows, records, prev, now)", src)


if __name__ == "__main__":
    unittest.main()

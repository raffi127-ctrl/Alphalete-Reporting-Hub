"""Fault posts say what happened in plain words, with no fake error attached.

2026-09-21, Kash: "something broke knocks-slow" with a thread reply of
"NoneType: None". A slow read is not a breakage, the stage name is ours not
the office's, and that reply is Python's placeholder for "no exception".
"""
from __future__ import annotations

import sys
import unittest
from unittest import mock

from automations.icd_alerts import post as P


class HeadlinesTest(unittest.TestCase):
    L = "Kash's Local Office"

    def test_slow_is_not_something_broke(self):
        h = P.fault_headline(self.L, "knocks-slow")
        self.assertNotIn("broke", h)
        self.assertIn("reading OwnerVille is running slowly", h)

    def test_stuck_says_it_was_stopped(self):
        self.assertIn("got stuck and was stopped",
                      P.fault_headline(self.L, "box-timeout"))

    def test_no_internal_stage_names_leak(self):
        for st in ("knocks-slow", "sweep-slow", "box-slow", "knocks-timeout",
                   "sweep-timeout", "box-timeout", "box", "sweep", "knocks"):
            h = P.fault_headline(self.L, st) + P.stage_words(st)
            self.assertNotIn(st if "-" in st else "broke %s." % st, h, st)

    def test_ordinary_faults_read_as_before(self):
        self.assertEqual(P.fault_headline(self.L, "sweep"),
                         ":rotating_light: *Kash's Local Office* — something "
                         "broke reading SaraPlus.")

    def test_follow_up_lines_are_plain(self):
        self.assertEqual(P.stage_words("knocks-slow"), "reading OwnerVille (slow)")


class NoFakeTracebackTest(unittest.TestCase):
    def test_the_placeholder_is_dropped(self):
        for junk in ("NoneType: None", "", "  ", None, "None"):
            self.assertEqual(P._real_traceback(junk), "")

    def test_a_real_one_is_kept(self):
        self.assertTrue(P._real_traceback("Traceback (most recent call last):"))

    def test_report_sends_no_traceback_when_nothing_was_raised(self):
        """The watchdog files a slow read from a `finally`, nothing raised."""
        from automations.icd_alerts import run as RUN
        with mock.patch.object(RUN.R, "report_fault") as rf:
            RUN._report("knocks-slow", RuntimeError("took 217s"))
        self.assertEqual(rf.call_args.args[2], "")

    def test_report_keeps_the_traceback_when_something_was(self):
        from automations.icd_alerts import run as RUN
        with mock.patch.object(RUN.R, "report_fault") as rf:
            try:
                raise ValueError("real")
            except ValueError as e:
                RUN._report("sweep", e)
        self.assertIn("ValueError", rf.call_args.args[2])


if __name__ == "__main__":
    unittest.main()

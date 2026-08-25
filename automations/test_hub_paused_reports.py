"""A stood-down report gets its own colour, and stops pretending to be due.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.test_hub_paused_reports

WHY (Megan 2026-08-25). Every status colour on the Hub means "something is
happening or should have": red = due, amber = partial/failed, green = done, blue
= schedule, purple = awaiting approval. There was no colour for OFF — so a report
that had been deliberately switched off wore the same red DUE TODAY as one that
was genuinely late, and sat on the morning triage list.

tracker_mirror is the case. Carlos stood it down 2026-08-24 (5d4042b) because the
manager tabs went back on live IMPORTRANGE, so a ferry pass would overwrite those
formulas with frozen values — running it would have been the WRONG thing to do.
The stand-down is enforced by a DISABLED file on Lucy 1 that makes both run.py and
deploy/tracker_mirror.sh refuse to run, but that file is on the RUNNER and
invisible to a Hub on anyone's laptop, so the card kept advertising "07:30 CST"
and reading as overdue.

Slate grey is used for nothing else on the page, on purpose — it has to read as
OFF at a glance without competing with the colours that need you.
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations import dashboard

TODAY = dt.date(2026, 8, 25)
DAILY = {"frequency": "daily", "time": "07:30"}


class TheReasonLookup(unittest.TestCase):
    """Two sources, because a library card has nowhere to carry a field."""

    def test_a_hand_written_card_can_carry_its_own_flag(self):
        r = {"id": "whatever", "schedule": DAILY, "paused": "on hold for Q4"}
        self.assertEqual(dashboard._paused_reason(r), "on hold for Q4")

    def test_a_non_string_flag_still_reads_as_paused(self):
        r = {"id": "whatever", "schedule": DAILY, "paused": True}
        self.assertTrue(dashboard._paused_reason(r))

    def test_a_library_card_is_covered_by_the_map(self):
        """tracker_mirror is a self-registered library card — a Sheet row, not a
        dict — so the flag can only live in PAUSED_REPORTS."""
        r = {"id": "tracker_mirror", "schedule": DAILY}
        self.assertIn("IMPORTRANGE", dashboard._paused_reason(r))

    def test_a_live_report_is_not_paused(self):
        self.assertEqual(
            dashboard._paused_reason({"id": "org-sales-board", "schedule": DAILY}),
            "")


class APausedReportIsNeverDue(unittest.TestCase):
    """_was_due_on is the single funnel — the DUE pill, the 'N due today'
    counts, the calendar tiles and Needs-attention all ask it."""

    def test_paused_beats_a_daily_schedule(self):
        r = {"id": "tracker_mirror", "schedule": DAILY}
        self.assertFalse(dashboard._was_due_on(r, TODAY))

    def test_the_same_card_would_be_due_if_it_were_not_paused(self):
        """Proves the schedule itself says 'due' — so paused is what changed it,
        not a malformed schedule."""
        r = {"id": "not-paused-anywhere", "schedule": DAILY}
        self.assertTrue(dashboard._was_due_on(r, TODAY))

    def test_a_live_daily_report_is_still_due(self):
        r = {"id": "org-sales-board", "schedule": DAILY}
        self.assertTrue(dashboard._is_due_today(r, TODAY))

    def test_the_real_tracker_mirror_card_is_not_due(self):
        """End to end against the card the Hub actually loads."""
        card = next((c for c in dashboard.AUTOMATED_REPORTS
                     if c.get("id") == "tracker_mirror"), None)
        self.assertIsNotNone(card, "tracker_mirror card missing from the Hub")
        self.assertFalse(dashboard._is_due_today(card, TODAY))


class TheColourIsReservedForOff(unittest.TestCase):

    def test_pill_paused_is_defined(self):
        import inspect
        src = inspect.getsource(dashboard)
        self.assertIn(".pill-paused{", src)

    def test_grey_is_not_reused_by_another_pill(self):
        """The whole point is that this colour means one thing. If another pill
        adopts the same background, 'paused' stops being readable at a glance."""
        import inspect
        import re
        src = inspect.getsource(dashboard)
        greys = re.findall(r"\.(pill-[a-z]+)\{[^}]*background:\s*#EEF0F2", src)
        self.assertEqual(greys, ["pill-paused"], f"grey reused by: {greys}")

    def test_the_paused_pill_wins_over_the_schedule_pills(self):
        import inspect
        src = inspect.getsource(dashboard)
        self.assertIn("if _paused:", src)
        self.assertIn("elif ran_today and not _hide_sched", src,
                      "the DONE/DUE pills must be an elif under paused")

    def test_a_paused_card_does_not_advertise_a_schedule_time(self):
        """The time pill is a promise the report isn't keeping — it's what put
        tracker_mirror in front of Megan looking overdue."""
        import inspect
        src = inspect.getsource(dashboard)
        self.assertIn("if sched and not _hide_sched and not _paused:", src)


class ItStaysOffTheTriageList(unittest.TestCase):

    def test_needs_attention_skips_paused(self):
        import inspect
        src = inspect.getsource(dashboard)
        self.assertIn('if _paused_reason(r):', src,
                      "Needs-attention must skip stood-down reports")


if __name__ == "__main__":
    unittest.main()

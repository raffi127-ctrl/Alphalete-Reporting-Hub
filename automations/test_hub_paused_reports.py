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


class PausedStaysVISIBLEButUncounted(unittest.TestCase):
    """The correction (Megan 2026-08-25). Gating _was_due_on on `paused` did stop
    every count at once — but that function ALSO decides which cards a day's views
    LIST, so tracker_mirror disappeared from the Hub completely and there was no
    way to see it was paused. 'Doesn't count as work' and 'isn't on the page' are
    different things."""

    def test_a_paused_report_is_still_due_on_so_it_stays_listed(self):
        r = {"id": "tracker_mirror", "schedule": DAILY}
        self.assertTrue(dashboard._was_due_on(r, TODAY),
                        "paused must NOT hide the card from the day's views")

    def test_the_real_tracker_mirror_card_is_still_visible(self):
        card = next((c for c in dashboard.AUTOMATED_REPORTS
                     if c.get("id") == "tracker_mirror"), None)
        self.assertIsNotNone(card, "tracker_mirror card missing from the Hub")
        self.assertTrue(dashboard._is_due_today(card, TODAY))
        self.assertTrue(dashboard._paused_reason(card))

    def test_the_pack_count_excludes_paused(self):
        import inspect
        src = inspect.getsource(dashboard)
        self.assertIn("and not _paused_reason(r)   # stood down \u2260 needs running",
                      src, "the per-person 'N due today' count must skip paused")

    def test_the_day_ratio_excludes_paused(self):
        import inspect
        src = inspect.getsource(dashboard)
        self.assertIn("and not _paused_reason(r)]", src,
                      "the day's ran/due ratio must skip paused")


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


class AFindingsRunCountsAsDone(unittest.TestCase):
    """An AUDIT records findings as a soft-incomplete (ok=False -> `partial`) on
    purpose, so it never logs "success". Counting only successes left the Vantura
    Board Audit permanently "due": it ran clean at 04:01 on 2026-08-25 and filed
    its 3 findings, and Lucy 2's card still said one report was due all day. The
    findings are a human's follow-up, not a re-run — the audit carries no
    retry_args and never edits the board."""

    def test_the_audit_is_done_once_it_has_run_partial(self):
        import datetime as _dt
        va = next((c for c in dashboard.AUTOMATED_REPORTS
                   if c.get("id") == "vantura_board_audit"), None)
        self.assertIsNotNone(va, "vantura_board_audit card missing")
        self.assertTrue(dashboard._counts_as_done_today(va, _dt.date.today()))

    def test_the_partial_exemption_is_scoped_to_findings_reports(self):
        """A normal report that came back partial genuinely still needs someone.
        Runs are stubbed so this tests the RULE, not whatever ran today."""
        from unittest import mock
        run = {"report_id": "", "status": "partial",
               "_dt": dt.datetime.combine(TODAY, dt.time(4, 1))}

        def _with(rid):
            run["report_id"] = rid
            with mock.patch.object(dashboard, "_all_runs_merged",
                                   return_value=[dict(run)]), \
                    mock.patch.object(dashboard, "_was_run_successfully_today",
                                      return_value=False):
                return dashboard._counts_as_done_today({"id": rid}, TODAY)

        self.assertTrue(_with("vantura_board_audit"), "an audit's findings = done")
        self.assertFalse(_with("org-sales-board"), "an ordinary partial is NOT done")

    def test_both_counts_use_the_helper(self):
        import inspect
        src = inspect.getsource(dashboard)
        self.assertEqual(src.count("_counts_as_done_today(r, today)"), 2,
                         "the day ratio and the per-person count must both use it")


class ItStaysOffTheTriageList(unittest.TestCase):

    def test_needs_attention_skips_paused(self):
        import inspect
        src = inspect.getsource(dashboard)
        self.assertIn('if _paused_reason(r):', src,
                      "Needs-attention must skip stood-down reports")


if __name__ == "__main__":
    unittest.main()

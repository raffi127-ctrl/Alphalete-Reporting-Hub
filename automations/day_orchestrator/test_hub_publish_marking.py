"""Who is allowed to say "somebody is working this" in #claudecorrections.

Megan 2026-08-20: "Lucy the bot is putting a pending reaction on things that
she's not actually working … it looks like it's been worked on, but it's not."
publish_running marked on EVERY start — the 4am loop, every auto-retry, the
standalone LaunchAgents, and _sync_hub_pills, which opens a pill for a report
merely WAITING on data with nothing executing. So the mark meant nothing.

    python -m unittest automations.day_orchestrator.test_hub_publish_marking -v
"""
from __future__ import annotations

import unittest

from automations.day_orchestrator import hub_publish, mini_control


class _Sheet:
    """Just enough worksheet for publish_running's one append."""

    def __init__(self):
        self.rows = []

    def append_row(self, row, **_kw):
        self.rows.append(row)


class PublishRunningMarksTest(unittest.TestCase):
    def setUp(self):
        self.marked = []
        self.sheet = _Sheet()
        for name, repl in (("_ws", lambda: self.sheet),
                           ("_resolve_card", lambda *a, **k: "card-1"),
                           ("_mark_working", self.marked.append)):
            real = getattr(hub_publish, name)
            setattr(hub_publish, name, repl)
            self.addCleanup(setattr, hub_publish, name, real)

    def test_a_scheduled_run_marks_nothing(self):
        """The 4am loop, a retry, a LaunchAgent, or a report still WAITING on
        data. None of those is a person, and the pill still opens either way."""
        run_id = hub_publish.publish_running("b2b_metrics", "B2B Metrics")
        self.assertTrue(run_id, "the Hub pill is unaffected")
        self.assertEqual(self.marked, [], "no ⏳ for a machine's run")

    def test_a_persons_rerun_marks_the_thread(self):
        hub_publish.publish_running("b2b_metrics", "B2B Metrics", manual=True)
        self.assertEqual(self.marked, ["b2b_metrics"])

    def test_a_report_with_no_hub_card_marks_nothing_either(self):
        hub_publish._resolve_card = lambda *a, **k: None
        self.assertIsNone(hub_publish.publish_running("x", "X", manual=True))
        self.assertEqual(self.marked, [])


class WhoQueuedItTest(unittest.TestCase):
    """is_manual decides whether a queued `rerun` counts as somebody working the
    ticket. Unknown answers False on purpose: a missed ⏳ is much the cheaper
    mistake than a false one (incident_thread's own rule)."""

    def tearDown(self):
        mini_control._CURRENT_BY = ""

    def test_a_person_by_name_is_manual(self):
        for who in ("Megan", "Eve", "Raf", "Hub"):
            self.assertTrue(mini_control.is_manual(who), who)

    def test_a_watchdog_is_not(self):
        self.assertFalse(mini_control.is_manual("appstream_watch"))

    def test_the_auto_prefix_is_not(self):
        self.assertFalse(mini_control.is_manual("auto:something_new"))

    def test_an_empty_by_column_is_not(self):
        self.assertFalse(mini_control.is_manual(""))

    def test_it_falls_back_to_the_row_being_run(self):
        mini_control._CURRENT_BY = "Megan"
        self.assertTrue(mini_control.is_manual())
        mini_control._CURRENT_BY = "auto:appstream_watch"
        self.assertFalse(mini_control.is_manual())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

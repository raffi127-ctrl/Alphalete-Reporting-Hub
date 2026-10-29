"""An office wired AFTER the morning run gets today's boards on the next
catch-up pass (goldenview, 2026-10-29: wired 9:18, got only Box + Quantum).
Pure — no Slack, no Sheets, no queue."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.tableau_screenshots import run

NOW = dt.datetime(2026, 10, 29, 9, 40)
TODAY = NOW.date()
IDS = {"alphalete": ["att_country", "nds", "b2b_box"],
       "goldenview": ["att_country", "nds", "b2b_box", "quantum_fiber"]}


def plan(served, captured=("att_country", "nds", "b2b_box")):
    return run.newcomer_plan(served, list(IDS), list(captured),
                             IDS.__getitem__, NOW)


class NewcomerPlan(unittest.TestCase):
    def test_org_the_morning_missed_gets_todays_captured_boards(self):
        served = {"served": ["alphalete"], "queued": {}}
        # quantum_fiber wasn't captured today (held) -> not sent from here
        self.assertEqual(plan(served),
                         {"goldenview": ["att_country", "nds", "b2b_box"]})

    def test_no_morning_ledger_means_nothing(self):
        self.assertEqual(plan(None), {})

    def test_served_orgs_are_left_alone(self):
        self.assertEqual(plan({"served": list(IDS), "queued": {}}), {})

    def test_recently_queued_is_not_queued_again(self):
        q = (NOW - dt.timedelta(minutes=20)).isoformat()
        self.assertEqual(plan({"served": ["alphalete"],
                               "queued": {"goldenview": q}}), {})

    def test_stale_queue_entry_is_retried(self):
        q = (NOW - dt.timedelta(minutes=run.NEWCOMER_REQUEUE_MIN + 5)).isoformat()
        self.assertIn("goldenview", plan({"served": ["alphalete"],
                                          "queued": {"goldenview": q}}))

    def test_nothing_captured_today_means_nothing(self):
        self.assertEqual(plan({"served": [], "queued": {}}, captured=()), {})


class ServedLedger(unittest.TestCase):
    def test_mark_merges_and_yesterday_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run._mark_served(out, ["alphalete"], TODAY)
            run._mark_served(out, ["goldenview", "alphalete"], TODAY)
            self.assertEqual(run._read_served(out, TODAY)["served"],
                             ["alphalete", "goldenview"])
            self.assertIsNone(run._read_served(out, TODAY + dt.timedelta(days=1)))


if __name__ == "__main__":
    unittest.main()

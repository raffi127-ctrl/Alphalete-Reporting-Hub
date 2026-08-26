"""Unit tests for the financial source watch — no network, no Sheets.

The three things that would silently break the watch and be noticed only months
later: an arrival that never announces, an announcement that repeats forever,
and a mailbox probe that cries wolf on every roster email.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from automations.financial_report import source_watch as sw

TAB = "Andrew Burton"
OFFICE = "KAIZEN SOLUTIONS, INC. (ANDRE BURTON JR-TX)"


def _by_owner(weeks=(dt.date(2026, 8, 15), dt.date(2026, 8, 22))):
    return {"andre burton": [{
        "office": OFFICE, "owner": "ANDRE BURTON JR", "state": "TX",
        "metrics": {"TOTAL FUNDS AVAILABLE": {w: 1000 for w in weeks}}}]}


class WatchTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = sw.WATCH_STATE
        sw.WATCH_STATE = Path(self._tmp.name) / "watch.json"
        # The real bridge reads three mapping files; the watch only needs the
        # one entry, and pinning it keeps the test off the filesystem.
        self.bridge = {"andrew burton": ["Andre Burton Jr"]}

    def tearDown(self):
        sw.WATCH_STATE = self._orig
        self._tmp.cleanup()

    # --- check ------------------------------------------------------------
    def test_no_source_is_not_found(self):
        r = sw.check({}, self.bridge)[0]
        self.assertFalse(r["found"])
        self.assertEqual(r["weeks"], [])

    def test_found_lists_only_weeks_that_carry_a_value(self):
        by_owner = _by_owner()
        by_owner["andre burton"][0]["metrics"]["PROFIT/LOSS"] = {
            dt.date(2026, 8, 22): -50, dt.date(2026, 8, 29): None}
        r = sw.check(by_owner, self.bridge)[0]
        self.assertTrue(r["found"])
        self.assertEqual(r["weeks"], [dt.date(2026, 8, 15), dt.date(2026, 8, 22)])

    def test_office_present_but_empty_still_counts_as_found(self):
        """An office with no numbers yet is 'arrived' — the source exists, and
        that is the fact the watch is for. `weeks` is what says it's empty."""
        r = sw.check({"andre burton": [{"office": OFFICE, "owner": "x",
                                        "state": "TX", "metrics": {}}]},
                     self.bridge)[0]
        self.assertTrue(r["found"])
        self.assertEqual(r["weeks"], [])

    # --- record / one-shot announcement -----------------------------------
    def test_arrival_announces_once_and_never_again(self):
        first = sw.record(sw.check(_by_owner(), self.bridge))[0]
        self.assertTrue(first["newly_arrived"])
        second = sw.record(sw.check(_by_owner(), self.bridge))[0]
        self.assertFalse(second["newly_arrived"])
        self.assertEqual(second["first_seen"], first["first_seen"])

    def test_dry_run_does_not_spend_the_arrival(self):
        sw.record(sw.check(_by_owner(), self.bridge), persist=False)
        live = sw.record(sw.check(_by_owner(), self.bridge))[0]
        self.assertTrue(live["newly_arrived"])

    def test_record_keeps_seen_mail(self):
        """record() and new_mentions() share one state entry; a replace instead
        of a merge would re-announce the same mail every single week."""
        sw.new_mentions([{"tab": TAB, "terms": ["Burton"],
                          "hits": [{"id": "<m1>", "from": "a@b.c",
                                    "subject": "s", "date": "d", "files": []}]}])
        sw.record(sw.check({}, self.bridge))
        st = json.loads(sw.WATCH_STATE.read_text(encoding="utf-8"))
        self.assertIn("<m1>", st[sw._key(TAB)]["seen_mail"])

    def test_new_mentions_only_returns_unseen_mail(self):
        hit = {"id": "<m1>", "from": "a@b.c", "subject": "s", "date": "d",
               "files": []}
        payload = [{"tab": TAB, "terms": ["Burton"], "hits": [hit]}]
        self.assertEqual(len(sw.new_mentions(payload)), 1)
        self.assertEqual(sw.new_mentions(payload), [])

    # --- notes ------------------------------------------------------------
    def test_note_fragment_reports_the_wait_too(self):
        waiting = sw.record(sw.check({}, self.bridge))
        self.assertIn("still no financial source", sw.note_fragment(waiting))
        arrived = sw.record(sw.check(_by_owner(), self.bridge))
        self.assertIn("ARRIVED", sw.note_fragment(arrived))

    # --- mailbox signal ---------------------------------------------------
    def test_real_financial_mail_is_signal(self):
        for subject, files in (
                ("Kaizen Solutions - Financial Summary W/E 8.29",
                 ["KAIZEN FINANCIAL SUMMARY 2026.08.29.xlsx"]),
                ("Andre Burton financials", []),          # figures in the body
                ("weekly books", ["Burton_Profit_Aug.xlsx"]),
                ("SAHIL SUMMARY REPORT 2026.08.29",
                 ["SAHIL SUMMARY REPORT 2026.08.29.xlsx"]),
        ):
            with self.subTest(subject=subject):
                self.assertTrue(sw._is_real_signal(
                    {"subject": subject, "files": files}, ["Burton", "Kaizen"]))

    def test_his_name_in_passing_is_not_signal(self):
        """Every one of these actually matched a free-text search for 'Burton'
        in the reporting mailbox (Eve 2026-08-26). None is a financial source."""
        for subject, files in (
                ("Headcount and Recruiting Totals: Wk Ending 08-22-26", []),
                ("Residential Telecom Tracker - RANKED", ["tracker.pdf"]),
                ("1 new commit pushed to the Hub (Eve)", []),
                ("Burton roster update", []),
                ("Country Sales Board 8/24", []),
        ):
            with self.subTest(subject=subject):
                self.assertFalse(sw._is_real_signal(
                    {"subject": subject, "files": files}, ["Burton", "Kaizen"]))


if __name__ == "__main__":
    unittest.main()

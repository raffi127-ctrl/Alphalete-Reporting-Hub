"""The snapshot that ships with the code, so a hosted page opens at once.

output/ is gitignored, so a Streamlit Cloud container starts with no
snapshot and every visitor pays a cold read -- about forty serial Sheets
calls against a quota the whole Hub shares. The deployed page sat on
"Reading the registries…" for minutes (Megan 2026-10-06). One person can
wait; a link sent to every ICD at once cannot, and they would queue behind
each other on the same quota.

This file is COMMITTED and DEPLOYED, so what it carries is the same
contract the ungated page has: SAFE_COLUMNS and nothing else.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_sales_board import enrollment as EN


class WhatShipped(unittest.TestCase):
    """Against the real committed file."""

    def setUp(self):
        if not EN.PUBLISHED.exists():
            self.skipTest("no published snapshot committed yet")
        self.blob = json.loads(EN.PUBLISHED.read_text())

    def test_it_holds_offices(self):
        self.assertGreater(len(self.blob["rows"]), 20)

    def test_every_key_is_in_the_safe_list(self):
        keys = {k for r in self.blob["rows"] for k in r}
        self.assertEqual(keys - set(EN.SAFE_COLUMNS), set())

    def test_no_private_scaffolding_shipped(self):
        """_relayed and _reading_tone decide colour; they are not data."""
        keys = {k for r in self.blob["rows"] for k in r}
        self.assertEqual([k for k in keys if str(k).startswith("_")], [])

    def test_it_says_when_it_was_taken(self):
        when = dt.datetime.fromisoformat(self.blob["taken"])
        self.assertLessEqual(when, dt.datetime.now() + dt.timedelta(minutes=5))

    def test_nobody_retired_is_in_it(self):
        names = {r.get("ICD") for r in self.blob["rows"]}
        for gone in ("Ron Dawson", "Ronald Dawson", "Cinthya",
                     "Hayden Wilson", "Salik Waqar", "Z Test"):
            self.assertNotIn(gone, names, gone)


class WritingOne(unittest.TestCase):

    ROW = {"ICD": "Someone", "LucyECO": "Active", "_relayed": True,
           "_reading_tone": "down", "Secret": "should not ship"}

    def test_it_strips_private_and_unknown_keys(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "pub.json"
            with mock.patch.object(EN, "rows", return_value=[dict(self.ROW)]):
                EN.publish_snapshot(out)
            got = json.loads(out.read_text())["rows"][0]
        self.assertIn("ICD", got)
        self.assertNotIn("_relayed", got)
        self.assertNotIn("_reading_tone", got)
        self.assertNotIn("Secret", got)

    def test_it_refuses_to_publish_nothing(self):
        """An empty file would blank the page for everyone it is sent to."""
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "pub.json"
            with mock.patch.object(EN, "rows", return_value=[]):
                with self.assertRaises(SystemExit):
                    EN.publish_snapshot(out)
            self.assertFalse(out.exists())


class ServingIt(unittest.TestCase):

    def _blob(self, age_hours):
        when = dt.datetime.now() - dt.timedelta(hours=age_hours)
        return {"taken": when.isoformat(timespec="seconds"),
                "rows": [{"ICD": "Shipped", "LucyECO": "Active"}]}

    def test_a_recent_shipped_copy_is_served_without_a_live_read(self):
        with mock.patch.object(EN, "_read_snapshot", return_value=([], None)), \
             mock.patch.object(EN, "_read_published",
                               return_value=([{"ICD": "Shipped"}],
                                             dt.datetime.now())), \
             mock.patch.object(EN, "rows") as live:
            got, _taken = EN.rows_cached()
        self.assertEqual(got[0]["ICD"], "Shipped")
        live.assert_not_called()

    def test_an_old_shipped_copy_does_not_block_a_live_read(self):
        old = dt.datetime.now() - dt.timedelta(
            hours=EN.PUBLISHED_MAX_HOURS + 1)
        with mock.patch.object(EN, "_read_snapshot", return_value=([], None)), \
             mock.patch.object(EN, "_read_published",
                               return_value=([{"ICD": "Stale"}], old)), \
             mock.patch.object(EN, "rows",
                               return_value=[{"ICD": "Fresh"}]), \
             mock.patch.object(EN, "_write_snapshot"):
            got, _t = EN.rows_cached()
        self.assertEqual(got[0]["ICD"], "Fresh")

    def test_a_failed_live_read_falls_back_to_what_shipped(self):
        """However old. A page with rows beats a page with an apology."""
        old = dt.datetime.now() - dt.timedelta(days=9)
        with mock.patch.object(EN, "_read_snapshot", return_value=([], None)), \
             mock.patch.object(EN, "_read_published",
                               return_value=([{"ICD": "Shipped"}], old)), \
             mock.patch.object(EN, "rows", return_value=[]):
            got, taken = EN.rows_cached()
        self.assertEqual(got[0]["ICD"], "Shipped")
        self.assertEqual(taken, old)


if __name__ == "__main__":
    unittest.main()

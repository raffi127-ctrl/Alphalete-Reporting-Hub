"""A library read that FAILS must never look like an EMPTY library.

2026-11-19: the 2:45am schedule guard's Report Library read failed, the
coverage sweep took the empty answer to mean "none of these 109 reports has a
card", rewrote every row at 3:27-3:31, and hub_library_watch emailed Megan one
"Hub card updated" per row (100+). Reads that failed mid-write also appended
duplicate rows. These tests pin the three fixes:
  1. a failed read raises LibraryUnreadable (never set());
  2. the sweep / resolver write NOTHING when the library can't be read;
  3. a refresh that changes nothing writes nothing, and keeps the card's
     original registration time (a fresh stamp is what made each rewrite an
     emailed "edit").
No network: the library worksheet is a fake.

  python -m unittest automations.day_orchestrator.test_hub_coverage_unreadable
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from automations.day_orchestrator import hub_coverage as hc

RID = "ztest_unreadable_probe"   # not a real report, not offboarded


class _Cell:
    def __init__(self, row):
        self.row = row


class _FakeWS:
    def __init__(self, find_fails=False):
        self.rows = [list(hc.SHARED_LIBRARY_HEADERS)]
        self.find_fails = find_fails
        self.updates = 0
        self.appends = 0

    def get_all_records(self):
        head = self.rows[0]
        return [dict(zip(head, r)) for r in self.rows[1:]]

    def find(self, value, in_column=1):
        if self.find_fails:
            raise RuntimeError("quota")
        for i, r in enumerate(self.rows, start=1):
            if i > 1 and r[in_column - 1] == value:
                return _Cell(i)
        return None

    def row_values(self, n):
        return list(self.rows[n - 1])

    def update(self, values, rng, value_input_option=None):
        n = int(rng.split(":")[0][1:])
        self.rows[n - 1] = list(values[0])
        self.updates += 1

    def append_row(self, row, value_input_option=None):
        self.rows.append(list(row))
        self.appends += 1


def _broken_ws():
    raise RuntimeError("429 read quota")


class UnreadableLibraryTest(unittest.TestCase):
    def setUp(self):
        hc._forget_library_cache()

    def tearDown(self):
        hc._forget_library_cache()

    def test_failed_read_raises_not_empty(self):
        with mock.patch.object(hc, "_library_ws", _broken_ws):
            with self.assertRaises(hc.LibraryUnreadable):
                hc._library_card_ids()
            with self.assertRaises(hc.LibraryUnreadable):
                hc._auto_library_ids()
            with self.assertRaises(hc.LibraryUnreadable):
                hc.existing_card_ids()

    def test_sweep_writes_nothing_when_unreadable(self):
        with mock.patch.object(hc, "_library_ws", _broken_ws), \
             mock.patch.object(hc, "ensure_library_card") as ens:
            with self.assertRaises(hc.LibraryUnreadable):
                hc.sync(dry_run=False)
            ens.assert_not_called()

    def test_resolver_writes_nothing_when_unreadable(self):
        with mock.patch.object(hc, "_library_ws", _broken_ws), \
             mock.patch.object(hc, "ensure_library_card") as ens:
            self.assertEqual(hc.resolve_card(RID, create=True), RID)
            self.assertIsNone(hc.resolve_card(RID, create=False))
            ens.assert_not_called()

    def test_failed_lookup_does_not_append_a_duplicate(self):
        ws = _FakeWS(find_fails=True)
        with mock.patch.object(hc, "_library_ws", lambda: ws):
            ok, msg = hc.ensure_library_card(RID, "Z Test")
        self.assertFalse(ok, msg)
        self.assertEqual(ws.appends, 0)
        self.assertEqual(ws.updates, 0)


class RefreshIsQuietTest(unittest.TestCase):
    def setUp(self):
        hc._forget_library_cache()

    def tearDown(self):
        hc._forget_library_cache()

    def test_unchanged_refresh_writes_nothing_and_keeps_first_stamp(self):
        ws = _FakeWS()
        with mock.patch.object(hc, "_library_ws", lambda: ws):
            ok, _ = hc.ensure_library_card(RID, "Z Test")
            self.assertTrue(ok)
            self.assertEqual(ws.appends, 1)
            # Age the stored stamps, as if the card was made months ago.
            row = ws.rows[1]
            meta = json.loads(row[5])
            meta["auto_registered_at"] = "2026-01-01 00:00"
            row[4], row[5] = "2026-01-01 00:00", json.dumps(meta)

            ok, msg = hc.ensure_library_card(RID, "Z Test")
            self.assertTrue(ok)
            self.assertIn("already up to date", msg)
            self.assertEqual(ws.updates, 0)

            # A real change still writes, and still keeps the first stamp.
            ok, _ = hc.ensure_library_card(RID, "Z Test Renamed")
            self.assertTrue(ok)
            self.assertEqual(ws.updates, 1)
            self.assertEqual(ws.appends, 1)
            row = ws.rows[1]
            self.assertEqual(row[4], "2026-01-01 00:00")
            self.assertEqual(json.loads(row[5])["auto_registered_at"],
                             "2026-01-01 00:00")


if __name__ == "__main__":
    unittest.main()

"""A missing disposition BUCKET must not fail an office's whole pull.

Run:  PYTHONPATH=. .venv/Scripts/python.exe -m unittest \
          automations.total_knocks.test_header_tolerance

WHAT THIS GUARDS (2026-08-31). Two `/knocks` requests died the same morning on
the same all-or-nothing header check:

* Stergios Kasapidis — "Disposition table is missing expected column(s):
  Inaccessible". ONE bucket. His office's TeleMapper page carries the whole
  house set plus buckets nobody else has (bill payer not home, credit check,
  already has AT&T, battery, coverage, device) and simply has no Inaccessible
  bucket. The disposition vocabulary is per-office; requiring the full canonical
  set means any office that words its doors differently gets no board at all.
* Francisco Castillo — the SAME error listing every column, which is what an
  empty header row looks like after the check resolves nothing. That is a
  stalled grid (`_navigate` gave up), and it read as a data problem instead of
  a failed scrape, so nothing retried it.

The contract, in both directions:

  headers present, optional bucket absent → scrape it, that bucket reads 0
  headers present, ID/Rep/Total Knocks absent → RuntimeError (real shape problem)
  NO headers at all → KnocksPullFailed (stalled grid; retried, never a 0 board)

The reverse half matters as much: an office whose Total Knocks column vanished
must NOT quietly board zeros for everyone.
"""
from __future__ import annotations

import unittest

from automations.total_knocks import pull as knocks
from automations.total_knocks.pull import KnocksPullFailed

# Stergios Kasapidis' live header row, 2026-08-31 — the house set MINUS
# Inaccessible, plus his office-only buckets.
STERGIOS = [
    "ID", "Rep", "Total Leads Knocked", "Total Knocks", "First Knock",
    "Last Knock", "No answer", "Talk To - Not Interested",
    "Presentation – Not Interested", "Come Back", "Sale", "Do Not Knock",
    "Already has AT&T", "Battery", "Bill payer not home", "Close", "Coverage",
    "Credit check", "Device",
]


def _idx(headers):
    return {knocks._norm(h): i for i, h in enumerate(headers)}


def _house_columns():
    skip = {knocks.COL_TOTAL_TALK_TO, *knocks.TIME_TRACKER_COLUMNS}
    return [c for c in knocks.SHEET_COLUMNS if c not in skip]


class OptionalBuckets(unittest.TestCase):
    def test_an_office_without_inaccessible_still_resolves(self):
        """THE BUG: one absent bucket used to fail the entire office."""
        want, absent = knocks._resolve_columns(
            _idx(STERGIOS), _house_columns(), verbose=False)
        self.assertEqual(absent, [knocks.COL_INACCESSIBLE])
        self.assertIn(knocks.COL_TOTAL_KNOCKS, want)
        self.assertIn(knocks.COL_SALE, want)

    def test_every_present_bucket_keeps_its_own_index(self):
        """Tolerance must not shift columns — indices stay live-header based."""
        want, _ = knocks._resolve_columns(
            _idx(STERGIOS), _house_columns(), verbose=False)
        self.assertEqual(want[knocks.COL_ID], 0)
        self.assertEqual(want[knocks.COL_SALE], STERGIOS.index("Sale"))

    def test_office_only_buckets_are_ignored_not_boarded(self):
        """'Credit check' is real data, but it is not a Sheet column — the pull
        stays keyed to the canonical set."""
        want, _ = knocks._resolve_columns(
            _idx(STERGIOS), _house_columns(), verbose=False)
        self.assertNotIn("Credit check", want)


class RequiredColumns(unittest.TestCase):
    def test_a_missing_total_knocks_still_raises(self):
        """The reverse regression: tolerance must not board zeros for an office
        whose spine column disappeared."""
        headers = [h for h in STERGIOS if h != "Total Knocks"]
        with self.assertRaises(RuntimeError) as ctx:
            knocks._resolve_columns(_idx(headers), _house_columns(),
                                    verbose=False)
        self.assertIn("Total Knocks", str(ctx.exception))

    def test_a_required_failure_is_not_the_retriable_kind(self):
        """A real shape problem is NOT a stalled grid — retrying won't fix it."""
        headers = [h for h in STERGIOS if h != "Rep"]
        with self.assertRaises(RuntimeError) as ctx:
            knocks._resolve_columns(_idx(headers), _house_columns(),
                                    verbose=False)
        self.assertNotIsInstance(ctx.exception, KnocksPullFailed)


class EmptyHeaderRow(unittest.TestCase):
    def test_no_headers_is_a_failed_pull_not_a_column_list(self):
        """Francisco Castillo's case: the answer must name the stall, and be
        the typed failure the runner retries."""
        with self.assertRaises(KnocksPullFailed) as ctx:
            knocks._resolve_columns({}, _house_columns(), verbose=False)
        self.assertIn("never rendered", str(ctx.exception))

    def test_it_does_not_list_every_column_as_missing(self):
        """The old message was a wall of column names that sent everyone
        looking for a table-shape problem that wasn't there."""
        with self.assertRaises(KnocksPullFailed) as ctx:
            knocks._resolve_columns({}, _house_columns(), verbose=False)
        self.assertNotIn(knocks.COL_TALK_TO_NI, str(ctx.exception))


class WirelessShape(unittest.TestCase):
    """The NDS/wireless walk shares the same resolver — one behaviour, not two."""

    def test_wireless_columns_tolerate_a_missing_bucket(self):
        from automations.rashad_metrics import knocks_pull as rk
        headers = [c for c in rk._WIRELESS_COLUMNS
                   if c != knocks.COL_INACCESSIBLE]
        want, absent = knocks._resolve_columns(
            _idx(headers), rk._WIRELESS_COLUMNS,
            label="Wireless disposition", verbose=False)
        self.assertEqual(absent, [knocks.COL_INACCESSIBLE])
        self.assertIn(knocks.COL_TOTAL_KNOCKS, want)


if __name__ == "__main__":
    unittest.main()

"""A week-rolled pull must never overwrite a good fill with the FAIL marker.

2026-09-07: the WiFi outage that took the whole Lucy fleet down at ~14:03 CDT
killed the Monday 2pm Leader's Call run mid-flight. The re-run on TUESDAY could
not succeed — Fiber/NDS/B2B read their relative "This Week" filter, which had
already rolled — and it wrote '⚠ PULL FAILED' over those three sections. Had
Monday's fill landed first, that re-run would have erased it: the tab is the
only copy of the week (the deck is rebuilt from it, `_results_from_tab`).

A week-rolled failure is the one pull error that re-running cannot fix, so it
HOLDS whatever real rows the section already has instead of flagging them.
"""
import unittest
from unittest import mock

from automations.leaders_call import run as lc


class FakeWS:
    def __init__(self, grid):
        self.grid = [list(r) for r in grid]
        self.updates = []
        self.inserts = []
        self.deletes = []

    def get_all_values(self):
        return self.grid

    def update(self, rng, body, value_input_option=None):
        self.updates.append((rng, body))

    def insert_rows(self, rows, at):
        self.inserts.append((at, len(rows)))

    def delete_rows(self, start, end):
        self.deletes.append((start, end))


FILLED = [
    ["Alphalete Leader's Call", "", ""],
    ["Fiber - 12+ Apps", "", ""],
    ["Rep's Name", "Owner's Name", "Apps"],
    ["Ana Griffin", "Rafael Hidalgo", "18"],
    ["Hank Tran", "Kash Rai", "14"],
    ["BOX - 8+ Apps", "", ""],
    ["Rep's Name", "Owner's Name", "Apps"],
    ["Emily Garcia", "Roshan Ahmad", "20"],
]


def _write(grid, results):
    ws = FakeWS(grid)
    with mock.patch("automations.recruiting_report.fill._retry",
                    lambda fn, *a, **k: fn(*a, **k)):
        log = lc.write_report(ws, results, dry_run=False)
    return ws, log


class WeekRollHoldTest(unittest.TestCase):
    def test_week_rolled_leaves_a_filled_section_alone(self):
        rolled = lc.PullFailure(
            "fiber", "WRONG WEEK: data is for ['09-07'], expected 2026-08-31..2026-09-06",
            week_rolled=True)
        ws, log = _write(FILLED, {"Fiber": rolled})
        self.assertIn("[hold] Fiber", "\n".join(log))
        self.assertEqual(ws.updates, [])
        self.assertEqual(ws.inserts, [])
        self.assertEqual(ws.deletes, [])

    def test_an_ordinary_pull_failure_still_flags(self):
        """Only the week roll holds — a real Tableau failure must still be loud,
        so nobody reads last week's numbers as this week's."""
        ws, log = _write(FILLED, {"Fiber": lc.PullFailure("fiber", "Timeout 30000ms")})
        self.assertIn("[FAIL] Fiber", "\n".join(log))
        self.assertEqual(len(ws.updates), 1)
        self.assertTrue(ws.updates[0][1][0][0].startswith(lc._PULL_FAILED_PREFIX))

    def test_week_rolled_still_flags_an_EMPTY_section(self):
        """Nothing to protect: the marker is the most honest thing to show."""
        empty = [r for r in FILLED if r[0] not in ("Ana Griffin", "Hank Tran")]
        rolled = lc.PullFailure("fiber", "0 rows after 3 tries", week_rolled=True)
        ws, log = _write(empty, {"Fiber": rolled})
        self.assertIn("[FAIL] Fiber", "\n".join(log))
        self.assertEqual(len(ws.updates), 1)

    def test_week_rolled_overwrites_an_existing_marker(self):
        """A section already carrying the marker holds no data either."""
        flagged = [r if r[0] != "Ana Griffin"
                   else [lc._PULL_FAILED_PREFIX + " — not updated this week", "", ""]
                   for r in FILLED if r[0] != "Hank Tran"]
        rolled = lc.PullFailure("fiber", "WRONG WEEK", week_rolled=True)
        ws, log = _write(flagged, {"Fiber": rolled})
        self.assertIn("[FAIL] Fiber", "\n".join(log))


if __name__ == "__main__":
    unittest.main()

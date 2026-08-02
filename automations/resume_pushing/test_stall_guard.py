"""Regression tests for the extract_loop STALL guard (resume_pushing/run.py).

The guard exists so a wedged extractor (console logs in, but the per-resume reads
are Cloudflare-challenged, so "Ready For Extraction" never drops) BAILS fast with
a non-zero exit instead of grinding the 30-cycle / ~11-hour safety cap. Fast-fail
is what lets the next q10min pass re-copy a fresh profile (self-heal) and the
deploy wrapper's fail-streak notifier fire. These tests pin that behaviour so a
future edit to the loop can't silently bring the 11-hour grind back.

No browser / no network: ready_for_extraction + run_extract_once are stubbed.
"""
import unittest

from automations.resume_pushing import run as R


class _FakePage:
    def reload(self, **kwargs):
        pass

    def wait_for_timeout(self, *args):
        pass


def _drive(counts, res="reset"):
    """Run extract_loop with ready_for_extraction returning `counts` in order
    (repeating the last value once exhausted, for the final end-count read).
    `res` is what run_extract_once returns each cycle: "reset" (clean finish) or
    "cap" (hit the wait cap with no Reset — the fast-bail signal)."""
    it = iter(counts)
    last = [counts[-1]]

    def _read(page):
        try:
            return next(it)
        except StopIteration:
            return last[0]

    orig_read, orig_once = R.ready_for_extraction, R.run_extract_once
    R.ready_for_extraction = _read
    R.run_extract_once = lambda page: res
    try:
        return R.extract_loop(_FakePage(), dry_run=False)
    finally:
        R.ready_for_extraction, R.run_extract_once = orig_read, orig_once


class StallGuardTest(unittest.TestCase):
    def test_flat_queue_stalls_fast(self):
        # Count never drops (noise around 72) -> bail, don't grind 30 cycles.
        with self.assertRaises(R.ExtractionStalled):
            _drive([72, 74, 73, 75, 76, 78])

    def test_partial_then_wedge_stalls(self):
        # Drops once (60->30) then wedges flat -> still a stall vs best-seen.
        with self.assertRaises(R.ExtractionStalled):
            _drive([60, 30, 31, 30, 32, 30])

    def test_healthy_run_completes(self):
        # Clears in a couple of cycles -> no stall, ends at 0.
        self.assertEqual(_drive([72, 22, 0]), 0)

    def test_slow_but_progressing_never_stalls(self):
        # Drops every cycle, just slowly -> must NOT false-positive.
        self.assertEqual(_drive([80, 60, 55, 30, 5, 0]), 0)

    def test_cap_with_no_drop_bails_after_one_cycle(self):
        # run_extract_once hit the cap (no Reset) AND the count didn't move ->
        # definitive wedge, bail after ONE cycle (don't wait out STALL_CYCLES).
        with self.assertRaises(R.ExtractionStalled):
            _drive([76, 76, 76], res="cap")

    def test_cap_but_dropping_is_a_healthy_big_batch(self):
        # A big batch can hit the cap yet still DROP the count (partial progress);
        # that's healthy-slow, not a wedge -> must complete, never raise.
        self.assertEqual(_drive([120, 70, 20, 0], res="cap"), 0)


if __name__ == "__main__":
    unittest.main()

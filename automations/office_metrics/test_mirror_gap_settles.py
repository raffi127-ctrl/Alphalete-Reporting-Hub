"""A mirror copy is only MISSING once it settles.

WHY (trang, 2026-09-27). The copy check is the last thing an office run does,
and the board it is most likely to call missing is the one posted seconds
earlier. Slack returns from files_upload_v2 when the UPLOAD finishes and posts
the share message once it has finished PROCESSING the file — the same lag
slack_metrics_post.wait_for_share exists for.

That day #freshsuccess-all-leaders got ":camera_with_flash: Tableau Metrics" at
...480.50 and #freshsuccess-team got its copy at ...482.83 — but _mirror_gaps
had already read the mirror thread and called the board missing, so the run
posted an INCOMPLETE incident for a board that was in the channel the whole
time.

The two halves this pins:
  - a board that shows up on a later read is NOT a gap (the trang case), and
  - a board that never shows up still IS one — the settle must not become a way
    for a real miss to time out into green [[feedback_green_means_delivered]].
"""
from __future__ import annotations

import datetime as dt
import unittest

from automations.office_metrics import runner

TODAY = dt.date(2026, 9, 27)
PRIMARY = "C07TRPJ7HFH"          # #freshsuccess-all-leaders
MIRROR = "C07QS80KJL8"           # #freshsuccess-team
BOARDS = [":credit_card: New Internet ABP %", ":camera_with_flash: Tableau Metrics"]


class _FakeClient:
    """Replies keyed by channel. `late` is the reply the mirror only starts
    returning on read number `late_after` — Slack finishing the file share."""

    def __init__(self, mirror_has, late=None, late_after=0):
        self.mirror_has = list(mirror_has)
        self.late, self.late_after = late, late_after
        self.mirror_reads = 0

    def conversations_replies(self, channel, ts, limit=200):
        if channel == PRIMARY:
            texts = BOARDS
        else:
            self.mirror_reads += 1
            texts = list(self.mirror_has)
            if self.late and self.mirror_reads > self.late_after:
                texts.append(self.late)
        return {"messages": [{"text": "*Metrics for: X*"}]
                            + [{"text": t} for t in texts]}


class _Patched:
    """_mirror_gaps reaches into slack_metrics_post for the thread lookups; both
    are one-line stubs here so the test is about the settle and nothing else."""

    def __enter__(self):
        from automations.shared import slack_metrics_post as smp
        self.smp, self.find, self.twin = (
            smp, smp.find_metrics_thread_ts, smp._mirror_thread_ts)
        smp.find_metrics_thread_ts = lambda *a, **k: "1790509220.492139"
        smp._mirror_thread_ts = lambda *a, **k: "1790509221.165729"
        # A real but negligible sleep, not a no-op: the settle loop's exit is
        # a wall-clock deadline, so a zero-cost sleep would spin it hundreds of
        # times in the "still missing" test instead of re-reading a few.
        self.sleep = runner.time.sleep
        runner.time.sleep = lambda s: self.sleep(0.02)
        return self

    def __exit__(self, *a):
        self.smp.find_metrics_thread_ts = self.find
        self.smp._mirror_thread_ts = self.twin
        runner.time.sleep = self.sleep


class MirrorGapSettles(unittest.TestCase):

    def test_a_board_that_lands_on_a_later_read_is_not_a_gap(self):
        """The trang case: the copy was 2.3s behind, not absent."""
        c = _FakeClient(mirror_has=BOARDS[:1], late=BOARDS[1], late_after=1)
        with _Patched():
            gaps = runner._mirror_gaps(c, PRIMARY, [MIRROR], TODAY)
        self.assertEqual(gaps, [], "a copy that settles must not be reported")
        self.assertGreater(c.mirror_reads, 1, "it has to actually re-read")

    def test_a_board_that_never_lands_is_still_a_gap(self):
        """The settle must not turn a real miss into a timeout that reads green."""
        c = _FakeClient(mirror_has=BOARDS[:1])
        with _Patched():
            gaps = runner._mirror_gaps(c, PRIMARY, [MIRROR], TODAY, settle_s=0.1)
        self.assertEqual(gaps, [(MIRROR, [BOARDS[1]])])
        self.assertGreater(c.mirror_reads, 1, "it re-read and it is STILL short")

    def test_a_clean_run_reads_each_mirror_once(self):
        """No gap on the first pass => no waiting. The happy path pays nothing."""
        c = _FakeClient(mirror_has=BOARDS)
        with _Patched():
            gaps = runner._mirror_gaps(c, PRIMARY, [MIRROR], TODAY)
        self.assertEqual(gaps, [])
        self.assertEqual(c.mirror_reads, 1)


if __name__ == "__main__":
    unittest.main()

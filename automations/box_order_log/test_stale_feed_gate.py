"""`should_block_send` must catch a feed that missed a completed day — WITHOUT
false-blocking the Mondays where Sunday simply had no Box sales.

WHY (Megan 2026-09-15). The gate counted raw calendar days behind today and
blocked at >= 4. The real cap slipped under it: on Tuesday 9/15 the feed sat at
Saturday 9/12 — 3 days, one short — so the gate passed and box_order_log posted
`THIS 9.14-9.20 paid=0` to two of Carlos's channels. A whole empty week, and the
gate said fine.

Lowering the constant would have been worse than the bug. Sunday legitimately
has no Box sales, so on a Monday "newest = Saturday" is 2 days behind and
perfectly healthy; a smaller number blocks Carlos most Mondays, and a false
block is an owner with NO report — worse than the thing being prevented.

So the test is "has the feed reached the newest COMPLETED reporting day", with
_probe_box_daily's tie-break for the case a quiet day and a dead feed look
identical in one pull: did the extract move further today than ever before?

    python -m unittest automations.box_order_log.test_stale_feed_gate
"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.box_order_log import window as W

D = dt.date
TUE = D(2026, 9, 15)      # the real incident day
MON = D(2026, 9, 14)
SUN = D(2026, 9, 13)
SAT = D(2026, 9, 12)
FRI = D(2026, 9, 11)


class _Tmp(unittest.TestCase):
    """Each test gets a private high-water file — never the real one."""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.dir = Path(self._d.name)
        patch = mock.patch.object(W, "OUTPUT_DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)

    def _history(self, day, prior=None, mx=None):
        (self.dir / "box_orderlog_reach.json").write_text(json.dumps(
            {"date": day.isoformat(),
             "prior": prior.isoformat() if prior else None,
             "max": mx.isoformat() if mx else None}))


class TheIncident(_Tmp):

    def test_2026_09_15_would_now_be_blocked(self):
        """Tue, feed stuck at Sat, hasn't moved since yesterday -> block."""
        self._history(D(2026, 9, 14), prior=None, mx=SAT)   # yesterday reached Sat
        reason = W.should_block_send(SAT, today=TUE)
        self.assertTrue(reason, "the 9/15 pull must not be deliverable")
        self.assertIn("STALE FEED", reason)
        self.assertIn("2026-09-14", reason)

    def test_the_old_calendar_rule_alone_let_it_through(self):
        """Pin the gap that existed: 3 days behind is under the >=4 threshold."""
        self.assertEqual((TUE - SAT).days, 3)
        self.assertLess((TUE - SAT).days, W.BLOCK_SEND_MIN_DAYS_BEHIND)


class QuietSundayMustStillSend(_Tmp):
    """The false-block this fix exists to avoid."""

    def test_monday_with_a_no_sales_sunday_sends(self):
        # Mon 9/14: newest completed day is Sun 9/13. Feed reaches Sat — but it
        # MOVED today (yesterday it only had Fri), so Sunday is simply empty.
        self._history(D(2026, 9, 13), prior=None, mx=FRI)
        self.assertEqual(W.should_block_send(SAT, today=MON), "")

    def test_monday_whose_feed_really_died_is_blocked(self):
        # Same shape, but the extract has NOT moved since before today.
        self._history(D(2026, 9, 13), prior=SAT, mx=SAT)
        self.assertTrue(W.should_block_send(SAT, today=MON))

    def test_a_current_feed_is_never_blocked(self):
        self._history(D(2026, 9, 14), prior=SAT, mx=MON)
        self.assertEqual(W.should_block_send(MON, today=TUE), "")

    def test_a_feed_ahead_of_target_is_never_blocked(self):
        self.assertEqual(W.should_block_send(TUE, today=TUE), "")


class FailsOpen(_Tmp):
    """This gate can refuse to deliver, so every uncertainty resolves to SEND."""

    def test_no_history_falls_back_to_the_calendar_rule(self):
        # Nothing to compare against -> must not block on the new rule alone.
        self.assertEqual(W.should_block_send(SAT, today=TUE), "")

    def test_but_the_calendar_backstop_still_fires_when_far_behind(self):
        reason = W.should_block_send(D(2026, 9, 5), today=TUE)
        self.assertTrue(reason)
        self.assertIn("CAPPED PULL", reason)

    def test_a_broken_week_module_never_blocks(self):
        with mock.patch.dict("sys.modules",
                             {"automations.org_sales_board.week": None}):
            self.assertEqual(W._behind_completed_day(SAT, TUE), "")

    def test_no_completed_day_yet_never_blocks(self):
        with mock.patch("automations.org_sales_board.week.completed_days",
                        return_value=[]):
            self.assertEqual(W._behind_completed_day(SAT, TUE), "")

    def test_an_unwritable_history_dir_never_raises(self):
        with mock.patch.object(W, "OUTPUT_DIR", Path("/proc/nonexistent/nope")):
            self.assertIsNone(W._extract_moved_today(SAT, TUE))

    def test_no_dates_at_all_is_still_the_hard_block(self):
        self.assertIn("no dated sales", W.should_block_send(None, today=TUE))


class HighWaterMark(_Tmp):

    def test_it_freezes_prior_on_the_first_pull_of_a_day(self):
        self._history(MON, prior=FRI, mx=SAT)
        W._extract_moved_today(SAT, TUE)
        data = json.loads((self.dir / "box_orderlog_reach.json").read_text())
        self.assertEqual(data["prior"], SAT.isoformat())   # yesterday's max
        self.assertEqual(data["date"], TUE.isoformat())

    def test_later_pulls_the_same_day_keep_that_prior(self):
        self._history(MON, prior=FRI, mx=SAT)
        W._extract_moved_today(SAT, TUE)
        self.assertIs(W._extract_moved_today(SAT, TUE), False)
        self.assertIs(W._extract_moved_today(MON, TUE), True)

    def test_within_day_max_only_climbs(self):
        self._history(TUE, prior=FRI, mx=MON)
        W._extract_moved_today(SAT, TUE)
        data = json.loads((self.dir / "box_orderlog_reach.json").read_text())
        self.assertEqual(data["max"], MON.isoformat())


if __name__ == "__main__":
    unittest.main()

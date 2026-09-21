"""readiness: the build waits for today's fills instead of trusting a clock.

    python -m unittest automations.captainship_drafts.test_readiness
"""
import datetime as dt
import unittest
from unittest import mock

from automations.captainship_drafts import readiness as R

TODAY = dt.date(2026, 9, 21)


def _tab(*boxes):
    """A/B grid: each box = (label, date label, [B values under it])."""
    grid = []
    for label, date, vals in boxes:
        grid.append([label, date])
        grid.append(["Captainship Avg", vals[0] if vals else ""])
        grid.append(["Rep", "%"])
        for v in vals[1:]:
            grid.append(["Someone", v])
    return grid


class StaleBlocks(unittest.TestCase):
    def test_filled_today_is_ready(self):
        g = _tab(("CANCEL 0-30", "Mon 9/21/26", ["12.0%", "10%"]),
                 ("CANCEL 30-60", "Mon 9/21/26", ["20.1%"]))
        self.assertEqual(R.stale_blocks(g, TODAY), [])

    def test_yesterday_is_stale(self):
        # 2026-09-21: the drafts went up with 9/20 as the newest day.
        g = _tab(("ACTIVATION 0-30", "Sun 9/20/26", ["80%"]))
        self.assertEqual(R.stale_blocks(g, TODAY),
                         ["ACTIVATION 0-30: newest day 9/20"])

    def test_header_without_numbers_is_stale(self):
        # The fill inserts the dated column BEFORE writing it; a header alone
        # must not read as filled. The '%' label under Rep is not a number.
        g = _tab(("ABP", "Mon 9/21/26", ["", ""]))
        self.assertEqual(R.stale_blocks(g, TODAY),
                         ["ABP: 9/21 column is empty"])

    def test_one_stale_box_among_fresh(self):
        g = _tab(("CANCEL 0-30", "Mon 9/21/26", ["12%"]),
                 ("CANCEL 30-60", "Sun 9/20/26", ["20%"]))
        self.assertEqual(R.stale_blocks(g, TODAY),
                         ["CANCEL 30-60: newest day 9/20"])

    def test_tab_without_dates_is_not_held_on(self):
        self.assertEqual(R.stale_blocks([["Churn Tiers", "2%"], []], TODAY), [])


class WaitForFills(unittest.TestCase):
    def _run(self, checks, start, **kw):
        clock = {"t": start}

        def now():
            return clock["t"]

        def sleep(s):
            clock["t"] += dt.timedelta(seconds=s)

        seq = iter(checks)
        with mock.patch.object(R, "_open_all",
                               return_value={"id": (object(), ["T"])}), \
             mock.patch.object(R, "check", side_effect=lambda *a, **k: next(seq)):
            out = R.wait_for_fills([], TODAY, logfn=lambda m: None, now=now,
                                   sleep=sleep, alert=False, **kw)
        return out, clock["t"]

    def test_fresh_builds_immediately(self):
        start = dt.datetime(2026, 9, 21, 6, 45)
        out, end = self._run([{}], start)
        self.assertEqual((out, end), ({}, start))

    def test_waits_until_the_fill_lands(self):
        start = dt.datetime(2026, 9, 21, 6, 45)
        out, end = self._run([{"T": ["x"]}, {"T": ["x"]}, {}], start)
        self.assertEqual(out, {})
        self.assertEqual(end, start + dt.timedelta(minutes=10))

    def test_gives_up_at_the_deadline_and_reports_it(self):
        start = dt.datetime(2026, 9, 21, 7, 40)
        stale = {"T": ["x"]}
        out, end = self._run([stale] * 5, start)
        self.assertEqual(out, stale)
        self.assertEqual(end, dt.datetime(2026, 9, 21, 7, 45))

    def test_never_raises(self):
        with mock.patch.object(R, "_open_all", side_effect=RuntimeError("429")):
            self.assertEqual(R.wait_for_fills([], TODAY, logfn=lambda m: None,
                                              alert=False), {})


if __name__ == "__main__":
    unittest.main()

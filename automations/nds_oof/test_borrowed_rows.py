"""borrowed_rows: Cinthya + Nathaly off Raf's 'Lucy Knocks' row, board only."""
import datetime as dt
import json
import unittest
from unittest import mock

from automations.nds_oof import run as R


class _WS:
    def __init__(self, lines):
        self.lines = lines

    def get_all_values(self):
        return [["Key", "Owner", "Day", "At", "Rows JSON"]] + self.lines


def _line(key, day, rows, at="2026-11-03T14:31:00"):
    return [key, key.title(), day.isoformat(), at, json.dumps(rows)]


RAF = [{"Rep": "Cinthya Reyes Roadtrip", "Total Knocks": "41", "First Knock": "1:40 PM", "Talk To's": "9"},
       {"Rep": "Nathaly Benitez", "Total Knocks": "27", "First Knock": "2:05 PM", "Talk To's": "4"},
       {"Rep": "Jorge Gramajo", "Total Knocks": "60", "First Knock": "1:35 PM", "Talk To's": "12"}]
OWN = [{"Rep": "Sebastian Avellaneda", "Total Knocks": "30", "First Knock": "2:01 PM"}]


class Borrowed(unittest.TestCase):
    def _run(self, lines, own=OWN, today=dt.date(2026, 11, 3)):
        ws = _WS(lines)
        with mock.patch("automations.owner_knocks_hourly.share._book", lambda: None), \
             mock.patch("automations.owner_knocks_hourly.share._tab", lambda book, create=False: ws), \
             mock.patch.object(R, "_log"):
            return R.borrowed_rows(today, list(own))

    def test_two_names_come_over_board_shape_only(self):
        got = self._run([_line("rafael", dt.date(2026, 11, 3), RAF)])
        self.assertEqual([r["Rep"] for r in got], ["Cinthya Reyes Roadtrip", "Nathaly Benitez"])
        for r in got:                       # trimmed to our own rows' columns
            self.assertEqual(set(r), {"Rep", "Total Knocks", "First Knock"})
        self.assertEqual(got[0]["Total Knocks"], "41")

    def test_yesterdays_row_is_ignored(self):
        self.assertEqual(self._run([_line("rafael", dt.date(2026, 11, 2), RAF)]), [])

    def test_other_keys_ignored_and_no_double(self):
        own = OWN + [{"Rep": "Nathaly Benitez", "Total Knocks": "5", "First Knock": "2:10 PM"}]
        got = self._run([_line("steve", dt.date(2026, 11, 3), RAF),
                         _line("rafael", dt.date(2026, 11, 3), RAF)], own=own)
        self.assertEqual([r["Rep"] for r in got], ["Cinthya Reyes Roadtrip"])

    def test_no_own_rows_keeps_every_column(self):
        got = self._run([_line("rafael", dt.date(2026, 11, 3), RAF)], own=[])
        self.assertEqual(len(got), 2)
        self.assertIn("Talk To's", got[0])

    def test_tab_down_means_no_rows_not_a_crash(self):
        with mock.patch("automations.owner_knocks_hourly.share._book", side_effect=RuntimeError("403")), \
             mock.patch.object(R, "_log"):
            self.assertEqual(R.borrowed_rows(dt.date(2026, 11, 3), list(OWN)), [])

    def test_window_starts_at_130(self):
        self.assertTrue(R.in_window(dt.datetime(2026, 11, 3, 13, 30)))
        self.assertFalse(R.in_window(dt.datetime(2026, 11, 3, 13, 29)))


if __name__ == "__main__":
    unittest.main()


class FreshWait(unittest.TestCase):
    def _go(self, shares, now=dt.datetime(2026, 11, 3, 14, 30, 5)):
        """`shares` = successive {key: at} answers; the clock is real, so the
        deadline is kept out of reach (max_wait_min 60)."""
        it = iter(shares)
        last = {}
        def shared_at():
            nonlocal last
            try:
                last = next(it)
            except StopIteration:
                pass
            return last
        slept = []
        with mock.patch.object(R, "_log"):
            ok = R.wait_for_fresh_share(now, shared_at=shared_at, sleep=slept.append,
                                        max_wait_min=60)
        return ok, slept

    def test_fresh_already_no_wait(self):
        ok, slept = self._go([{"rafael": dt.datetime(2026, 11, 3, 14, 34, 32)}])
        self.assertTrue(ok); self.assertEqual(slept, [])

    def test_waits_until_a_share_newer_than_the_slot(self):
        ok, slept = self._go([{"rafael": dt.datetime(2026, 11, 3, 14, 4, 32)},
                              {"rafael": dt.datetime(2026, 11, 3, 14, 4, 32)},
                              {"rafael": dt.datetime(2026, 11, 3, 14, 34, 40)}])
        self.assertTrue(ok); self.assertEqual(slept, [30, 30])

    def test_gives_up_at_the_deadline(self):
        with mock.patch.object(R, "_log"):
            ok = R.wait_for_fresh_share(dt.datetime(2026, 11, 3, 14, 30, 5),
                                        shared_at=lambda: {}, sleep=lambda s: None,
                                        max_wait_min=0)
        self.assertFalse(ok)

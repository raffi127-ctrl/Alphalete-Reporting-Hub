"""borrowed_rows: Cinthya + Annett off Raf's 'Lucy Knocks' row, board only."""
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
       {"Rep": "Anette Climaco", "Total Knocks": "27", "First Knock": "2:05 PM", "Talk To's": "4"},
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
        self.assertEqual([r["Rep"] for r in got], ["Cinthya Reyes Roadtrip", "Anette Climaco"])
        for r in got:                       # trimmed to our own rows' columns
            self.assertEqual(set(r), {"Rep", "Total Knocks", "First Knock"})
        self.assertEqual(got[0]["Total Knocks"], "41")

    def test_yesterdays_row_is_ignored(self):
        self.assertEqual(self._run([_line("rafael", dt.date(2026, 11, 2), RAF)]), [])

    def test_other_keys_ignored_and_no_double(self):
        own = OWN + [{"Rep": "Anette Climaco", "Total Knocks": "5", "First Knock": "2:10 PM"}]
        got = self._run([_line("steve", dt.date(2026, 11, 3), RAF),
                         _line("rafael", dt.date(2026, 11, 3), RAF)], own=own)
        self.assertEqual([r["Rep"] for r in got], ["Cinthya Reyes Roadtrip"])

    def test_no_own_rows_keeps_every_column(self):
        got = self._run([_line("rafael", dt.date(2026, 11, 3), RAF)], own=[])
        self.assertEqual(len(got), 2)
        self.assertIn("Talk To's", got[0])

    def test_icd_relay_is_the_source_when_lucy_knocks_has_no_row(self):
        """Since 11/03 Raf's Mac relays to 'ICD Knocks'; no 'Lucy Knocks' row."""
        from automations.icd_alerts import knocks_post as KP
        icd_row = [""] * (KP.KN_POSTED + 1)
        icd_row[KP.KN_OFFICE] = "rafael"
        icd_row[KP.KN_DAY] = "2026-11-06"
        icd_row[KP.KN_ROWS] = json.dumps([{"raw": 1}])
        icd_row[KP.KN_TRACKER] = "[]"
        icd_row[KP.KN_RECEIVED] = "11/6/2026 14:31:10"

        class _Book:
            def worksheet(self, name):
                assert name == KP.KNOCKS_TAB
                return _WS([icd_row])   # header differs but only [1:] is read

        with mock.patch("automations.owner_knocks_hourly.share._book", lambda: _Book()), \
             mock.patch("automations.owner_knocks_hourly.share._tab", lambda book, create=False: _WS([])), \
             mock.patch("automations.icd_alerts.knocks_map.to_rows", lambda raw, tracker: list(RAF)), \
             mock.patch("automations.icd_alerts.knocks_post.shift_ov_clock", lambda o, raw, tr, now=None: (raw, tr)), \
             mock.patch("automations.icd_alerts.offices.all_offices", lambda: {}), \
             mock.patch("automations.icd_alerts.post._day_key", lambda d: d), \
             mock.patch.object(R.C, "BORROWED_ICD_OFFICES", {"rafael": "rafael"}), \
             mock.patch.object(R, "_log"):
            got = R.borrowed_rows(dt.date(2026, 11, 6), list(OWN))
            at = R._shared_at(dt.date(2026, 11, 6))
        self.assertEqual([r["Rep"] for r in got], ["Cinthya Reyes Roadtrip", "Anette Climaco"])
        self.assertEqual(at, {"rafael": dt.datetime(2026, 11, 6, 14, 31, 10)})

    def test_empty_relay_row_still_counts_as_reported(self):
        from automations.icd_alerts import knocks_post as KP
        icd_row = [""] * (KP.KN_POSTED + 1)
        icd_row[KP.KN_OFFICE] = "raf"; icd_row[KP.KN_DAY] = "2026-11-06"
        icd_row[KP.KN_ROWS] = "[]"; icd_row[KP.KN_TRACKER] = "[]"
        icd_row[KP.KN_RECEIVED] = "11/6/2026 10:10:01"

        class _Book:
            def worksheet(self, name):
                return _WS([icd_row])

        with mock.patch("automations.owner_knocks_hourly.share._book", lambda: _Book()), \
             mock.patch("automations.owner_knocks_hourly.share._tab", lambda book, create=False: _WS([])), \
             mock.patch("automations.icd_alerts.knocks_map.to_rows", lambda raw, tracker: []), \
             mock.patch("automations.icd_alerts.knocks_post.shift_ov_clock", lambda o, raw, tr, now=None: (raw, tr)), \
             mock.patch("automations.icd_alerts.offices.all_offices", lambda: {}), \
             mock.patch("automations.icd_alerts.post._day_key", lambda d: d), \
             mock.patch.object(R.C, "BORROWED_ICD_OFFICES", {"rafael": "raf"}), \
             mock.patch.object(R, "_log"):
            src = R._borrow_sources(dt.date(2026, 11, 6))
            at = R._shared_at(dt.date(2026, 11, 6))
        self.assertEqual(src["rafael"][0], [])
        self.assertEqual(at["rafael"], dt.datetime(2026, 11, 6, 10, 10, 1))

    def test_newer_tab_wins(self):
        from automations.icd_alerts import knocks_post as KP
        icd_row = [""] * (KP.KN_POSTED + 1)
        icd_row[KP.KN_OFFICE] = "rafael"; icd_row[KP.KN_DAY] = "2026-11-06"
        icd_row[KP.KN_ROWS] = "[{}]"; icd_row[KP.KN_TRACKER] = "[]"
        icd_row[KP.KN_RECEIVED] = "11/6/2026 14:01:00"          # older than Lucy's 14:31
        newer_lucy = [_line("rafael", dt.date(2026, 11, 6), RAF, at="2026-11-06T14:31:00")]

        class _Book:
            def worksheet(self, name):
                return _WS([icd_row])

        with mock.patch("automations.owner_knocks_hourly.share._book", lambda: _Book()), \
             mock.patch("automations.owner_knocks_hourly.share._tab", lambda book, create=False: _WS(newer_lucy)), \
             mock.patch("automations.icd_alerts.knocks_map.to_rows", lambda raw, tracker: [{"Rep": "Nobody", "Total Knocks": "1", "First Knock": ""}]), \
             mock.patch("automations.icd_alerts.knocks_post.shift_ov_clock", lambda o, raw, tr, now=None: (raw, tr)), \
             mock.patch("automations.icd_alerts.offices.all_offices", lambda: {}), \
             mock.patch("automations.icd_alerts.post._day_key", lambda d: d), \
             mock.patch.object(R.C, "BORROWED_ICD_OFFICES", {"rafael": "rafael"}), \
             mock.patch.object(R, "_log"):
            src = R._borrow_sources(dt.date(2026, 11, 6))
        self.assertEqual(src["rafael"][2], "Lucy Knocks")
        self.assertEqual(src["rafael"][1], dt.datetime(2026, 11, 6, 14, 31))

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


LOG = []
D = dt.date(2026, 11, 13)


class SurnameFallback(unittest.TestCase):
    """Carlos 2026-11-13: Annett's first name may be spelled differently on
    Raf's Ownerville. A unique surname match still brings her over; two rows
    sharing the surname bring nobody."""

    def _run(self, raf_rows):
        with mock.patch.object(R, "_borrow_sources",
                               lambda today: {"rafael": (raf_rows, None, "ICD Knocks office raf")}), \
             mock.patch.object(R.C, "BORROWED_ROWS", {"rafael": ["Cinthya Reyes", "Anette Climaco"]}), \
             mock.patch.object(R, "_log", lambda m: LOG.append(m)):
            return R.borrowed_rows(D, list(OWN))

    def test_misspelled_first_name_matches_on_unique_surname(self):
        LOG.clear()
        got = self._run([{"Rep": "Cinthya Reyes Roadtrip", "Total Knocks": "3"},
                         {"Rep": "Annett Michell Climaco", "Total Knocks": "9"}])
        self.assertEqual([r["Rep"] for r in got], ["Cinthya Reyes Roadtrip", "Annett Michell Climaco"])
        self.assertTrue(any("via surname 'climaco'" in m for m in LOG), LOG)

    def test_two_rows_with_the_surname_claim_nobody(self):
        LOG.clear()
        got = self._run([{"Rep": "Annett Climaco", "Total Knocks": "9"},
                         {"Rep": "Maria Climaco", "Total Knocks": "2"}])
        self.assertEqual([r["Rep"] for r in got], [])
        self.assertTrue(any("not on rafael's rows today" in m for m in LOG), LOG)

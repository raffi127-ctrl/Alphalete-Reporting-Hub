"""Pure tests -- no AppStream, no Messages, nothing sent."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from automations.recruiting_day_texts import config as C
from automations.recruiting_day_texts import read as RD
from automations.recruiting_day_texts import render as R
from automations.recruiting_day_texts import texts as T

DAY = dt.date(2026, 11, 13)
OFF = C.Office(key="t", appstream_id="1", owner="Rafael Hidalgo", team="Alphalete")
H1 = ['', 'first name', 'last name', 'email', 'phone', 'rating', 'job board',
      '1st interview date/time', 'ad (subject line)', '']


def row(first, last, when):
    return ['1', first, last, 'e', 'p', '0', 'Indeed', when, 'ad', '']


class Parse(unittest.TestCase):
    def test_when(self):
        self.assertEqual(RD.parse_when("11/13/2026 12:15 PM"), (DAY, dt.time(12, 15)))
        self.assertEqual(RD.parse_when("11/13/2026 12:15 AM"), (DAY, dt.time(0, 15)))
        self.assertIsNone(RD.parse_when(""))

    def test_slots_match_timeslot_page(self):
        rows = [row("A", "a", "11/13/2026 8:15 AM"), row("B", "b", "11/13/2026 8:15 AM"),
                row("C", "c", "11/13/2026 9:15 AM")]
        d = RD.Day(day=DAY, owner="x", first=RD.timed(H1, rows, DAY, "t"))
        self.assertEqual(d.slots("first"), [(dt.time(8, 15), 2), (dt.time(9, 15), 1)])

    def test_wrong_day_or_no_time_raises(self):
        with self.assertRaises(RuntimeError):
            RD.timed(H1, [row("A", "a", "11/12/2026 8:15 AM")], DAY, "t")
        with self.assertRaises(RuntimeError):
            RD.timed(H1, [row("A", "a", "")], DAY, "t")

    def test_names_dedupe_and_case(self):
        h = ['', 'first name', 'last name', 'email']
        self.assertEqual(RD.names_of(h, [['1', 'victoria', 'newsom', ''],
                                         ['2', 'Victoria', 'Newsom', '']]),
                         ["Victoria Newsom"])

    def test_missing_column_raises(self):
        with self.assertRaises(RuntimeError):
            RD.names_of(['', 'email'], [['1', 'x']])


class Copy(unittest.TestCase):
    def test_empty_day_sends_nothing(self):
        d = RD.Day(day=DAY, owner="x")
        self.assertIsNone(T.morning(OFF, d))
        self.assertIsNone(T.showed(OFF, d))

    def test_showed(self):
        d = RD.Day(day=DAY, owner="x", ns_scheduled=["A", "B", "C", "D"],
                   ns_showed=["A", "C", "D"])
        msg = T.showed(OFF, d)
        self.assertEqual(msg, "New Starts Update: 3/4 showed — 75% retention")
        with tempfile.TemporaryDirectory() as t:
            self.assertTrue(R.showed_png(d, Path(t) / "s.png").exists())

    def test_morning_counts(self):
        d = RD.Day(day=DAY, owner="x", first=[(dt.time(8), "a")] * 3)
        self.assertEqual(T.morning(OFF, d),
                         "Good Morning Alphalete Team \u2600\ufe0f Here\u2019s today's Schedule:")

    def test_render(self):
        d = RD.Day(day=DAY, owner="Rafael Hidalgo", first=[(dt.time(8, 15), "a")],
                   ns_scheduled=["Arielle Adams"])
        with tempfile.TemporaryDirectory() as t:
            p = R.morning_png(d, Path(t) / "x.png")
            self.assertTrue(p.exists() and p.stat().st_size > 1000)

    def test_fmt_time_no_platform_strftime(self):
        self.assertEqual(R.fmt_time(dt.time(0, 5)), "12:05 AM")
        self.assertEqual(R.fmt_time(dt.time(13, 0)), "1:00 PM")


class NewStartTimes(unittest.TestCase):
    def test_sorted_by_time_unknown_last_and_drawn(self):
        d = RD.Day(day=DAY, owner="Atef Choudhury",
                   ns_scheduled=["Zed Last", "Amy Early", "No Time"],
                   ns_times={"zed last": dt.time(10, 0), "amy early": dt.time(8, 30)})
        self.assertEqual([n for _, n in d.ns_with_times()],
                         ["Amy Early", "Zed Last", "No Time"])
        with tempfile.TemporaryDirectory() as t:
            self.assertTrue(R.morning_png(d, Path(t) / "x.png").exists())

    def test_clock(self):
        self.assertEqual(RD.parse_clock("12:30 PM"), dt.time(12, 30))
        self.assertIsNone(RD.parse_clock(""))

    def test_times_ride_the_hand_off(self):
        from automations.recruiting_day_texts import run as RUN
        d = RD.Day(day=DAY, owner="x", ns_scheduled=["Amy Early"],
                   ns_times={"amy early": dt.time(8, 30)})
        p = RUN.decode(RUN.encode(RD.to_payload(C.OFFICES["raf"], "morning", d)))
        self.assertEqual(RD.from_payload(p)[2].ns_times, {"amy early": dt.time(8, 30)})


class Config(unittest.TestCase):
    def test_new_offices_start_dry(self):
        self.assertEqual(C.Office(key="x", appstream_id="1", owner="y", team="z").mode, "dry")

    def test_company_name_follows_the_icd(self):
        o = C.Office(key="x", appstream_id="1", owner="Jacob Dover", team="Rockstar")
        d = RD.Day(day=DAY, owner="x", first=[(dt.time(8), "a")])
        self.assertTrue(T.morning(o, d).startswith("Good Morning Rockstar Team"))
        with self.assertRaises(TypeError):
            C.Office(key="x", appstream_id="1", owner="y")      # no company name
        self.assertIs(C.office("11280"), C.OFFICES["raf"])


class Clock(unittest.TestCase):
    def setUp(self):
        from zoneinfo import ZoneInfo
        from automations.recruiting_day_texts import run as RUN
        self.RUN, self.Z = RUN, ZoneInfo

    def at(self, h, m, tz="America/Chicago", day=16):
        return dt.datetime(2026, 11, day, h, m, tzinfo=self.Z(tz))

    def test_each_zone_at_its_own_seven(self):
        et = C.Office(key="e", appstream_id="1", owner="a b", team="t", tz="America/New_York")
        pt = C.Office(key="p", appstream_id="1", owner="a b", team="t", tz="America/Los_Angeles")
        self.assertTrue(self.RUN.is_due(et, "morning", self.at(6, 5)))
        self.assertFalse(self.RUN.is_due(pt, "morning", self.at(6, 5)))
        self.assertTrue(self.RUN.is_due(pt, "morning", self.at(9, 5)))
        self.assertFalse(self.RUN.is_due(et, "morning", self.at(7, 0)))   # next zone's slot

    def test_never_sunday(self):
        o = C.Office(key="c", appstream_id="1", owner="a b", team="t")
        self.assertFalse(self.RUN.is_due(o, "morning", self.at(7, 5, day=15)))

    def test_dry_offices_never_dispatched(self):
        self.assertTrue(all(o.mode == "live" for o in self.RUN.due_offices("morning", self.at(7, 5))))

    def test_payload_survives_names_with_quotes(self):
        d = RD.Day(day=DAY, owner="Rafael Hidalgo", first=[(dt.time(8, 15), "Pat O'Brien")],
                   ns_scheduled=["Zoë D'Angelo"], ns_showed=[])
        s = self.RUN.encode(RD.to_payload(C.OFFICES["raf"], "morning", d, {"first": 120.0}))
        self.assertNotIn(" ", s); self.assertNotIn(",", s); self.assertNotIn("'", s)
        o, mode, d2, avg = RD.from_payload(self.RUN.decode(s))
        self.assertEqual((o.key, mode, d2.first, d2.ns_scheduled, avg),
                         ("raf", "morning", d.first, d.ns_scheduled, {"first": 120.0}))


class RedAlert(unittest.TestCase):
    def test_low_only_when_clearly_under_usual(self):
        d = RD.Day(day=DAY, owner="x", first=[(dt.time(8), "a")] * 76,
                   second=[(dt.time(9), "b")] * 29)
        self.assertEqual(RD.low_flags(d, {"first": 120.0, "second": 30.0}), {"first": 120.0})
        self.assertEqual(RD.low_flags(d, {}), {})
        tiny = RD.Day(day=DAY, owner="x", first=[(dt.time(8), "a")])
        self.assertEqual(RD.low_flags(tiny, {"first": 3.0}), {})       # too small to judge

    def test_closed_days_do_not_drag_the_average(self):
        self.assertEqual(RD.average([52, 63, 72, 0]), 62.333333333333336)
        self.assertEqual(RD.average([0, 0]), 0.0)

    def test_alert_compares_mornings_never_full_days(self):
        # 2026-11-15: Raf's Monday read 27 the day before vs a 210 final --
        # the * must only ever weigh a morning against earlier mornings.
        with tempfile.TemporaryDirectory() as t:
            old = RD.MORNINGS
            RD.MORNINGS = Path(t) / "m.json"
            try:
                o = C.OFFICES["raf"]
                today = dt.date.today()
                day = lambda n: RD.Day(day=today - dt.timedelta(days=7 * n), owner="x",
                                       first=[(dt.time(8), "a")] * n * 10)
                self.assertEqual(RD.morning_usual(o, today), {})   # no history: no *
                RD.morning_record(o, day(1))                       # 10
                self.assertEqual(RD.morning_usual(o, today), {})   # 1 morning: still no *
                RD.morning_record(o, day(2))                       # 20
                RD.morning_record(o, day(2))                       # a resend never doubles
                self.assertEqual(RD.morning_usual(o, today), {"first": 15.0})
            finally:
                RD.MORNINGS = old

    def test_red_note_drawn(self):
        d = RD.Day(day=DAY, owner="Rafael Hidalgo", first=[(dt.time(8), "a")] * 10)
        with tempfile.TemporaryDirectory() as t:
            plain = R.morning_png(d, Path(t) / "a.png")
            alert = R.morning_png(d, Path(t) / "b.png", low={"first": 40.0})
            from PIL import Image
            self.assertGreater(Image.open(alert).height, Image.open(plain).height)


class OfficeList(unittest.TestCase):
    def test_one_group_per_icd_and_37_live(self):
        ids = [o.appstream_id for o in C.OFFICES.values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(o.group for o in C.OFFICES.values()))
        self.assertEqual(sum(o.mode == "live" for o in C.OFFICES.values()), 37)


if __name__ == "__main__":
    unittest.main()

"""The Await text's interview times follow the clock for EVERY office that
pushes (Megan 2026-10-28) -- each with its own windows, never another's.
No browser, no AppStream."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.oat_processing import await_template as AT
from automations.oat_processing import await_window as AW


class OnlyTheChosenOffices(unittest.TestCase):
    """Megan 2026-10-28: 11580 + Raf's 23965 and 24065 only."""

    def test_the_list(self):
        self.assertEqual(AT.OFFICES, {"11580", "23965", "24065"})

    def test_rafs_main_office_is_never_opened(self):
        for office in ("11280", "23467", "11901"):
            with mock.patch.object(AT, "_goto_templates") as go, \
                 mock.patch.object(AT, "read_office_schedule") as rs:
                self.assertTrue(AT.ensure_await_template(mock.Mock(), office))
            go.assert_not_called()
            rs.assert_not_called()


class PerOfficeWindows(unittest.TestCase):

    def test_carlos_text_is_unchanged(self):
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 13, 0)),
                         "available TODAY between 1:45pm-3:45pm")
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 7, 0)),
                         "available TODAY between 8:15am-10:45am or "
                         "12:15pm-3:45pm")

    def test_an_office_uses_its_own_windows(self):
        own = [AW._w(9, 0, 11, 0), AW._w(13, 0, 17, 0)]
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 14, 0), own),
                         "available TODAY between 3:00pm-5:00pm")
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 18, 0), own),
                         "available TOMORROW between 9:00am-11:00am or "
                         "1:00pm-5:00pm")

    def test_a_single_window_office(self):
        one = [AW._w(10, 0, 12, 0)]
        self.assertEqual(AW.await_clause(dt.datetime(2026, 10, 28, 11, 20), one),
                         "available TODAY at 12:00pm")

    def test_an_office_whose_schedule_cannot_be_read_is_left_alone(self):
        page = mock.Mock()
        with mock.patch.object(AT, "read_office_schedule",
                               return_value=(None, None)), \
             mock.patch.object(AT, "office_now",
                               return_value=dt.datetime(2026, 10, 28, 9)), \
             mock.patch.object(AT, "_goto_templates") as go:
            with mock.patch.object(AT, "OFFICES", {"99999"}):
                self.assertFalse(AT.ensure_await_template(page, "99999"))
        go.assert_not_called()       # never opened, never edited

    def test_the_regex_still_matches_every_shape_it_writes(self):
        own = [AW._w(9, 0, 11, 0), AW._w(13, 0, 17, 0)]
        for h in range(6, 23):
            for w in (None, own):
                c = AW.await_clause(dt.datetime(2026, 10, 28, h, 10), w)
                self.assertTrue(AT.CLAUSE_RE.search(
                    "Are you %s for a quick ZOOM?" % c), c)


class FromTheOfficesOwnSettings(unittest.TestCase):
    """Megan 2026-10-28: each office has its own schedule in AppStream,
    Settings > Office Level Settings (Raf's 11280: Mon-Fri 8:00 AM - 4:00 PM,
    every 15 minutes)."""

    RAF = {d: [AW.parse_span("8:00 AM - 4:00 PM")]
           for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")}

    def at(self, s):
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")

    def test_every_15_minutes_through_the_last_start(self):
        self.assertEqual(AW.clause_from_schedule(self.at("2026-10-28 13:00"),
                                                 self.RAF, 15),
                         "available TODAY between 1:45pm-3:45pm")

    def test_after_the_last_slot_offers_tomorrow(self):
        self.assertEqual(AW.clause_from_schedule(self.at("2026-10-28 15:20"),
                                                 self.RAF, 15),
                         "available TOMORROW between 8:00am-3:45pm")

    def test_friday_evening_offers_monday_not_saturday(self):
        self.assertEqual(AW.clause_from_schedule(self.at("2026-10-30 15:30"),
                                                 self.RAF, 15),
                         "available MONDAY between 8:00am-3:45pm")

    def test_split_days_keep_both_windows(self):
        sched = {"Wednesday": [AW.parse_span("9:00 AM - 11:00 AM"),
                               AW.parse_span("1:00 PM - 5:00 PM")]}
        self.assertEqual(AW.clause_from_schedule(self.at("2026-10-28 08:00"),
                                                 sched, 30),
                         "available TODAY between 9:00am-10:30am or "
                         "1:00pm-4:30pm")

    def test_monday_wording_still_matches_the_rewrite(self):
        c = AW.clause_from_schedule(self.at("2026-10-30 18:00"), self.RAF, 15)
        self.assertTrue(AT.CLAUSE_RE.search("Are you %s for a quick ZOOM?" % c))

    def test_the_header_clock_is_the_offices(self):
        page = mock.Mock()
        fr = mock.Mock()
        fr.inner_text.return_value = ("Office ID: 11280 Owner: Rafael Hidalgo "
                                      "Time: Oct, 28 02:16 PM - Central Standard")
        page.frames = [fr]
        self.assertEqual(AT.office_now(page).strftime("%m-%d %H:%M"),
                         "10-28 14:16")

    def test_reads_rafs_settings_page(self):
        try:
            from patchright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            self.skipTest(str(e))
        html = ("<p>Calendar Time Increment: <input type=radio name=i> 5 Mins "
                "<input type=radio name=i checked> 15 Mins "
                "<input type=radio name=i> 30 Mins</p>"
                "<table><tr><td>Current Active Interview Slots</td></tr>"
                "<tr><th>Slot</th><th>Sunday</th><th>Monday</th><th>Tuesday</th>"
                "<th>Wednesday</th><th>Thursday</th><th>Friday</th><th>Saturday</th></tr>"
                "<tr><td>1</td><td></td>" + "<td>8:00 AM - 4:00 PM</td>" * 5 +
                "<td></td></tr></table>")
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                pg = b.new_page()
                pg.set_content(html)
                raw = pg.evaluate(AT._SCHED_JS)
                b.close()
        except Exception as e:  # noqa: BLE001
            self.skipTest("no browser: %s" % e)
        self.assertEqual(raw["step"], 15)
        self.assertEqual(raw["slots"]["Monday"], ["8:00 AM - 4:00 PM"])
        self.assertNotIn("Sunday", raw["slots"])


if __name__ == "__main__":
    unittest.main()

"""The Await text's interview times (Carlos + Megan 2026-10-28), for 11580
and Raf's 23965 + 24065 only, each from its own schedule:
3-6 hours out first; else today's remaining; else the next interview day.
Schedules and template texts below are the REAL ones read 10/28.
No AppStream; one test uses a local headless browser."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.oat_processing import await_template as AT
from automations.oat_processing import await_window as AW

P = AW.parse_span
_MORN = ["8:15 AM - 8:30 AM", "8:45 AM - 9:00 AM", "9:15 AM - 9:30 AM",
         "9:45 AM - 10:00 AM", "10:15 AM - 10:30 AM", "10:45 AM - 11:00 AM",
         "12:45 PM - 3:45 PM"]
S24065 = {d: [P(x) for x in _MORN]
          for d in ("Monday", "Tuesday", "Wednesday", "Thursday")}
S24065["Friday"] = [P("12:45 PM - 3:45 PM")]
S23965 = {d: [P("8:15 AM - 3:45 PM")]
          for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")}
T24065 = ("Are you available currentInterviewDay 12:45 pm - 3:45 pm for a "
          "quick ZOOM to go over the position?")
T23965 = ("Hello applicantFirstName, this is Tiffani with Alphalete Marketing. "
          "We’ve reviewed your application and would love to set up a "
          "quick 20-minute Zoom Interview. Are you available?")


def at(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")


class OnlyTheChosenOffices(unittest.TestCase):

    def test_the_list(self):
        self.assertEqual(AT.OFFICES, {"11580", "23965", "24065"})

    def test_others_are_never_opened(self):
        for office in ("11280", "23467", "11901"):
            with mock.patch.object(AT, "_goto_templates") as go, \
                 mock.patch.object(AT, "read_office_schedule") as rs:
                self.assertTrue(AT.ensure_await_template(mock.Mock(), office))
            go.assert_not_called()
            rs.assert_not_called()


class TheSweetSpot(unittest.TestCase):

    def test_three_to_six_hours_out_first(self):
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 09:30"),
                                                 S23965, 15),
                         "available TODAY, Wednesday between 12:30pm-3:30pm")

    def test_none_that_far_today_remaining_anyway(self):
        # Megan: "Today's remaining slots anyway ... under 3 hours, but same-day"
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 13:30"),
                                                 S23965, 15),
                         "available TODAY, Wednesday between 2:15pm-3:30pm")

    def test_nothing_left_today_the_next_day(self):
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 15:20"),
                                                 S24065, 30),
                         "available TOMORROW, Thursday between 8:15am-10:45am "
                         "/ 12:45pm-3:15pm")

    def test_friday_evening_is_monday(self):
        self.assertEqual(AW.clause_from_schedule(at("2026-10-30 16:00"),
                                                 S23965, 15),
                         "available MONDAY between 8:15am-3:30pm")

    def test_single_morning_slots_count(self):
        # 24065's "8:15 AM - 8:30 AM" rows are one 8:15 start each.
        self.assertEqual(AW.starts_from_spans([P("8:15 AM - 8:30 AM")], 30),
                         [8 * 60 + 15])

    def test_24065_friday_is_afternoon_only(self):
        self.assertEqual(AW.clause_from_schedule(at("2026-10-30 07:30"),
                                                 S24065, 30),
                         "available TODAY, Friday between 12:45pm-1:15pm")

    def test_carlos_gets_the_sweet_spot_too(self):
        self.assertEqual(AW.await_clause(at("2026-10-28 09:30")),
                         "available TODAY, Wednesday between 12:45pm-3:15pm")


class TheDayReadsTodayWednesday(unittest.TestCase):
    """Megan 10/28: 'this should say "TODAY, Wednesday"'."""

    def test_labels(self):
        self.assertEqual(AW.day_label(at("2026-10-28 09:00"), 0), "TODAY, Wednesday")
        self.assertEqual(AW.day_label(at("2026-10-28 09:00"), 1), "TOMORROW, Thursday")
        self.assertEqual(AW.day_label(at("2026-10-30 16:00"), 3), "MONDAY")

    def test_24065_fits_its_160_character_box(self):
        worst = 0
        for day in ("2026-10-28", "2026-10-30", "2026-10-31"):
            for h in range(6, 23):
                c = AW.clause_from_schedule(at("%s %02d:10" % (day, h)), S24065, 30)
                worst = max(worst, len(AT.CLAUSE_RE.sub(c, T24065, count=1)))
        self.assertLessEqual(worst, 160)


class MimicsJacobs23607(unittest.TestCase):
    """Megan 10/28: 'we want it to mimic this'."""

    def _page(self, b1, b2):
        vals = {"smsBody": b1, "smsBody2": b2}
        filled = {}

        def field(page, name):
            if vals.get(name) is None:
                return None
            el = mock.Mock()
            el.input_value.return_value = vals[name]
            el.fill.side_effect = lambda v, n=name: filled.__setitem__(n, v)
            return el
        return field, filled

    def test_both_boxes_set_to_the_standard(self):
        field, filled = self._page(T23965, "")
        with mock.patch.object(AT, "_named_field", side_effect=field), \
             mock.patch.object(AT, "_click_text", return_value=True):
            self.assertTrue(AT._set_standard(mock.Mock(), "23965",
                                             "available TODAY, Wednesday between "
                                             "12:30pm-3:30pm", True))
        self.assertEqual(filled["smsBody"], AT.STANDARD_BODY1)
        self.assertEqual(filled["smsBody2"],
                         "Are you available TODAY, Wednesday between "
                         "12:30pm-3:30pm for a quick ZOOM to go over the "
                         "position?")

    def test_already_current_saves_nothing(self):
        want = "available TODAY, Wednesday between 12:45pm-3:15pm"
        field, filled = self._page(AT.STANDARD_BODY1, AT.STANDARD_BODY2 % want)
        with mock.patch.object(AT, "_named_field", side_effect=field), \
             mock.patch.object(AT, "_click_text") as click:
            self.assertTrue(AT._set_standard(mock.Mock(), "24065", want, True))
        click.assert_not_called()
        self.assertEqual(filled, {})

    def test_every_version_fits_160(self):
        for sched, step in ((S24065, 30), (S23965, 15)):
            for day in ("2026-10-28", "2026-10-30", "2026-10-31"):
                for h in range(6, 23):
                    c = AW.clause_from_schedule(at("%s %02d:10" % (day, h)),
                                                sched, step)
                    self.assertLessEqual(len(AT.STANDARD_BODY2 % c), 160, c)

    def test_jacobs_own_box_two_still_matches(self):
        self.assertIsNotNone(AT.CLAUSE_RE.search(
            "Are you available TODAY between 8:15am -10:45am / 12:45pm-3:45 pm "
            "for a quick ZOOM to go over the position?"))


class TheRealTemplates(unittest.TestCase):

    def test_24065_keeps_its_sentence_day_and_times_swapped(self):
        c = AW.clause_from_schedule(at("2026-10-28 09:30"), S24065, 30)
        self.assertEqual(AT.CLAUSE_RE.sub(c, T24065, count=1),
                         "Are you available TODAY, Wednesday between "
                         "12:45pm-3:15pm for a quick ZOOM to go over the "
                         "position?")

    def test_23965_gets_times_on_its_question(self):
        self.assertIsNone(AT.CLAUSE_RE.search(T23965))
        c = AW.clause_from_schedule(at("2026-10-28 09:30"), S23965, 15)
        new = AT.BARE_ASK_RE.sub("Are you %s?" % c, T23965, count=1)
        self.assertTrue(new.endswith("Zoom Interview. Are you available "
                                     "TODAY, Wednesday between 12:30pm-3:30pm?"))
        # ...and from then on the normal update finds it.
        self.assertIsNotNone(AT.CLAUSE_RE.search(new))

    def test_every_shape_we_write_is_swallowed_whole(self):
        for sched, step in ((S24065, 30), (S23965, 15)):
            for day in ("2026-10-28", "2026-10-30", "2026-10-31"):
                for h in range(6, 23):
                    c = AW.clause_from_schedule(at("%s %02d:10" % (day, h)),
                                                sched, step)
                    m = AT.CLAUSE_RE.search("Are you %s for a ZOOM?" % c)
                    self.assertIsNotNone(m, c)
                    self.assertEqual(m.group(0), c)

    def test_an_unreadable_schedule_edits_nothing(self):
        with mock.patch.object(AT, "read_office_schedule",
                               return_value=(None, None)), \
             mock.patch.object(AT, "office_now",
                               return_value=at("2026-10-28 09:00")), \
             mock.patch.object(AT, "_goto_templates") as go:
            self.assertFalse(AT.ensure_await_template(mock.Mock(), "23965"))
        go.assert_not_called()

    def test_the_header_clock_is_the_offices(self):
        page = mock.Mock()
        fr = mock.Mock()
        fr.inner_text.return_value = "Time: Oct, 28 02:40 PM - Central Standard"
        page.frames = [fr]
        self.assertEqual(AT.office_now(page).strftime("%m-%d %H:%M"),
                         "10-28 14:40")


class TheGridReader(unittest.TestCase):
    """The settings page draws its slots in ExtJS grids, one per interview tab
    (seen live 10/28). Only the 1st Interview tab counts."""

    HTML = (
        "<div class=x-tab-panel><ul><li><span class=x-tab-strip-text>1st Interview</span></li>"
        "<li><span class=x-tab-strip-text>2nd Interview</span></li></ul>"
        "<div class=x-tab-panel-body>"
        "<div class=x-panel><input type=radio value=15> <input type=radio value=30 checked>"
        "<div class=x-grid3><div class=x-grid3-header><table><tr>"
        "<td class='x-grid3-hd'>Slot</td><td class='x-grid3-hd'>Sunday</td>"
        "<td class='x-grid3-hd'>Monday</td><td class='x-grid3-hd'>Friday</td></tr></table></div>"
        "<div class=x-grid3-body><div class=x-grid3-row><table><tr>"
        "<td class=x-grid3-cell>1</td><td class=x-grid3-cell></td>"
        "<td class=x-grid3-cell>8:15 AM - 8:30 AM</td><td class=x-grid3-cell>12:45 PM - 3:45 PM</td>"
        "</tr></table></div></div></div></div>"
        "<div class=x-panel><input type=radio value=15 checked>"
        "<div class=x-grid3><div class=x-grid3-header><table><tr>"
        "<td class='x-grid3-hd'>Slot</td><td class='x-grid3-hd'>Monday</td></tr></table></div>"
        "<div class=x-grid3-body><div class=x-grid3-row><table><tr>"
        "<td class=x-grid3-cell>1</td><td class=x-grid3-cell>9:00 AM - 9:30 AM</td>"
        "</tr></table></div></div></div></div>"
        "</div></div>")

    def test_reads_the_first_round_tab_only(self):
        try:
            from patchright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                pg = b.new_page()
                pg.set_content(self.HTML)
                raw = pg.evaluate(AT._SCHED_JS)
                b.close()
        except Exception as e:  # noqa: BLE001
            self.skipTest("no browser: %s" % e)
        self.assertEqual(raw["step"], 30)
        self.assertEqual(raw["slots"], {"Monday": ["8:15 AM - 8:30 AM"],
                                        "Friday": ["12:45 PM - 3:45 PM"]})


if __name__ == "__main__":
    unittest.main()

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
        self.assertEqual(AT.OFFICES, {"11580", "23965", "24065", "11280",
                                      "23467", "11901"})

    def test_others_are_never_opened(self):
        for office in ("23607", "12345"):
            with mock.patch.object(AT, "_goto_templates") as go, \
                 mock.patch.object(AT, "read_office_schedule") as rs:
                self.assertTrue(AT.ensure_await_template(mock.Mock(), office))
            go.assert_not_called()
            rs.assert_not_called()


class AlwaysTheAppStreamSchedule(unittest.TestCase):
    """Megan 10/28: "we should always use the schedule set in app stream"."""

    def test_carlos_reads_his_appstream_schedule_too(self):
        with mock.patch.object(AT, "read_office_schedule",
                               return_value=({}, 30)) as rs:
            self.assertFalse(AT.ensure_await_template(mock.Mock(), "11580"))
        rs.assert_called_once()


class NearestSlotFirst(unittest.TestCase):
    """Megan 10/28: no 3-6 hour step -- every slot more than 30 min out."""

    def test_the_nearer_morning_slots_are_offered(self):
        # Carlos 10/28: at 9:00 it must offer 9:45-10:45 too.
        slots, step = AT.parse_ai_hours(_hours_page(CARLOS))
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 09:00"), slots, step),
                         "available TODAY, currentInterviewDay, from "
                         "9:45am-10:45am or 12:15pm-3:45pm")

    def test_rest_of_today_from_30_min_out(self):
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 09:30"),
                                                 S23965, 15),
                         "available TODAY, currentInterviewDay, from 10:15am-3:30pm")

    def test_none_that_far_today_remaining_anyway(self):
        # Megan: "Today's remaining slots anyway ... under 3 hours, but same-day"
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 13:30"),
                                                 S23965, 15),
                         "available TODAY, currentInterviewDay, from 2:15pm-3:30pm")

    def test_nothing_left_today_the_next_day(self):
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 15:20"),
                                                 S24065, 30),
                         "available TOMORROW, nextInterviewDay, from 8:15am-10:45am "
                         "or 12:45pm-3:15pm")

    def test_friday_evening_is_monday(self):
        self.assertEqual(AW.clause_from_schedule(at("2026-10-30 16:00"),
                                                 S23965, 15),
                         "available nextInterviewDay from 8:15am-3:30pm")

    def test_single_morning_slots_count(self):
        # 24065's "8:15 AM - 8:30 AM" rows are one 8:15 start each.
        self.assertEqual(AW.starts_from_spans([P("8:15 AM - 8:30 AM")], 30),
                         [8 * 60 + 15])

    def test_24065_friday_is_afternoon_only(self):
        self.assertEqual(AW.clause_from_schedule(at("2026-10-30 07:30"),
                                                 S24065, 30),
                         "available TODAY, currentInterviewDay, from 12:45pm-3:15pm")

    def test_a_slot_30_min_away_or_closer_is_skipped(self):
        slots, step = AT.parse_ai_hours(_hours_page(CARLOS))
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 09:15"), slots, step),
                         "available TODAY, currentInterviewDay, from "
                         "10:15am-10:45am or 12:15pm-3:45pm")


class TheDayReadsTodayWednesday(unittest.TestCase):
    """Megan 10/28: 'this should say "TODAY, currentInterviewDay"'."""

    def test_labels(self):
        self.assertEqual(AW.day_label(at("2026-10-28 09:00"), 0), "TODAY, currentInterviewDay")
        self.assertEqual(AW.day_label(at("2026-10-28 09:00"), 1), "TOMORROW, nextInterviewDay")
        self.assertEqual(AW.day_label(at("2026-10-30 16:00"), 3), "nextInterviewDay")

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
                                             "available TODAY, currentInterviewDay, from "
                                             "12:30pm-3:30pm", True))
        self.assertEqual(filled["smsBody"], AT.STANDARD_BODY1)
        self.assertEqual(filled["smsBody2"],
                         "Are you available TODAY, currentInterviewDay, from "
                         "12:30pm-3:30pm for a quick Zoom to go over the "
                         "position?")

    def test_already_current_saves_nothing(self):
        want = "available TODAY, currentInterviewDay, from 12:45pm-3:15pm"
        b1, b2 = AT.TEXTS["24065"]
        field, filled = self._page(b1, b2 % want)
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
                    for office, (b1, b2) in AT.TEXTS.items():
                        self.assertLessEqual(len(b2 % c), 160, (office, c))

    def test_jacobs_own_box_two_still_matches(self):
        self.assertIsNotNone(AT.CLAUSE_RE.search(
            "Are you available TODAY between 8:15am -10:45am or 12:45pm-3:45 pm "
            "for a quick Zoom call to go over the position?"))


class TheApprovedTexts(unittest.TestCase):
    """Megan 10/28: "approved, build it for all accounts"."""

    def test_box_one_fits_and_is_plain(self):
        for office, (b1, b2) in AT.TEXTS.items():
            self.assertLessEqual(len(b1), 300, office)
            self.assertTrue(all(ord(ch) < 128 for ch in b1 + b2), office)
            self.assertIn("%s", b2)

    def test_no_two_accounts_send_the_same_text(self):
        seen = [b1 + b2 for b1, b2 in AT.TEXTS.values()]
        self.assertEqual(len(seen), len(set(seen)))

    def test_11280_reads_as_approved(self):
        b1, b2 = AT.TEXTS["11280"]
        self.assertEqual(b2 % "available TOMORROW, nextInterviewDay, from "
                         "8:15am-10:15am or 12:15pm-3:15pm",
                         "Would you be available TOMORROW, nextInterviewDay, "
                         "from 8:15am-10:15am or 12:15pm-3:15pm for a quick "
                         "Zoom to go over the role?")


class TheRealTemplates(unittest.TestCase):

    def test_24065_keeps_its_sentence_day_and_times_swapped(self):
        c = AW.clause_from_schedule(at("2026-10-28 09:30"), S24065, 30)
        self.assertEqual(AT.CLAUSE_RE.sub(c, T24065, count=1),
                         "Are you available TODAY, currentInterviewDay, from "
                         "10:15am-10:45am or 12:45pm-3:15pm for a quick ZOOM "
                         "to go over the position?")

    def test_23965_gets_times_on_its_question(self):
        self.assertIsNone(AT.CLAUSE_RE.search(T23965))
        c = AW.clause_from_schedule(at("2026-10-28 09:30"), S23965, 15)
        new = AT.BARE_ASK_RE.sub("Are you %s?" % c, T23965, count=1)
        self.assertTrue(new.endswith("Zoom Interview. Are you available "
                                     "TODAY, currentInterviewDay, from 10:15am-3:30pm?"))
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


def _hours_page(days):
    """The AI Settings > Hours text, built the way the live page reads
    (10/28): a letter per weekday, then 'HH:MM AM - HH:MM AM' + capacity."""
    out = ["Interview Schedule", "Save Settings", "Current Active Interview Time",
           "Video Tutorial"]
    for letter, blocks in days:
        out.append(letter)
        for a, b in blocks:
            t = dt.datetime(2026, 1, 1, a // 60, a % 60)
            while t.hour * 60 + t.minute <= b:
                e = t + dt.timedelta(minutes=30)
                out += ["%s - %s" % (t.strftime("%I:%M %p"), e.strftime("%I:%M %p")), "7"]
                t = e
    out.append("Holiday Settings")
    return "\n".join(out)


CARLOS = [(L, [(495, 645), (735, 945)]) for L in "MTWTF"] + [("S", []), ("S", [])]
ATEF = [(L, [(705, 885)]) for L in "MTWTF"] + [("S", []), ("S", [])]


class ReadsAISettingsHours(unittest.TestCase):
    """Megan 10/28: "for the schedule we need to look at AI>ai settings>hours"."""

    def test_carlos_lunch_break_comes_through(self):
        slots, step = AT.parse_ai_hours(_hours_page(CARLOS))
        self.assertEqual(step, 30)
        self.assertEqual(sorted(slots), sorted(["Monday", "Tuesday", "Wednesday",
                                                "Thursday", "Friday"]))
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 19:15"), slots, step),
                         "available TOMORROW, nextInterviewDay, from "
                         "8:15am-10:45am or 12:15pm-3:45pm")

    def test_atef_midday_only(self):
        slots, step = AT.parse_ai_hours(_hours_page(ATEF))
        self.assertEqual(AW.clause_from_schedule(at("2026-10-28 08:00"), slots, step),
                         "available TODAY, currentInterviewDay, from 11:45am-2:45pm")

    def test_two_T_letters_are_tuesday_then_thursday(self):
        days = [("M", []), ("T", [(495, 495)]), ("W", []), ("T", [(600, 600)]),
                ("F", []), ("S", []), ("S", [])]
        slots, _ = AT.parse_ai_hours(_hours_page(days))
        self.assertEqual(slots, {"Tuesday": [(495, 525)], "Thursday": [(600, 630)]})

    def test_no_list_no_schedule(self):
        self.assertEqual(AT.parse_ai_hours("Hours\nSave Schedule"), ({}, None))


class StopsThirtyBeforeTheLastSlot(unittest.TestCase):
    """Carlos 10/28: stop pushing before the last 1st-interview slot;
    Megan: "do 30 min"."""

    def _saved(self, slots, step=30):
        import json
        import tempfile
        path = tempfile.mktemp(suffix=".json")
        json.dump({"slots": slots, "step": step}, open(path, "w"))
        return mock.patch.object(AT, "_sched_path", return_value=path)

    def test_carlos_stops_at_3_15(self):
        slots, step = AT.parse_ai_hours(_hours_page(CARLOS))
        with self._saved(slots, step):
            self.assertEqual(AT.stop_at_today("11580", at("2026-10-29 09:00")).strftime("%H:%M"),
                             "15:15")
            self.assertFalse(AT.past_stop("11580", at("2026-10-29 15:14")))
            self.assertTrue(AT.past_stop("11580", at("2026-10-29 15:15")))

    def test_atef_stops_at_2_15(self):
        slots, step = AT.parse_ai_hours(_hours_page(ATEF))
        with self._saved(slots, step):
            self.assertTrue(AT.past_stop("23467", at("2026-10-29 14:15")))
            self.assertFalse(AT.past_stop("23467", at("2026-10-29 14:10")))

    def test_no_saved_schedule_never_stops(self):
        with mock.patch.object(AT, "_sched_path", return_value="/nonexistent/x.json"):
            self.assertFalse(AT.past_stop("11580", at("2026-10-29 21:00")))

    def test_a_day_with_no_slots_never_stops(self):
        with self._saved({"Monday": [(495, 525)]}):
            self.assertFalse(AT.past_stop("11580", at("2026-10-29 21:00")))  # Thursday


class StopUsesTheOfficeClock(unittest.TestCase):
    """10/29: Atef 23467 is on Mountain time, pushed from Lucy 2 on Central."""

    def test_atef_mountain_from_a_central_machine(self):
        import json
        import tempfile
        slots, step = AT.parse_ai_hours(_hours_page(ATEF))
        path = tempfile.mktemp(suffix=".json")
        json.dump({"slots": slots, "step": step, "shift_min": -60}, open(path, "w"))
        with mock.patch.object(AT, "_sched_path", return_value=path):
            # 2:15 Mountain = 3:15 Central on Lucy 2's clock
            self.assertEqual(AT.stop_at_today("23467", at("2026-10-29 10:00")).strftime("%H:%M"),
                             "15:15")
            self.assertFalse(AT.past_stop("23467", at("2026-10-29 15:10")))
            self.assertTrue(AT.past_stop("23467", at("2026-10-29 15:15")))


class EveryOfficeLikeCarlos(unittest.TestCase):
    """Megan 10/29: "we should run them all like carlos has his set up" --
    the next open slot, even minutes away, on every account."""

    def test_all_six_offer_the_next_slot(self):
        for office in ("11580", "23965", "24065", "11280", "23467", "11901"):
            self.assertEqual(AW.lead_for(office), 0, office)

    def test_a_slot_five_minutes_out_is_offered(self):
        slots, step = AT.parse_ai_hours(_hours_page(CARLOS))
        self.assertEqual(AW.clause_from_schedule(at("2026-10-29 12:10"), slots, step,
                                                 office_id="11280"),
                         "available TODAY, currentInterviewDay, from 12:15pm-3:45pm")


class TheDayEndsWithTomorrowMorningsText(unittest.TestCase):
    """Megan 10/29: "at 7am today applicants were still told tomorrow's
    interview times" -- the evening's "TOMORROW, nextInterviewDay" reads as
    the day after by the 7am send."""

    def test_wednesday_evening_writes_thursday_as_today(self):
        when = AT._next_morning(at("2026-10-28 16:00"), S24065)
        self.assertEqual(when, at("2026-10-29 05:00"))
        self.assertEqual(AW.clause_from_schedule(when, S24065, 30),
                         "available TODAY, currentInterviewDay, from "
                         "8:15am-10:45am or 12:45pm-3:15pm")

    def test_friday_evening_skips_to_monday(self):
        self.assertEqual(AT._next_morning(at("2026-10-30 16:00"), S24065),
                         at("2026-11-02 05:00"))

    def test_last_push_of_day(self):
        with mock.patch.object(AT, "stop_at_today", return_value=at("2026-10-29 15:15")):
            self.assertTrue(AT.last_push_of_day("11280", 15, at("2026-10-29 15:05")))
            self.assertFalse(AT.last_push_of_day("11280", 15, at("2026-10-29 14:50")))

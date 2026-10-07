"""Lucy's hourly call-outs: gap + no fresh credit check, once an hour, never
blank (Carlos / Megan, 2026-09-26)."""
import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import gap_callouts as G

NOW = dt.datetime(2026, 9, 26, 15, 0)
ROWS = [{"Rep": "Nick Smith", "Last Knock": "2:15 PM"},      # 45 min
        {"Rep": "Christian Doe", "Last Knock": "2:20 PM"},   # 40 min
        {"Rep": "Jose Ruiz", "Last Knock": "2:40 PM"},       # 20 min -- under Carlos's 30
        {"Rep": "Ana Pitching", "Last Knock": "2:00 PM"}]    # 60 min but a fresh credit check


class PickTest(unittest.TestCase):
    def test_gap_without_a_fresh_credit_check(self):
        out = G.pick(ROWS, {"NICK SMITH": 2, "ANA PITCHING": 3}, {"NICK SMITH": 2, "ANA PITCHING": 2}, NOW)
        self.assertEqual([c["name"] for c in out], ["Nick Smith", "Christian Doe"])
        self.assertEqual(out[0]["mins"], 45)

    def test_under_thirty_is_left_alone(self):
        out = G.pick(ROWS[2:3], {}, {}, NOW)
        self.assertEqual(out, [])

    def test_a_fresh_credit_check_exempts(self):
        out = G.pick([ROWS[3]], {"ANA PITCHING": 1}, {}, NOW)
        self.assertEqual(out, [])


class ActivityTest(unittest.TestCase):
    def test_att_counts_credit_checks_and_sales(self):
        a = G.activity({"NICK SMITH": 2}, {"NICK SMITH": {"Int": 1, "Int Up": 0, "DTV": 0, "NL": 1}}, "att")
        self.assertEqual(a["nick smith"], 4)

    def test_box_counts_contracts(self):
        a = G.activity({}, {"Ana B": {"Sales": 2, "Volume": 27000, "Big": 1, "Huge": 0}}, "b2b_box")
        self.assertEqual(a["ana b"], 2)


class LineTest(unittest.TestCase):
    def test_names_and_rounded_minutes(self):
        s = G.line("carlos", [{"name": "Nick Smith", "mins": 45}, {"name": "CHRISTIAN DOE", "mins": 43}], NOW)
        self.assertTrue("Nick and Christian" in s or "Nick y Christian" in s, s)
        self.assertIn("40+", s)

    def test_single_name(self):
        s = G.line("carlos", [{"name": "Nick Smith", "mins": 32}], NOW)
        self.assertIn("Nick", s); self.assertNotIn("Nick and", s); self.assertNotIn("and Nick", s); self.assertIn("30+", s)

    def test_a_crowd_is_a_bulleted_list_with_every_name(self):
        c = [{"name": "Breana A", "mins": 47}, {"name": "Gary B", "mins": 31}, {"name": "Kandice C", "mins": 25},
             {"name": "Jaslene D", "mins": 22}, {"name": "Tara E", "mins": 20}]
        s = G.line("carlos", c, NOW)
        self.assertNotIn("more", s)
        self.assertTrue("5 of y'all" in s or "5 de ustedes" in s, s)
        for n in ("• Breana — 47 min", "• Gary — 31 min", "• Kandice — 25 min", "• Jaslene — 22 min", "• Tara — 20 min"):
            self.assertIn(n, s)
        self.assertTrue(s.index("Breana") < s.index("Tara"))

    def test_nobody_is_no_message(self):
        self.assertEqual(G.line("carlos", [], NOW), "")

    def test_same_hour_repeats_next_hour_differs(self):
        c = [{"name": "Nick Smith", "mins": 45}]
        a = G.line("carlos", c, NOW); b = G.line("carlos", c, NOW.replace(minute=30))
        self.assertEqual(a, b)
        seen = {G.line("carlos", c, NOW.replace(hour=h)) for h in range(13, 21)}
        self.assertGreater(len(seen), 1)


class SpanishTest(unittest.TestCase):
    """Megan 2026-10-06: English lines with a few Spanish phrases, never a
    whole Spanish sentence. Names always join with "and"."""

    PHRASES = ("¡Vamos!", "¡ándale!", "cafecito", "dinero", "¡a trabajar!", "eso es trabajo",
               "¡Así se hace!", "recepcionista", "¿eh?", "Ojo")

    def test_no_line_is_spanish_only(self):
        for pool in (G.LINES, G.B2B_LINES, G.PACE_LINES, G.B2B_PACE_LINES,
                     G.RECEIPT_LINES, G.B2B_RECEIPT_LINES):
            for t in pool:
                self.assertFalse(G._is_spanish(t), t)
                self.assertNotIn("{unit_es}", t)
                self.assertNotIn(" sin ", t)

    def test_every_pool_still_sprinkles_spanish(self):
        for pool in (G.LINES, G.B2B_LINES, G.PACE_LINES, G.B2B_PACE_LINES,
                     G.RECEIPT_LINES, G.B2B_RECEIPT_LINES):
            self.assertTrue(any(any(ph in t for ph in self.PHRASES) for t in pool))

    def test_names_join_with_and_everywhere(self):
        for h in range(24):
            s = G.line("x", [{"name": "Nick S", "mins": 30}, {"name": "Jose R", "mins": 25}], NOW.replace(hour=h))
            self.assertIn("Nick and Jose", s)
            self.assertNotIn(" y ", s)


class DueTest(unittest.TestCase):
    def test_first_of_day_is_due(self):
        self.assertTrue(G.due(None, NOW)); self.assertTrue(G.due({"day": "2026-09-25", "last_at": "2026-09-25T20:00:00"}, NOW))

    def test_within_the_half_hour_is_not(self):
        self.assertFalse(G.due({"day": "2026-09-26", "last_at": "2026-09-26T14:40:00"}, NOW))
        self.assertTrue(G.due({"day": "2026-09-26", "last_at": "2026-09-26T14:29:00"}, NOW))


if __name__ == "__main__":
    unittest.main()


class GuestCalloutTest(unittest.TestCase):
    def setUp(self):
        import pathlib, tempfile
        from unittest import mock
        self.p = mock.patch.object(G, "STATE_PATH", pathlib.Path(tempfile.mkdtemp()) / "s.json"); self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_from_a_gap_list_with_the_hosts_credit_checks(self):
        gaps = [{"name": "Nick Smith", "minutesSinceLastKnock": 45},
                {"name": "Ana Pitching", "minutesSinceLastKnock": 50},
                {"name": "Jose Ruiz", "minutesSinceLastKnock": 20}]
        first = G.guest_callout("rafael_hidalgo", "Carlos Hidalgo", gaps, {"NICK SMITH": 1, "ANA PITCHING": 1}, NOW)
        self.assertIn("Nick", first); self.assertIn("Ana", first)      # first hour: no previous -> both idle
        again = G.guest_callout("rafael_hidalgo", "Carlos Hidalgo", gaps, {"NICK SMITH": 1, "ANA PITCHING": 2}, NOW.replace(minute=20))
        self.assertEqual(again, "")                                     # within the half hour: quiet
        later = G.guest_callout("rafael_hidalgo", "Carlos Hidalgo", gaps, {"NICK SMITH": 1, "ANA PITCHING": 2}, NOW + dt.timedelta(minutes=30))
        self.assertIn("Nick", later); self.assertNotIn("Ana", later)   # Ana ran a credit check since


class PaceTest(unittest.TestCase):
    ROWS = [{"Rep": "Ana Fast", "Total Knocks": "62", "First Knock": "12:00 PM", "Last Knock": "2:00 PM"},   # 31/hr
            {"Rep": "Bo Slow", "Total Knocks": "20", "First Knock": "12:00 PM", "Last Knock": "2:00 PM"},    # 10/hr
            {"Rep": "Cy Short", "Total Knocks": "9", "First Knock": "2:40 PM", "Last Knock": "2:55 PM"}]     # 36/hr but 15 min

    def test_25_an_hour_over_two_hours(self):
        out = G.pace(self.ROWS, NOW)
        self.assertEqual([(r["name"], r["avg"]) for r in out], [("Ana Fast", 31)])

    def test_one_hour_of_data_is_not_enough(self):
        rows = [{"Rep": "Ana Fast", "Total Knocks": "40", "First Knock": "1:30 PM", "Last Knock": "2:45 PM"}]  # 32/hr, 75 min
        self.assertEqual(G.pace(rows, NOW), [])

    def test_box_is_actual_talk_tos_at_ten(self):
        rows = [{"Rep": "Bo Box", "Total Knocks": "40", "Corp - No Opp": "8", "Inaccessible": "4", "Inaccurate Lead": "2",
                 "First Knock": "12:00 PM", "Last Knock": "2:00 PM"}]     # 26 actual TT / 2h = 13/hr
        self.assertEqual(G.pace(rows, NOW, "b2b_box"), [{"name": "Bo Box", "avg": 13}])
        self.assertEqual(G.pace(rows, NOW, "att"), [])                    # 20 doors/hr is under 25
        s = G.pace_line("ryan", G.pace(rows, NOW, "b2b_box"), NOW, "b2b_box")
        self.assertTrue("talk-to's" in s or "conversaciones" in s, s)

    def test_praised_once_a_day(self):
        import pathlib, tempfile
        from unittest import mock
        with mock.patch.object(G, "STATE_PATH", pathlib.Path(tempfile.mkdtemp()) / "s.json"):
            first = G.pace_callout("kash", self.ROWS, NOW)
            self.assertIn("Ana", first); self.assertIn("31", first)
            self.assertEqual(G.pace_callout("kash", self.ROWS, NOW.replace(minute=30)), "")   # judged once a day
            self.assertNotEqual(G.pace_callout("kash", self.ROWS, NOW + dt.timedelta(days=1)), "")

    def test_after_the_bell(self):
        from automations.icd_alerts import offices as O
        o = O.AlertOffice(key="x", owner="x", label="x", channels=(), timezone="America/Chicago",
                          day_start="13:30", day_end="20:30", sat_start="10:45", sat_end="17:00", saturday=True)
        self.assertFalse(G.after_the_bell(o, dt.datetime(2026, 9, 25, 20, 0)))   # Fri, still knocking
        self.assertTrue(G.after_the_bell(o, dt.datetime(2026, 9, 25, 20, 45)))   # Fri, 15 past the bell
        self.assertFalse(G.after_the_bell(o, dt.datetime(2026, 9, 25, 23, 0)))   # too long after
        self.assertFalse(G.after_the_bell(o, dt.datetime(2026, 9, 27, 18, 0)))   # Sunday


class WhoIsCalledOut(unittest.TestCase):
    """Who the call-outs reach, and who they must NOT.

    Both gates in run() are `campaign in CALLOUT_CAMPAIGNS or key in
    CALLOUT_EXTRA_OFFICES`, so an office on a non-D2D campaign is on ONLY while
    its key sits in the opt-in set. That makes the set the whole switch, and it
    is the reason stopping an office needs nothing in the relay or the sheet.
    """

    def test_roshan_is_off_by_request(self):
        # Raf 2026-09-26: "Roshan wants her call outs from Lucy stopped."
        self.assertNotIn("roshan", G.CALLOUT_EXTRA_OFFICES)

    def test_roshan_is_not_let_back_in_by_her_campaign(self):
        # The opt-out only holds while b2b_box stays OUT of the campaign set.
        # If Box is ever switched on org-wide, she comes back silently — which
        # is exactly the kind of quiet re-enable this test exists to catch.
        self.assertNotIn("b2b_box", G.CALLOUT_CAMPAIGNS)

    def test_ryan_who_also_asked_is_untouched(self):
        self.assertIn("ryan", G.CALLOUT_EXTRA_OFFICES)

    def test_the_d2d_campaigns_still_get_them(self):
        self.assertEqual(G.CALLOUT_CAMPAIGNS, {"att", "nds"})


class BoxOfficesGetB2BTalk(unittest.TestCase):
    """Ryan 2026-09-30: Box reps walk into businesses, not neighborhoods."""

    C = [{"name": "Emanuel A", "mins": 35}, {"name": "Pedro B", "mins": 35}]

    def test_box_lines_come_from_the_b2b_pool(self):
        for h in range(9, 21):
            s = G.line("ryan", self.C, NOW.replace(hour=h), "b2b_box")
            self.assertNotIn("neighborhood", s)
            self.assertNotIn("doors", s)
            self.assertIn("Emanuel", s)

    def test_d2d_keeps_the_door_lines(self):
        self.assertIs(G.lines_for("att"), G.LINES)
        self.assertIs(G.lines_for(None), G.LINES)
        self.assertIs(G.lines_for("b2b_box"), G.B2B_LINES)

    def test_every_b2b_line_formats_and_spanish_joins_with_y(self):
        for t in G.B2B_LINES:
            s = t.format(names="Ana y Jose" if G._is_spanish(t) else "Ana and Jose", m=30)
            self.assertIn("30+", s)
        self.assertFalse(any(G._is_spanish(t) for t in G.B2B_LINES))

    def test_run_passes_the_campaign(self):
        import inspect
        self.assertIn('line(key, callouts, now, getattr(office, "campaign", None))', inspect.getsource(G.run))


class TheDayIsJudgedOnce(unittest.TestCase):
    """The state file must survive a full run(), both markers intact.

    pace_callout() persists `pace:<office>` mid-run off a fresh disk read,
    while run() holds a snapshot taken before that. Saving the snapshot at the
    end erased the marker, so the next tick judged the day again -- every 60
    seconds for the whole 120-minute after_the_bell window (Cyrus's channel,
    five identical posts at 5:43 PM, 2026-09-26).
    """

    def setUp(self):
        import pathlib, tempfile
        from unittest import mock
        self.p = mock.patch.object(
            G, "STATE_PATH", pathlib.Path(tempfile.mkdtemp()) / "s.json")
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_a_pace_marker_survives_a_snapshot_save(self):
        snapshot = G._state()                 # what run() holds
        snapshot["cyrus"] = {"day": "2026-09-26", "last_at": "2026-09-26T17:40:00"}
        # pace_callout persists its own marker off a FRESH read, mid-run:
        fresh = G._state()
        fresh["pace:cyrus"] = {"day": "2026-09-26"}
        G._save(fresh)
        # ...and then run()'s tail save must not undo it.
        merged = G._state()
        merged.update(snapshot)
        G._save(merged)
        after = G._state()
        self.assertIn("pace:cyrus", after)     # the bug: this key vanished
        self.assertIn("cyrus", after)          # and this one must still land

    def test_pace_callout_says_it_once_then_stays_quiet(self):
        rows = [{"Rep": "Logan", "Last Knock": "4:00 PM"}]
        now = dt.datetime(2026, 9, 26, 17, 43)
        first = G.pace_callout("cyrus", rows, now)
        self.assertEqual(G.pace_callout("cyrus", rows, now), "")
        self.assertEqual(G.pace_callout("cyrus", rows, now + dt.timedelta(minutes=1)), "")
        self.assertNotEqual(G.pace_callout("cyrus", rows, now + dt.timedelta(days=1)), first or "x")


class SaturdayStopsAtFive(unittest.TestCase):
    """Raf 2026-09-26: "Call outs need to stop at 5pm on Saturdays." A hard
    wall on the office's own clock, independent of anybody's bell -- Cyrus's
    Saturday bell is 17:15 and after_the_bell ran to 19:15, which is how
    call-outs were still landing at 6pm on a Saturday."""

    def test_saturday_before_five_is_fine(self):
        self.assertTrue(G.callouts_allowed(dt.datetime(2026, 9, 26, 16, 59)))

    def test_saturday_at_five_is_blocked(self):
        self.assertFalse(G.callouts_allowed(dt.datetime(2026, 9, 26, 17, 0)))

    def test_saturday_after_five_is_blocked(self):
        # The exact window that spammed tonight.
        self.assertFalse(G.callouts_allowed(dt.datetime(2026, 9, 26, 17, 43)))
        self.assertFalse(G.callouts_allowed(dt.datetime(2026, 9, 26, 18, 1)))
        self.assertFalse(G.callouts_allowed(dt.datetime(2026, 9, 26, 19, 14)))

    def test_weekday_evenings_are_not_cut_at_five(self):
        # Saturday's wall is Saturday's. A weekday runs to its own 8:30.
        for hour in (17, 18, 19):
            self.assertTrue(G.callouts_allowed(dt.datetime(2026, 9, 25, hour, 30)),
                            "Friday %d:30 must still call out" % hour)
        self.assertTrue(G.callouts_allowed(dt.datetime(2026, 9, 28, 20, 0)))   # Mon


class WeekdaysStopAtEightThirty(unittest.TestCase):
    """Raf 2026-09-28: call-outs stop at 8:30 PM, Monday-Friday, every office,
    on the office's own clock, unless the office asked for a different time."""

    MON = dt.date(2026, 9, 28)

    def _at(self, day, h, m):
        return dt.datetime(day.year, day.month, day.day, h, m)

    def test_829_fires_and_831_is_blocked_every_weekday(self):
        for offset in range(5):                      # Mon..Fri
            d = self.MON + dt.timedelta(days=offset)
            self.assertTrue(G.callouts_allowed(self._at(d, 20, 29)), d)
            self.assertFalse(G.callouts_allowed(self._at(d, 20, 31)), d)

    def test_830_itself_is_the_wall(self):
        self.assertFalse(G.callouts_allowed(self._at(self.MON, 20, 30)))
        self.assertFalse(G.callouts_allowed(self._at(self.MON, 22, 5)))

    def test_every_office_gets_the_default(self):
        for key in ("kash", "cyrus", "colten", "rafael", "carlos", ""):
            self.assertEqual(G.callout_cutoff(self._at(self.MON, 12, 0), key), (20, 30), key)

    def test_saturday_still_cuts_at_five(self):
        sat = dt.datetime(2026, 10, 3, 16, 59)
        self.assertTrue(G.callouts_allowed(sat))
        self.assertFalse(G.callouts_allowed(sat.replace(hour=17, minute=0)))
        self.assertFalse(G.callouts_allowed(sat.replace(hour=20, minute=29)))

    def test_sunday_gains_no_new_rule(self):
        # Sunday was never walled here; field hours keep it quiet. Unchanged.
        self.assertIsNone(G.callout_cutoff(dt.datetime(2026, 10, 4, 21, 0)))
        self.assertTrue(G.callouts_allowed(dt.datetime(2026, 10, 4, 21, 0)))

    def test_an_office_override_uses_its_own_time(self):
        from unittest import mock
        with mock.patch.dict(G.CALLOUT_CUTOFF_OVERRIDES, {"cyrus": "19:45"}):
            self.assertTrue(G.callouts_allowed(self._at(self.MON, 19, 44), "cyrus"))
            self.assertFalse(G.callouts_allowed(self._at(self.MON, 19, 46), "cyrus"))
            # Everybody else keeps 8:30.
            self.assertTrue(G.callouts_allowed(self._at(self.MON, 20, 29), "kash"))
            self.assertFalse(G.callouts_allowed(self._at(self.MON, 20, 31), "kash"))
            # A later override is honoured too.
        with mock.patch.dict(G.CALLOUT_CUTOFF_OVERRIDES, {"cyrus": "21:15"}):
            self.assertTrue(G.callouts_allowed(self._at(self.MON, 21, 0), "cyrus"))
            self.assertFalse(G.callouts_allowed(self._at(self.MON, 21, 15), "cyrus"))

    def test_an_override_never_moves_saturday(self):
        from unittest import mock
        with mock.patch.dict(G.CALLOUT_CUTOFF_OVERRIDES, {"cyrus": "21:15"}):
            self.assertFalse(G.callouts_allowed(dt.datetime(2026, 10, 3, 17, 30), "cyrus"))

    def test_run_skips_an_office_past_its_cutoff(self):
        """The run() gate reads the office's OWN clock: an Eastern office at
        8:31 its time is walled while the machine's clock still says 7:31."""
        from unittest import mock
        office = mock.Mock(campaign="att")
        book = mock.Mock()
        book.worksheet.return_value.get_all_values.return_value = [[]]
        logged = []
        with mock.patch.object(G.P, "approved_channels", return_value={"zed": [mock.Mock(id="C1")]}), \
                mock.patch.object(G.O, "get", return_value=office), \
                mock.patch.object(G.K, "_office_now", return_value=self._at(self.MON, 20, 31)), \
                mock.patch.object(G.K, "in_field_hours", side_effect=AssertionError("gate must come first")), \
                mock.patch.object(G, "_say", side_effect=AssertionError("must not post")):
            G.run(self.MON, send=True, book=book, log=logged.append)
        self.assertTrue(any("cutoff" in l for l in logged), logged)


class TheRoomItselfIsTheBackstop(unittest.TestCase):
    """already_said asks SLACK what is in the room, NOT our state file.

    That is the whole point: tonight's runaway happened because the state file
    was being clobbered, so a de-dupe built on that same file would have failed
    with it. This guard has to hold with the state file EMPTY.
    """

    class _Client:
        def __init__(self, texts):
            self.texts = texts
            self.calls = []

        def conversations_history(self, channel, oldest, limit):
            self.calls.append((channel, oldest, limit))
            return {"messages": [{"text": t} for t in self.texts]}

    NOW = dt.datetime(2026, 9, 26, 17, 43)
    LINE = "Logan, Jamarion and Madelene — 25 doors/hr 🏃💨"

    def test_it_blocks_a_repeat_with_no_state_at_all(self):
        import pathlib, tempfile
        from unittest import mock
        # State file deliberately absent -- the failure mode from tonight.
        with mock.patch.object(G, "STATE_PATH",
                               pathlib.Path(tempfile.mkdtemp()) / "gone.json"):
            self.assertEqual(G._state(), {})
            c = self._Client([self.LINE])
            self.assertTrue(G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=c))

    def test_a_new_line_still_gets_through(self):
        c = self._Client([self.LINE])
        self.assertFalse(
            G.already_said("C0B1DHEFVLH", "Something else entirely", self.NOW, client=c))

    def test_an_empty_room_lets_it_through(self):
        self.assertFalse(
            G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=self._Client([])))

    def test_whitespace_does_not_smuggle_a_duplicate_past_it(self):
        c = self._Client(["  " + self.LINE + "  "])
        self.assertTrue(G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=c))

    def test_it_only_looks_back_the_window(self):
        c = self._Client([])
        G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=c)
        _ch, oldest, _lim = c.calls[0]
        expected = (self.NOW - dt.timedelta(minutes=G.DUP_WINDOW_MIN)).timestamp()
        self.assertAlmostEqual(float(oldest), expected, places=3)

    def test_an_unreadable_room_fails_CLOSED(self):
        class Boom:
            def conversations_history(self, **_kw):
                raise RuntimeError("slack down")
        # A missed call-out costs one tick. Guessing the other way is ninety
        # copies, which is the thing that must never happen again.
        self.assertTrue(G.already_said("C0B1DHEFVLH", self.LINE, self.NOW, client=Boom()))

    def test_say_does_not_post_a_duplicate(self):
        from unittest import mock
        posted = []
        with mock.patch.object(G.P, "_slack", lambda ch, t: posted.append((ch, t))), \
                mock.patch.object(G, "already_said", lambda *a, **k: True):
            G._say("C0B1DHEFVLH", self.LINE, self.NOW, lambda *_a: None)
        self.assertEqual(posted, [])

    def test_say_posts_when_the_room_is_clear(self):
        from unittest import mock
        posted = []
        with mock.patch.object(G.P, "_slack", lambda ch, t: posted.append((ch, t))), \
                mock.patch.object(G, "already_said", lambda *a, **k: False):
            G._say("C0B1DHEFVLH", self.LINE, self.NOW, lambda *_a: None)
        self.assertEqual(posted, [("C0B1DHEFVLH", self.LINE)])


class TheDedupeSurvivesSlacksEmoji(unittest.TestCase):
    """2026-09-28: Slack returned ':stopwatch:' for our ⏱️, exact match failed,
    the same pace line posted twenty times."""

    def test_shortcode_and_emoji_compare_equal(self):
        ours = "Pace check ⏱️ Gabriel at 25 doors an hour. Keep that foot on the gas 🚀"
        theirs = "Pace check :stopwatch: Gabriel at 25 doors an hour. Keep that foot on the gas :rocket:"
        self.assertEqual(G._norm(ours), G._norm(theirs))
        self.assertNotEqual(G._norm(ours), G._norm(ours.replace("25", "26")))

    def test_already_said_matches_through_the_shortcodes(self):
        class C:
            def conversations_history(self, **kw):
                return {"messages": [{"text": "Pace check :stopwatch: Gabriel at 25 doors an hour. Keep that foot on the gas :rocket:"}]}
        self.assertTrue(G.already_said("C1", "Pace check ⏱️ Gabriel at 25 doors an hour. Keep that foot on the gas 🚀",
                                       dt.datetime(2026, 9, 28, 20, 0), client=C()))


class TheStateFileIsAtomicAndNeverSilentlyEmpty(unittest.TestCase):
    def test_a_corrupt_file_is_set_aside_not_read_as_empty_forever(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "s.json"
            path.write_text("{not json")
            with mock.patch.object(G, "STATE_PATH", path):
                self.assertEqual(G._state(), {})
                self.assertFalse(path.exists())                       # moved aside
                self.assertTrue(any(p.name.startswith("s.corrupt-") for p in pathlib.Path(d).iterdir()))
                G._save({"pace:x": {"day": "2026-09-28"}})
                self.assertEqual(G._state()["pace:x"]["day"], "2026-09-28")
                self.assertFalse(any(".tmp-" in p.name for p in pathlib.Path(d).iterdir()))


class ARewordedRepeatIsStillARepeat(unittest.TestCase):
    def test_two_templates_about_the_same_reps_match(self):
        a = "8 of y'all — 30+ min without a dispo. Lucy sees you, finger poppers 👀🤌\n• Jorge — 161 min\n• Ashley — 156 min"
        b = "Quiet check 🤫 8 of y'all — 30+ min without a door. Y'all finger poppin' each other out there? 🤌🤌\n• Jorge — 161 min\n• Ashley — 156 min"
        self.assertEqual(G._content_key(a), G._content_key(b))
        self.assertNotEqual(G._content_key(a), G._content_key(b.replace("156", "157")))

    def test_already_said_catches_the_rewording(self):
        class C:
            def conversations_history(self, **kw):
                return {"messages": [{"text": "8 of y'all — 30+ min without a dispo. Lucy sees you, finger poppers 👀🤌\n• Jorge — 161 min\n• Ashley — 156 min"}]}
        self.assertTrue(G.already_said("C1", "Quiet check 🤫 8 of y'all — 30+ min without a door. Y'all finger poppin' each other out there? 🤌🤌\n• Jorge — 161 min\n• Ashley — 156 min",
                                       dt.datetime(2026, 9, 28, 20, 30), client=C()))


class AMarkerWrittenMidRunSurvivesTheRun(unittest.TestCase):
    """2026-09-28 third cause: run()'s end-of-run save put yesterday's pace
    marker back over today's. A marker is now layered onto a fresh read."""

    def test_remember_never_puts_an_old_value_back(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "s.json"
            with mock.patch.object(G, "STATE_PATH", path):
                G._save({"pace:aya": {"day": "2026-09-27"}, "colten": {"day": "2026-09-28"}})
                stale = G._state()                                  # what a run loaded at its top
                G._remember("pace:aya", {"day": "2026-09-28"})      # pace judged mid-run
                G._remember("colten", stale["colten"])              # the run writes ITS key only
                self.assertEqual(G._state()["pace:aya"]["day"], "2026-09-28")

    def test_run_has_no_snapshot_save(self):
        import inspect
        src = inspect.getsource(G.run)
        self.assertNotIn("merged.update(state)", src)
        self.assertNotIn("_save(state)", src)


class ThePraiseLandsBeforeTheWall(unittest.TestCase):
    """Raf 2026-09-28: "Keep the praise one." The positive pace line goes out
    in the last minutes before the cutoff (or after an early bell), ONCE; the
    gap call-outs stay hard-cut at the cutoff."""

    from types import SimpleNamespace as _NS
    LATE = _NS(day_end="21:15", sat_end="17:15", saturday=True, campaign="att")    # cyrus-shaped
    EARLY = _NS(day_end="19:30", sat_end="16:30", saturday=True, campaign="b2b_box")  # ryan-shaped
    MON = dt.date(2026, 9, 28)
    SAT = dt.date(2026, 10, 3)

    def _at(self, day, h, m):
        return dt.datetime(day.year, day.month, day.day, h, m)

    # -- the every-minute poster ------------------------------------------
    def test_weekday_praise_is_the_last_minutes_before_830(self):
        w = G.praise_window
        self.assertFalse(w(self.LATE, self._at(self.MON, 20, 19)))
        self.assertTrue(w(self.LATE, self._at(self.MON, 20, 20)))
        self.assertTrue(w(self.LATE, self._at(self.MON, 20, 29)))

    def test_no_praise_at_or_after_the_cutoff(self):
        for h, m in ((20, 30), (20, 31), (21, 20), (22, 0)):
            self.assertFalse(G.praise_window(self.LATE, self._at(self.MON, h, m)), (h, m))

    def test_saturday_praise_is_just_before_five(self):
        self.assertFalse(G.praise_window(self.LATE, self._at(self.SAT, 16, 49)))
        self.assertTrue(G.praise_window(self.LATE, self._at(self.SAT, 16, 55)))
        self.assertFalse(G.praise_window(self.LATE, self._at(self.SAT, 17, 0)))
        self.assertFalse(G.praise_window(self.LATE, self._at(self.SAT, 17, 20)))

    def test_an_early_bell_keeps_its_after_the_bell_praise_capped_by_the_wall(self):
        self.assertFalse(G.praise_window(self.EARLY, self._at(self.MON, 19, 29)))
        self.assertTrue(G.praise_window(self.EARLY, self._at(self.MON, 19, 45)))
        self.assertFalse(G.praise_window(self.EARLY, self._at(self.MON, 20, 30)))
        self.assertTrue(G.praise_window(self.EARLY, self._at(self.SAT, 16, 45)))
        self.assertFalse(G.praise_window(self.EARLY, self._at(self.SAT, 17, 0)))

    def test_it_follows_an_office_override(self):
        from unittest import mock
        with mock.patch.dict(G.CALLOUT_CUTOFF_OVERRIDES, {"cyrus": "19:45"}):
            self.assertTrue(G.praise_window(self.LATE, self._at(self.MON, 19, 40), "cyrus"))
            self.assertFalse(G.praise_window(self.LATE, self._at(self.MON, 19, 45), "cyrus"))
            self.assertFalse(G.praise_window(self.LATE, self._at(self.MON, 20, 25), "cyrus"))

    def test_sunday_and_a_saturday_off_office_get_nothing(self):
        self.assertFalse(G.praise_window(self.LATE, self._at(dt.date(2026, 10, 4), 20, 25)))
        off = self._NS(day_end="21:15", sat_end="17:15", saturday=False)
        self.assertFalse(G.praise_window(off, self._at(self.SAT, 16, 55)))

    # -- the quarter-hour gap_alerts runner (Raf's own reps, Carlos's) ------
    def test_gap_alerts_praise_is_the_last_tick_before_the_cutoff(self):
        t = G.praise_tick
        self.assertFalse(t(self._at(self.MON, 20, 0), "rafael", (22, 0), 15))
        self.assertTrue(t(self._at(self.MON, 20, 15), "rafael", (22, 0), 15))
        self.assertFalse(t(self._at(self.MON, 20, 30), "rafael", (22, 0), 15))
        self.assertFalse(t(self._at(self.MON, 21, 45), "rafael", (22, 0), 15))   # the old last tick
        self.assertTrue(t(self._at(self.SAT, 16, 45), "rafael", (20, 0), 15))
        self.assertFalse(t(self._at(self.SAT, 17, 0), "rafael", (20, 0), 15))
        self.assertFalse(t(self._at(self.SAT, 19, 45), "rafael", (20, 0), 15))

    def test_gap_alerts_window_ending_first_keeps_the_old_last_tick(self):
        self.assertTrue(G.praise_tick(self._at(self.MON, 19, 30), "x", (19, 30), 15))
        self.assertFalse(G.praise_tick(self._at(self.MON, 19, 15), "x", (19, 30), 15))

    # -- end to end through run(): once, and the nag stays cut ---------------
    def _run_at(self, when, posted, logged):
        import json as _json
        from unittest import mock
        row = ["cyrus", self.MON.isoformat(), "[]", "[]", "0", "2026-09-28 20:00", "", ""]
        tabs = {G.K.KNOCKS_TAB: [["hdr"], row], G.P.RELAY_TAB: [["hdr"]]}
        book = mock.Mock()
        book.worksheet.side_effect = lambda name: mock.Mock(get_all_values=mock.Mock(return_value=tabs.get(name, [["hdr"]])))
        with mock.patch.object(G.P, "approved_channels", return_value={"cyrus": [mock.Mock(id="C1")]}), \
                mock.patch.object(G.O, "get", return_value=self.LATE), \
                mock.patch.object(G.K, "_office_now", return_value=when), \
                mock.patch.object(G.K, "in_field_hours", return_value=True), \
                mock.patch.object(G.K, "_too_old", return_value=False), \
                mock.patch.object(G.M, "to_rows", return_value=[{"Rep": "Nick Smith"}]), \
                mock.patch.object(G, "pick", return_value=[{"name": "Nick Smith", "mins": 45}]), \
                mock.patch.object(G, "pace", return_value=[{"name": "Nick Smith", "avg": 31}]), \
                mock.patch.object(G, "already_said", return_value=False), \
                mock.patch.object(G.P, "_slack", lambda ch, t: posted.append((when, t))):
            G.run(self.MON, send=True, book=book, log=logged.append)

    def test_praise_posts_once_before_the_wall_and_the_nag_stays_cut(self):
        import pathlib, tempfile
        from unittest import mock
        posted, logged = [], []
        with mock.patch.object(G, "STATE_PATH", pathlib.Path(tempfile.mkdtemp()) / "s.json"):
            # Every minute from 20:20 to 20:40, like the poster.
            for minute in range(20, 41):
                self._run_at(self._at(self.MON, 20, minute), posted, logged)
        praise = [p for p in posted if "Nick" in p[1] and "31" in p[1]]
        nags = [p for p in posted if "45" in p[1]]
        self.assertEqual(len(praise), 1, posted)
        self.assertEqual(praise[0][0], self._at(self.MON, 20, 20))
        # The nag may still post before 8:30 (on its own 30-min cadence), and
        # never at or after it.
        self.assertTrue(all(w < self._at(self.MON, 20, 30) for w, _t in nags), nags)
        self.assertTrue(any("cutoff" in l for l in logged))

    def test_nothing_at_all_after_the_cutoff(self):
        import pathlib, tempfile
        from unittest import mock
        posted, logged = [], []
        with mock.patch.object(G, "STATE_PATH", pathlib.Path(tempfile.mkdtemp()) / "s.json"):
            for h, m in ((20, 30), (20, 45), (21, 16), (21, 30)):
                self._run_at(self._at(self.MON, h, m), posted, logged)
        self.assertEqual(posted, [])


class AnOfficeCanOptOutOfCallOuts(unittest.TestCase):
    def test_colten_is_out_although_nds_is_in(self):
        self.assertIn("nds", G.CALLOUT_CAMPAIGNS)
        self.assertIn("colten", G.CALLOUT_OPT_OUT)
        import inspect
        src = inspect.getsource(G.run)
        self.assertGreaterEqual(src.count("CALLOUT_OPT_OUT"), 2, "both the gap loop and the pace loop must check it")


class TheWordingFollowsTheServiceCloudAccount(unittest.TestCase):
    """Megan 2026-10-01: anyone whose alerts come off the Service Cloud account
    gets the B2B wording. The switch is config.SERVICECLOUD_CAMPAIGNS."""

    def test_every_servicecloud_campaign_gets_business_talk(self):
        from automations.icd_alerts import config as C
        for camp in C.SERVICECLOUD_CAMPAIGNS:
            self.assertTrue(G.is_box(camp), camp)
            self.assertIs(G.lines_for(camp), G.B2B_LINES)
            self.assertIs(G.pace_lines_for(camp), G.B2B_PACE_LINES)
            self.assertEqual(G.pace_units(camp)[0], "talk-to's")
            self.assertEqual(G.pace_target(camp), G.PACE_BOX_TT_PER_HOUR)

    def test_every_b2b_campaign_gets_business_talk_whatever_it_sells(self):
        # Megan 2026-10-01: any B2B enrollment regardless of campaign.
        from automations.icd_alerts import config as C
        for camp in C.B2B_CAMPAIGNS + ("b2b_att", "B2B_Att", "b2b_fiber"):
            self.assertTrue(G.is_b2b(camp), camp)
            self.assertIs(G.lines_for(camp), G.B2B_LINES)
            self.assertIs(G.pace_lines_for(camp), G.B2B_PACE_LINES)
        self.assertEqual(G.pace_units("b2b_att"), ("walk-ins", "visitas"))
        # Only Box is judged on talk-to's; b2b_att is still counted on its knocks.
        self.assertFalse(G.is_box("b2b_att"))
        self.assertEqual(G.pace_target("b2b_att"), G.PACE_KNOCKS_PER_HOUR)

    def test_d2d_keeps_doors(self):
        for camp in ("att", "nds", "energy", None, ""):
            self.assertFalse(G.is_box(camp))
            self.assertFalse(G.is_b2b(camp))
            self.assertIs(G.lines_for(camp), G.LINES)
            self.assertIs(G.pace_lines_for(camp), G.PACE_LINES)

    def test_a_campaign_added_to_the_account_later_is_covered(self):
        from automations.icd_alerts import config as C
        with mock.patch.object(C, "SERVICECLOUD_CAMPAIGNS", ("b2b_box", "b2b_energy")):
            self.assertIs(G.lines_for("b2b_energy"), G.B2B_LINES)
            self.assertEqual(G.pace_units("b2b_energy")[0], "talk-to's")

    def test_box_pace_recognition_never_says_doors(self):
        rows = [{"Rep": "Bo Box", "Total Knocks": 40, "Corp - No Opp": 2, "Inaccessible": 1,
                 "Inaccurate Lead": 0, "First Knock": "8:00 AM", "Last Knock": "11:00 AM"}]
        for h in range(24):
            n = NOW.replace(hour=h)
            s = G.pace_line("ryan", G.pace(rows, n, "b2b_box"), n, "b2b_box")
            if s:
                for bad in ("door", "puerta", "neighborhood", "🚪"):
                    self.assertNotIn(bad, s.lower(), s)


class ReceiptsTest(unittest.TestCase):
    """Megan 2026-10-07 ("do 1"): a rep called out last tick who has a credit
    check or a sale behind the quiet by this tick gets told so, by name. The
    "you showed me" moment -- never a tally, never a league table."""

    def test_only_the_called_who_moved(self):
        called = ["Tyrone Barnett", "Nashly Paul", "Hank Tran"]
        prev = {"tyrone barnett": 2, "nashly paul": 0, "hank tran": 1}
        now = {"tyrone barnett": 3, "nashly paul": 0, "hank tran": 1, "someone else": 9}
        self.assertEqual(G.receipts(called, now, prev), ["Tyrone Barnett"])

    def test_nobody_called_means_nobody_proven(self):
        self.assertEqual(G.receipts([], {"a b": 5}, {}), [])

    def test_line_names_first_names_and_reads_in_english(self):
        s = G.receipt_line("x", ["Tyrone Barnett", "Nashly Paul"], NOW)
        self.assertIn("Tyrone and Nashly", s)
        self.assertNotIn(" y ", s)
        self.assertNotIn("{names}", s)

    def test_same_hour_repeats_next_hour_differs(self):
        a = G.receipt_line("x", ["Tyrone B"], NOW)
        self.assertEqual(a, G.receipt_line("x", ["Tyrone B"], NOW))
        pool_size = len(G.RECEIPT_LINES)
        others = {G.receipt_line("x", ["Tyrone B"], NOW.replace(hour=h)) for h in range(24)}
        self.assertGreater(len(others), min(3, pool_size - 1))

    def test_box_office_gets_sale_wording_not_credit_checks(self):
        s = G.receipt_line("ryan", ["Miguel R"], NOW, campaign="b2b_box")
        self.assertNotIn("credit check", s.lower())
        self.assertIn("Miguel", s)

    def test_no_names_is_no_message(self):
        self.assertEqual(G.receipt_line("x", [], NOW), "")


class AnswerBackTest(unittest.TestCase):
    """Megan 2026-10-07 ("do 4"): a reply that calls a call-out snitching or
    lying earns ONE answer in that thread, in the house voice."""

    def test_snitch_gets_the_hype_answer(self):
        a = G.answer_for("lucy snitched already bro", "s1")
        self.assertIn(a, G.SNITCH_REPLIES)

    def test_liar_gets_the_board_answer(self):
        a = G.answer_for("Lucy u lying on me", "s1")
        self.assertIn(a, G.LIAR_REPLIES)
        self.assertIn(G.answer_for("Lucy you a liar", "s2"), G.LIAR_REPLIES)

    def test_anything_else_earns_nothing(self):
        self.assertEqual(G.answer_for("I'm in a cc chill", "s1"), "")
        self.assertEqual(G.answer_for("Ok Lucy", "s1"), "")
        self.assertEqual(G.answer_for("", "s1"), "")

    def test_same_thread_same_answer(self):
        self.assertEqual(G.answer_for("snitch", "x"), G.answer_for("SNITCHING", "x"))

    def test_answers_once_per_thread_and_never_itself(self):
        class Client:
            def __init__(self):
                self.posted = []
            def auth_test(self):
                return {"user_id": "ULUCY"}
            def conversations_history(self, channel, oldest, limit):
                return {"messages": [
                    {"ts": "1.0", "user": "ULUCY", "reply_count": 2, "text": "Snicklemeberries ..."},
                    {"ts": "2.0", "user": "ULUCY", "reply_count": 1, "text": "another call-out"},
                    {"ts": "3.0", "user": "UREP", "reply_count": 3, "text": "a rep's own post"},
                ]}
            def conversations_replies(self, channel, ts, limit):
                if ts == "1.0":
                    return {"messages": [{"ts": "1.0", "user": "ULUCY"},
                                         {"ts": "1.1", "user": "UREP", "text": "lucy snitched"}]}
                return {"messages": [{"ts": "2.0", "user": "ULUCY"},
                                     {"ts": "2.1", "user": "UREP", "text": "liar"},
                                     {"ts": "2.2", "user": "ULUCY", "text": "already answered"}]}
        posted = []
        with mock.patch.object(G, "_state", return_value={}), \
             mock.patch.object(G, "_remember", lambda k, v: None), \
             mock.patch.object(G.P, "_slack", lambda ch, text, thread_ts=None: posted.append((ch, thread_ts, text))):
            said = G.answer_back(NOW, send=True, log=lambda m: None, channels=["C1"], client=Client())
        self.assertEqual(len(said), 1)
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0][1], "1.0")
        self.assertIn(posted[0][2], G.SNITCH_REPLIES)


class AnswerBackB2BTest(unittest.TestCase):
    def test_a_business_room_never_hears_about_doors(self):
        for h in range(40):
            a = G.answer_for("snitch", "seed%d" % h, campaign="b2b_box")
            self.assertNotIn("knock", a.lower(), a)
            self.assertIn(a, G.SNITCH_REPLIES_B2B)

    def test_a_door_room_keeps_the_knock_line(self):
        self.assertIn("¡Tranquilo! Not snitching, hyping 📣 Go knock another! 🚪", G.SNITCH_REPLIES)
